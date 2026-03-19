"""Fetch blocklist content from URLs or local files."""
# v1.1.3

import ipaddress
import logging
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

_log = logging.getLogger(__name__)

# GitHub blob URL → raw URL conversion
# e.g. https://github.com/user/repo/blob/branch/file.txt
#    → https://raw.githubusercontent.com/user/repo/refs/heads/branch/file.txt
_GITHUB_BLOB_RE = re.compile(
    r'^https?://github\.com/([^/]+/[^/]+)/blob/(.+)$'
)

# Maximum response body accepted (50 MB). Larger responses are rejected to
# prevent memory exhaustion from malicious or runaway list servers.
_MAX_FETCH_BYTES = 50 * 1024 * 1024

from . import __version__


def _is_private_url(url: str) -> bool:
    """Return True if *url* resolves to a private/loopback IP address literal."""
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False  # hostname string — not a bare IP, can't classify here


class ListFetcher:
    """Fetch raw blocklist text from a URL or local file path."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = f"phlist/{__version__}"
        self.successful = 0
        self.failed = 0
        self.total_bytes = 0

    def fetch(self, source: str) -> Optional[str]:
        """Auto-detect URL vs file path and fetch accordingly."""
        if source.startswith(("http://", "https://")):
            return self.fetch_url(source)
        return self.fetch_file(source)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Convert GitHub blob URLs to raw URLs so we fetch plain text."""
        m = _GITHUB_BLOB_RE.match(url)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/refs/heads/{m.group(2)}"
        return url

    def fetch_url(self, url: str) -> Optional[str]:
        """Fetch a blocklist from a URL. Returns content or None on failure."""
        url = self._normalize_url(url)
        _log.info("Fetching URL: %s", url)
        try:
            response = self._session.get(url, timeout=self.timeout)
            response.raise_for_status()

            # Reject redirect to private/loopback IP (SSRF defence)
            if response.url != url and _is_private_url(response.url):
                _log.warning("Rejected redirect to private address: %s → %s", url, response.url)
                self.failed += 1
                return None

            # Reject oversized responses (Content-Length header check)
            cl = response.headers.get("Content-Length")
            if cl:
                try:
                    if int(cl) > _MAX_FETCH_BYTES:
                        _log.warning("Skipping %s — Content-Length %s exceeds limit", url, cl)
                        self.failed += 1
                        return None
                except ValueError:
                    pass  # malformed header; proceed and check body size below

            content = response.text

            # Reject oversized body (no Content-Length or compressed response)
            if len(content.encode()) > _MAX_FETCH_BYTES:
                _log.warning("Skipping %s — response body exceeds size limit", url)
                self.failed += 1
                return None

            # Strip null bytes — undefined behaviour in Tkinter / some SQLite builds
            content = content.replace("\x00", "")

            content_bytes = len(content.encode())
            self.successful += 1
            self.total_bytes += content_bytes
            _log.info("Fetched %d bytes from %s", content_bytes, url)
            time.sleep(0.5)
            return content
        except requests.RequestException as exc:
            _log.warning("Failed to fetch %s: %s", url, exc)
            self.failed += 1
            return None

    def fetch_file(self, path: str) -> Optional[str]:
        """Read a blocklist from a local file. Returns content or None on failure."""
        _log.info("Reading file: %s", path)
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            content_bytes = len(content.encode())
            self.successful += 1
            self.total_bytes += content_bytes
            _log.info("Read %d bytes from %s", content_bytes, path)
            return content
        except OSError as exc:
            _log.warning("Failed to read %s: %s", path, exc)
            self.failed += 1
            return None

    def get_stats(self) -> dict:
        return {
            "successful": self.successful,
            "failed": self.failed,
            "total_bytes": self.total_bytes,
        }
