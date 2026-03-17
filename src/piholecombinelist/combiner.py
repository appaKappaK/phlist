"""Orchestrate fetching, parsing, and deduplication into a combined blocklist."""
# v1.0.1

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .deduplicator import Deduplicator
from .parser import ListParser

_log = logging.getLogger(__name__)


class ListCombiner:
    """Combine multiple blocklist sources into one deduplicated list."""

    def __init__(self) -> None:
        self._parser = ListParser()
        self._dedup = Deduplicator()
        self._total_lines = 0
        self._lists_processed = 0

    def add_list(self, content: str, source: str = "unknown") -> int:
        """
        Parse content and add valid domains. Returns the number of new domains added.
        """
        lines = content.splitlines()
        self._total_lines += len(lines)
        before = self._dedup.count

        for line in lines:
            domain = self._parser.parse_line(line)
            if domain:
                self._dedup.add(domain)

        self._lists_processed += 1
        added = self._dedup.count - before
        _log.info("Added list '%s': %d new domains (%d total)", source, added, self._dedup.count)
        return added

    def get_combined(self, include_header: bool = True, list_type: str = "Blocklist",
                     credits: Optional[list] = None) -> str:
        """Return the full combined list as a string, sorted alphabetically."""
        lines = []

        if include_header:
            lines += [
                f"# Pi-hole Combined {list_type}",
                f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"# Unique domains: {self._dedup.count}",
                f"# Duplicates removed: {self._dedup.duplicates}",
                f"# Lists combined: {self._lists_processed}",
            ]
            if credits:
                lines.append(f"# Credits: {', '.join(credits)}")
            lines.append("")

        lines.extend(sorted(self._dedup.domains))
        _log.info("Combine complete: %d unique, %d duplicates, %d lists",
                   self._dedup.count, self._dedup.duplicates, self._lists_processed)
        return "\n".join(lines)

    def save(self, filename: str, include_header: bool = True) -> None:
        """Write the combined list to a file."""
        Path(filename).write_text(self.get_combined(include_header), encoding="utf-8")

    def get_stats(self) -> dict:
        return {
            "total_lines": self._total_lines,
            "lists_processed": self._lists_processed,
            "unique_domains": self._dedup.count,
            "duplicates_removed": self._dedup.duplicates,
        }

    def clear(self) -> None:
        """Reset state for a new run."""
        self._dedup.clear()
        self._total_lines = 0
        self._lists_processed = 0
