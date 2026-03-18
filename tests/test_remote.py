"""Tests for remote server integration (push_list / test_connection)."""

from unittest.mock import MagicMock, patch
import urllib.error

import pytest
from phlist.remote import push_list, check_connection


# ── push_list ────────────────────────────────────────────────────────

@patch("phlist.remote.urllib.request.urlopen")
def test_push_list_success(mock_urlopen):
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    ok, msg = push_list("http://server:8765", "secret", "general", "ads.com\ntracker.net\n")

    assert ok is True
    assert "http://server:8765/lists/general.txt" in msg
    # Verify the request was a PUT with correct auth
    req = mock_urlopen.call_args[0][0]
    assert req.method == "PUT"
    assert req.get_header("Authorization") == "Bearer secret"
    assert req.get_header("Content-type") == "text/plain; charset=utf-8"


@patch("phlist.remote.urllib.request.urlopen")
def test_push_list_http_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "http://server:8765/lists/x.txt", 403, "Forbidden", {}, None
    )

    ok, msg = push_list("http://server:8765", "bad-key", "x", "content")

    assert ok is False
    assert "403" in msg
    assert "Forbidden" in msg


@patch("phlist.remote.urllib.request.urlopen")
def test_push_list_connection_error(mock_urlopen):
    mock_urlopen.side_effect = ConnectionRefusedError("Connection refused")

    ok, msg = push_list("http://unreachable:8765", "key", "list", "content")

    assert ok is False
    assert "refused" in msg.lower()


@patch("phlist.remote.urllib.request.urlopen")
def test_push_list_url_trailing_slash(mock_urlopen):
    """Trailing slash on base_url should not produce double slashes."""
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    push_list("http://server:8765/", "key", "my-list", "content")

    req = mock_urlopen.call_args[0][0]
    assert "//lists" not in req.full_url


# ── test_connection ──────────────────────────────────────────────────

@patch("phlist.remote.urllib.request.urlopen")
def test_connection_success(mock_urlopen):
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    ok, msg = check_connection("http://server:8765", "secret")

    assert ok is True
    assert "200" in msg
    req = mock_urlopen.call_args[0][0]
    assert req.method == "GET"
    assert req.get_header("Authorization") == "Bearer secret"


@patch("phlist.remote.urllib.request.urlopen")
def test_connection_http_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "http://server:8765/health", 401, "Unauthorized", {}, None
    )

    ok, msg = check_connection("http://server:8765", "wrong-key")

    assert ok is False
    assert "401" in msg


@patch("phlist.remote.urllib.request.urlopen")
def test_connection_unreachable(mock_urlopen):
    mock_urlopen.side_effect = OSError("Network is unreachable")

    ok, msg = check_connection("http://down:8765", "key")

    assert ok is False
    assert "unreachable" in msg.lower()
