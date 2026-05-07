"""Re-fetch sources and re-combine a saved list without any GUI dependency.

Note: combine_tab._run_combine() has a similar fetch→combine pipeline but adds
session-scoped caching and credit extraction.  The two are intentionally separate
because their requirements diverge enough that a shared abstraction would be more
complex than the small amount of duplicated logic.
"""

import json
import logging
from typing import List, Tuple

from .combiner import ListCombiner
from .fetcher import ListFetcher

_log = logging.getLogger(__name__)


def has_fetchable_sources(sources_json: str) -> bool:
    """Return True if *sources_json* contains at least one url or file entry."""
    if not sources_json:
        return False
    try:
        sources = json.loads(sources_json)
    except (json.JSONDecodeError, TypeError):
        return False
    return any(s.get("type") in ("url", "file") for s in sources)


def update_list(
    sources_json: str,
    list_type: str = "Blocklist",
    timeout: int = 30,
    max_bytes: int = 50 * 1024 * 1024,
) -> Tuple[str, int, int, List[str]]:
    """Re-fetch all sources and re-combine.

    Returns ``(content, domain_count, duplicates_removed, failed_sources)``.
    If **all** sources fail, *content* is the empty string — the caller should
    keep the old saved content rather than overwriting with nothing.
    ``max_bytes`` is the per-source URL size cap.
    """
    try:
        sources = json.loads(sources_json)
    except (json.JSONDecodeError, TypeError):
        _log.warning("Invalid sources JSON: %s", sources_json)
        return ("", 0, 0, [sources_json or "(empty)"])
    _log.info("Update started: %d source(s)", len(sources))
    fetcher = ListFetcher(timeout=timeout, max_bytes=max_bytes)
    combiner = ListCombiner()
    failed: List[str] = []

    for src in sources:
        label = src.get("label", "")
        raw = fetcher.fetch(label)
        if raw is not None:
            combiner.add_list(raw, label)
        else:
            failed.append(label)

    stats = combiner.get_stats()
    if stats["unique_domains"] == 0:
        _log.warning("Update produced 0 domains — all sources failed")
        return ("", 0, 0, failed)

    content = combiner.get_combined(list_type=list_type)
    _log.info("Update complete: %d domains, %d failed source(s)",
              stats["unique_domains"], len(failed))
    return (content, stats["unique_domains"], stats["duplicates_removed"], failed)
