"""Tests for ListFetcher."""

from unittest.mock import MagicMock, patch

import pytest
from phlist.fetcher import ListFetcher


def test_fetch_file_success(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text("example.com\nads.com\n")
    fetcher = ListFetcher()
    content = fetcher.fetch_file(str(f))
    assert "example.com" in content
    assert fetcher.successful == 1
    assert fetcher.failed == 0


def test_fetch_file_not_found():
    fetcher = ListFetcher()
    result = fetcher.fetch_file("/nonexistent/path/list.txt")
    assert result is None
    assert fetcher.failed == 1
    assert fetcher.successful == 0


def test_fetch_routes_to_file(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text("domain.com\n")
    fetcher = ListFetcher()
    content = fetcher.fetch(str(f))
    assert content is not None
    assert "domain.com" in content


def test_fetch_routes_url_prefix():
    """fetch() should attempt URL fetch for http:// prefix (will fail without network,
    but we verify it increments failed and returns None gracefully)."""
    fetcher = ListFetcher(timeout=1)
    result = fetcher.fetch("http://localhost:19999/nonexistent")
    assert result is None
    assert fetcher.failed == 1


def test_stats_total_bytes(tmp_path):
    f = tmp_path / "list.txt"
    content = "example.com\nads.com\n"
    f.write_text(content)
    fetcher = ListFetcher()
    fetcher.fetch_file(str(f))
    assert fetcher.total_bytes == len(content.encode())


@pytest.mark.parametrize("blob_url,expected_raw", [
    (
        "https://github.com/Perflyst/PiHoleBlocklist/blob/master/android-tracking.txt",
        "https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/refs/heads/master/android-tracking.txt",
    ),
    (
        "https://github.com/user/repo/blob/main/lists/ads.txt",
        "https://raw.githubusercontent.com/user/repo/refs/heads/main/lists/ads.txt",
    ),
])
def test_normalize_github_blob_to_raw(blob_url, expected_raw):
    assert ListFetcher._normalize_url(blob_url) == expected_raw


def test_normalize_leaves_raw_url_unchanged():
    raw = "https://raw.githubusercontent.com/user/repo/refs/heads/main/list.txt"
    assert ListFetcher._normalize_url(raw) == raw


def test_normalize_leaves_non_github_unchanged():
    url = "https://example.com/blocklist.txt"
    assert ListFetcher._normalize_url(url) == url


def test_fetch_file_empty(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    fetcher = ListFetcher()
    result = fetcher.fetch_file(str(f))
    assert result == ""
    assert fetcher.successful == 1


def _mock_response(text: str, url: str = "https://example.com/list.txt",
                   headers: dict | None = None) -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.text = text
    resp.url = url
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_url_success():
    fetcher = ListFetcher()
    body = "example.com\nads.net\n"
    with patch.object(fetcher._session, "get", return_value=_mock_response(body)):
        result = fetcher.fetch_url("https://example.com/list.txt")
    assert result == body
    assert fetcher.successful == 1
    assert fetcher.total_bytes == len(body.encode())


def test_fetch_url_size_limit_content_length():
    fetcher = ListFetcher()
    big_cl = str(fetcher._max_bytes + 1)
    resp = _mock_response("x", headers={"Content-Length": big_cl})
    with patch.object(fetcher._session, "get", return_value=resp):
        result = fetcher.fetch_url("https://example.com/list.txt")
    assert result is None
    assert fetcher.failed == 1


def test_fetch_url_size_limit_body():
    fetcher = ListFetcher()
    # Body just over the limit, no Content-Length header
    big_body = "a" * (fetcher._max_bytes + 1)
    with patch.object(fetcher._session, "get", return_value=_mock_response(big_body)):
        result = fetcher.fetch_url("https://example.com/list.txt")
    assert result is None
    assert fetcher.failed == 1


def test_fetch_url_null_bytes_stripped():
    fetcher = ListFetcher()
    body = "example.com\x00\nadvertising.net\x00extra\n"
    with patch.object(fetcher._session, "get", return_value=_mock_response(body)):
        result = fetcher.fetch_url("https://example.com/list.txt")
    assert result is not None
    assert "\x00" not in result
    assert "example.com" in result
    assert "advertising.net" in result


def test_fetch_url_redirect_to_private_ip_rejected():
    fetcher = ListFetcher()
    # Final URL after redirect resolves to a private IP literal
    resp = _mock_response("example.com\n", url="http://192.168.1.1/malicious.txt")
    with patch.object(fetcher._session, "get", return_value=resp):
        result = fetcher.fetch_url("https://example.com/list.txt")
    assert result is None
    assert fetcher.failed == 1


def test_fetcher_custom_max_bytes():
    fetcher = ListFetcher(max_bytes=1024)
    assert fetcher._max_bytes == 1024
