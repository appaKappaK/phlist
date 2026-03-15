"""Fetch blocklist content from URLs or local files."""
# v1.0.0

import time
from pathlib import Path
from typing import Optional

import requests


class ListFetcher:
    """Fetch raw blocklist text from a URL or local file path."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "PiHoleCombineList/1.0.0"
        self.successful = 0
        self.failed = 0
        self.total_bytes = 0

    def fetch(self, source: str) -> Optional[str]:
        """Auto-detect URL vs file path and fetch accordingly."""
        if source.startswith(("http://", "https://")):
            return self.fetch_url(source)
        return self.fetch_file(source)

    def fetch_url(self, url: str) -> Optional[str]:
        """Fetch a blocklist from a URL. Returns content or None on failure."""
        try:
            response = self._session.get(url, timeout=self.timeout)
            response.raise_for_status()
            content = response.text
            self.successful += 1
            self.total_bytes += len(content.encode())
            time.sleep(0.5)
            return content
        except requests.RequestException as exc:
            print(f"Failed to fetch {url}: {exc}")
            self.failed += 1
            return None

    def fetch_file(self, path: str) -> Optional[str]:
        """Read a blocklist from a local file. Returns content or None on failure."""
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            self.successful += 1
            self.total_bytes += len(content.encode())
            return content
        except OSError as exc:
            print(f"Failed to read {path}: {exc}")
            self.failed += 1
            return None

    def get_stats(self) -> dict:
        return {
            "successful": self.successful,
            "failed": self.failed,
            "total_bytes": self.total_bytes,
        }
