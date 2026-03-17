"""Tests for the multi-path HTTP server."""

import time
import urllib.request
import urllib.error

import pytest

from phlist.server import ListServer
from phlist.gui.library_tab import _slugify


# Use a high port to avoid conflicts
_PORT = 18765


@pytest.fixture()
def server():
    srv = ListServer(port=_PORT)
    yield srv
    srv.stop()


def _get(path: str) -> tuple[int, str]:
    """GET http://localhost:{_PORT}{path}, return (status, body)."""
    url = f"http://127.0.0.1:{_PORT}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""


# ── add_path / start ──────────────────────────────────────────

def test_add_path_starts_server(server: ListServer):
    url = server.add_path("/test.txt", "hello")
    assert server.is_running
    assert "/test.txt" in url
    time.sleep(0.1)
    status, body = _get("/test.txt")
    assert status == 200
    assert body == "hello"


def test_two_paths_simultaneously(server: ListServer):
    server.add_path("/general.txt", "general domains")
    server.add_path("/tvs.txt", "tv domains")
    time.sleep(0.1)
    s1, b1 = _get("/general.txt")
    s2, b2 = _get("/tvs.txt")
    assert s1 == 200 and b1 == "general domains"
    assert s2 == 200 and b2 == "tv domains"


def test_unknown_path_returns_404(server: ListServer):
    server.add_path("/exists.txt", "data")
    time.sleep(0.1)
    status, _ = _get("/nope.txt")
    assert status == 404


# ── remove_path ───────────────────────────────────────────────

def test_remove_last_path_stops_server(server: ListServer):
    server.add_path("/only.txt", "data")
    assert server.is_running
    server.remove_path("/only.txt")
    assert not server.is_running


def test_remove_one_of_two_keeps_server(server: ListServer):
    server.add_path("/a.txt", "aaa")
    server.add_path("/b.txt", "bbb")
    server.remove_path("/a.txt")
    assert server.is_running
    time.sleep(0.1)
    status, body = _get("/b.txt")
    assert status == 200 and body == "bbb"
    s_a, _ = _get("/a.txt")
    assert s_a == 404


def test_remove_nonexistent_path_is_safe(server: ListServer):
    server.add_path("/x.txt", "x")
    server.remove_path("/does-not-exist.txt")  # should not raise
    assert server.is_running


# ── stop ──────────────────────────────────────────────────────

def test_stop_clears_all_paths(server: ListServer):
    server.add_path("/a.txt", "a")
    server.add_path("/b.txt", "b")
    server.stop()
    assert not server.is_running
    assert not server.has_path("/a.txt")
    assert not server.has_path("/b.txt")


# ── has_path / url_for ────────────────────────────────────────

def test_has_path(server: ListServer):
    server.add_path("/check.txt", "data")
    assert server.has_path("/check.txt")
    assert not server.has_path("/other.txt")


def test_url_for(server: ListServer):
    url = server.url_for("/my-list.txt")
    assert url.endswith(f":{_PORT}/my-list.txt")
    assert url.startswith("http://")


# ── _slugify ──────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("My General List", "my-general-list"),
    ("TVs & Smart Devices", "tvs-smart-devices"),
    ("  spaces  ", "spaces"),
    ("UPPER", "upper"),
    ("already-slug", "already-slug"),
    ("!!!???", "list"),  # all non-alnum → fallback
    ("test123", "test123"),
])
def test_slugify(name, expected):
    assert _slugify(name) == expected
