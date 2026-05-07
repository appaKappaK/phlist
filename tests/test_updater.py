"""Tests for the updater module (re-fetch + re-combine pipeline)."""

import json
from unittest.mock import patch

import pytest

from phlist.updater import has_fetchable_sources, update_list


# ── has_fetchable_sources ────────────────────────────────────────


def test_has_fetchable_sources_with_urls():
    sources = json.dumps([{"type": "url", "label": "https://example.com/list.txt"}])
    assert has_fetchable_sources(sources) is True


def test_has_fetchable_sources_with_files():
    sources = json.dumps([{"type": "file", "label": "/tmp/list.txt"}])
    assert has_fetchable_sources(sources) is True


def test_has_fetchable_sources_empty_string():
    assert has_fetchable_sources("") is False


def test_has_fetchable_sources_none():
    assert has_fetchable_sources(None) is False


def test_has_fetchable_sources_bad_json():
    assert has_fetchable_sources("not json at all") is False


def test_has_fetchable_sources_empty_array():
    assert has_fetchable_sources("[]") is False


def test_has_fetchable_sources_unknown_type():
    sources = json.dumps([{"type": "paste", "label": "pasted text"}])
    assert has_fetchable_sources(sources) is False


# ── update_list with local files ─────────────────────────────────


def test_update_list_with_file_sources(tmp_path):
    list_file = tmp_path / "hosts.txt"
    list_file.write_text("ads.example.com\ntracker.example.com\nads.example.com\n")
    sources = json.dumps([{"type": "file", "label": str(list_file)}])

    content, domain_count, duplicates_removed, failed = update_list(sources)

    assert domain_count == 2
    assert duplicates_removed == 1
    assert failed == []
    assert "ads.example.com" in content
    assert "tracker.example.com" in content


def test_update_list_multiple_file_sources(tmp_path):
    f1 = tmp_path / "list1.txt"
    f1.write_text("a.com\nb.com\n")
    f2 = tmp_path / "list2.txt"
    f2.write_text("b.com\nc.com\n")
    sources = json.dumps([
        {"type": "file", "label": str(f1)},
        {"type": "file", "label": str(f2)},
    ])

    content, domain_count, duplicates_removed, failed = update_list(sources)

    assert domain_count == 3
    assert duplicates_removed == 1
    assert failed == []


def test_update_list_all_sources_fail():
    sources = json.dumps([
        {"type": "file", "label": "/nonexistent/path/list.txt"},
        {"type": "file", "label": "/also/missing.txt"},
    ])

    content, domain_count, duplicates_removed, failed = update_list(sources)

    assert content == ""
    assert domain_count == 0
    assert len(failed) == 2


def test_update_list_partial_failure(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("valid.com\n")
    sources = json.dumps([
        {"type": "file", "label": str(good)},
        {"type": "file", "label": "/nonexistent.txt"},
    ])

    content, domain_count, duplicates_removed, failed = update_list(sources)

    assert domain_count == 1
    assert len(failed) == 1
    assert "valid.com" in content


def test_update_list_allowlist_header(tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text("safe.com\n")
    sources = json.dumps([{"type": "file", "label": str(f)}])

    content, _, _, _ = update_list(sources, list_type="Allowlist")

    assert "Allowlist" in content


def test_update_list_passes_custom_max_bytes(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text("safe.com\n")
    sources = json.dumps([{"type": "file", "label": str(f)}])

    with patch("phlist.updater.ListFetcher") as fetcher_cls:
        fetcher = fetcher_cls.return_value
        fetcher.fetch.return_value = "safe.com\n"
        content, domain_count, duplicates_removed, failed = update_list(
            sources,
            max_bytes=1234,
        )

    fetcher_cls.assert_called_once_with(timeout=30, max_bytes=1234)
    assert content
    assert domain_count == 1
    assert duplicates_removed == 0
    assert failed == []


# ── update_list with bad input ───────────────────────────────────


def test_update_list_empty_json():
    content, domain_count, _, failed = update_list("")

    assert content == ""
    assert domain_count == 0
    assert len(failed) == 1


def test_update_list_corrupt_json():
    content, domain_count, _, failed = update_list("{not valid")

    assert content == ""
    assert domain_count == 0
    assert len(failed) == 1


def test_has_fetchable_sources_missing_label():
    """Source with 'type' but no 'label' — has_fetchable_sources checks type only."""
    sources = json.dumps([{"type": "url"}])
    assert has_fetchable_sources(sources) is True
