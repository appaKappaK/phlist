"""Tests for ListFetcher."""

import pytest
from piholecombinelist.fetcher import ListFetcher


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
