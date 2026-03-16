"""Minimal HTTP server that serves the combined blocklist as plain text."""
# v1.0.0

import http.server
import socket
import socketserver
import threading
from typing import Optional


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
    """Serves a blocklist as plain text over HTTP on /blocklist.txt."""

    DEFAULT_PORT = 8765

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self._port = port
        self._server: Optional[_ReuseAddrServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self, content: str) -> str:
        """Start serving *content*. Returns the URL to add to Pi-hole's Adlists."""
        if self._server:
            self.stop()

        payload = content.encode("utf-8")

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path in ("/", "/blocklist.txt"):
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

        self._server = _ReuseAddrServer(("0.0.0.0", self._port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="phlist-server"
        )
        self._thread.start()
        return f"http://{_local_ip()}:{self._port}/blocklist.txt"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None
