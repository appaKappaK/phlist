"""Minimal HTTP server that serves combined blocklists as plain text."""
# v1.7.0

import http.server
import logging
import socket
import socketserver
import threading
from typing import Optional

_log = logging.getLogger(__name__)


def _local_ip() -> str:
    """Return this machine's LAN IP (the one Pi-hole on the network can reach)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no data sent — just picks the right interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class _ReuseAddrServer(socketserver.TCPServer):
    allow_reuse_address = True


class ListServer:
    """Serves one or more blocklists as plain text over HTTP on distinct paths."""

    DEFAULT_PORT = 8765

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self._port = port
        self._server: Optional[_ReuseAddrServer] = None
        self._thread: Optional[threading.Thread] = None
        self._paths: dict[str, bytes] = {}

    @property
    def is_running(self) -> bool:
        return self._server is not None

    # ── Public API ────────────────────────────────────────────────

    def add_path(self, path: str, content: str) -> str:
        """Register *path* with *content*. Starts the server if needed.

        Returns the full URL for that path.
        """
        self._paths[path] = content.encode("utf-8")
        if not self._server:
            self._start_server()
        url = f"http://{_local_ip()}:{self._port}{path}"
        _log.info("Path added: %s", url)
        return url

    def remove_path(self, path: str) -> None:
        """Remove *path*. Stops the server when no paths remain."""
        self._paths.pop(path, None)
        _log.info("Path removed: %s", path)
        if not self._paths:
            self._stop_server()

    def start(self, content: str) -> str:
        """Compatibility wrapper: serve *content* at ``/blocklist.txt``."""
        return self.add_path("/blocklist.txt", content)

    def stop(self) -> None:
        """Full shutdown: clear all paths and stop the server."""
        self._paths.clear()
        self._stop_server()

    def has_path(self, path: str) -> bool:
        return path in self._paths

    def url_for(self, path: str) -> str:
        """Return the full URL for an already-registered *path*."""
        return f"http://{_local_ip()}:{self._port}{path}"

    # ── Internal ──────────────────────────────────────────────────

    def _start_server(self) -> None:
        paths = self._paths  # reference — handler always sees latest entries

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                payload = paths.get(self.path)
                if payload is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *_):
                pass  # silence request logs

        try:
            self._server = _ReuseAddrServer(("0.0.0.0", self._port), _Handler)
        except OSError as exc:
            _log.warning("Failed to bind port %d: %s", self._port, exc)
            raise
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="phlist-server"
        )
        self._thread.start()
        _log.info("Server started on port %d", self._port)

    def _stop_server(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None
