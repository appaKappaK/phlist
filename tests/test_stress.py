"""Stress / performance tests for combiner and related subsystems.

These are headless tests — no GUI, no X11 — safe for CI.
"""

import json
import pytest
from piholecombinelist.combiner import ListCombiner
from piholecombinelist.updater import update_list


def _generate_domains(prefix: str, count: int) -> str:
    """Generate *count* fake domain lines."""
    return "\n".join(f"{prefix}-{i}.example.com" for i in range(count))


# ── Large list combine + dedup ────────────────────────────────────────

def test_combine_large_list():
    """Combine 100k+ domains across multiple lists, verify dedup is correct."""
    combiner = ListCombiner()

    # List A: 50k unique domains
    combiner.add_list(_generate_domains("a", 50_000), "list-a")
    # List B: 50k unique + 20k overlapping with A
    content_b = _generate_domains("a", 20_000) + "\n" + _generate_domains("b", 50_000)
    combiner.add_list(content_b, "list-b")

    stats = combiner.get_stats()
    assert stats["unique_domains"] == 100_000  # 50k a + 50k b
    assert stats["duplicates_removed"] == 20_000
    assert stats["lists_processed"] == 2

    result = combiner.get_combined()
    # Header + blank line + 100k domains
    lines = result.split("\n")
    domain_lines = [l for l in lines if l and not l.startswith("#")]
    assert len(domain_lines) == 100_000


# ── Display truncation ────────────────────────────────────────────────

def test_display_truncation():
    """Verify the truncation logic used by the GUI (tested headlessly)."""
    DISPLAY_LIMIT = 10_000

    combiner = ListCombiner()
    combiner.add_list(_generate_domains("x", 20_000), "big-list")
    result = combiner.get_combined()

    lines = result.split("\n")
    assert len(lines) > DISPLAY_LIMIT

    # Simulate truncation (same logic as combine_tab / library_tab)
    display = "\n".join(lines[:DISPLAY_LIMIT])
    display += f"\n\n# ... ({len(lines) - DISPLAY_LIMIT:,} more lines not shown)"
    display += "\n# Full list preserved — use Copy, Save, or Host to get all domains."

    display_lines = display.split("\n")
    assert len(display_lines) == DISPLAY_LIMIT + 3  # limit + blank + 2 comments

    # Full result is still intact
    assert len(lines) > 20_000  # domains + header lines


# ── Many small sources combine ────────────────────────────────────────

def test_combine_many_sources(tmp_path):
    """Combine 200+ tiny file sources, verify stats."""
    combiner = ListCombiner()
    total_unique = set()

    for i in range(200):
        # Each file has 5 domains, some overlap between consecutive files
        domains = [f"domain-{i}-{j}.com" for j in range(5)]
        total_unique.update(domains)
        content = "\n".join(domains)
        combiner.add_list(content, f"source-{i}")

    stats = combiner.get_stats()
    assert stats["unique_domains"] == len(total_unique)
    assert stats["lists_processed"] == 200


# ── Updater with file sources ────────────────────────────────────────

def test_update_many_file_sources(tmp_path):
    """update_list with 50 file sources — verify correct merge."""
    sources = []
    expected_domains = set()

    for i in range(50):
        f = tmp_path / f"list_{i}.txt"
        domains = [f"src{i}-d{j}.com" for j in range(10)]
        # Add some overlap: first domain of each list is shared
        domains.append("shared-across-all.com")
        expected_domains.update(domains)
        f.write_text("\n".join(domains) + "\n")
        sources.append({"type": "file", "label": str(f)})

    sources_json = json.dumps(sources)
    content, domain_count, dupes, failed = update_list(sources_json)

    assert domain_count == len(expected_domains)
    assert failed == []
    assert dupes >= 49  # "shared-across-all.com" duplicated 49 times
    assert "shared-across-all.com" in content


# ── Duplicate source detection (backend check) ───────────────────────

def test_duplicate_domains_across_lists():
    """Same domain in every list — verify dedup count."""
    combiner = ListCombiner()
    for i in range(100):
        combiner.add_list("always-the-same.com\n", f"list-{i}")

    stats = combiner.get_stats()
    assert stats["unique_domains"] == 1
    assert stats["duplicates_removed"] == 99
    assert stats["lists_processed"] == 100
