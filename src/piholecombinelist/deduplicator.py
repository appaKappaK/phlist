"""Track unique domains and count duplicates."""
# v1.0.0

from typing import Set


class Deduplicator:
    """Set-based domain deduplicator with duplicate counting."""

    def __init__(self) -> None:
        self._domains: Set[str] = set()
        self._duplicates: int = 0

    def add(self, domain: str) -> bool:
        """
        Add a domain. Returns True if it was new, False if it was a duplicate.
        """
        if domain in self._domains:
            self._duplicates += 1
            return False
        self._domains.add(domain)
        return True

    @property
    def domains(self) -> Set[str]:
        return self._domains

    @property
    def count(self) -> int:
        return len(self._domains)

    @property
    def duplicates(self) -> int:
        return self._duplicates

    def clear(self) -> None:
        self._domains.clear()
        self._duplicates = 0
