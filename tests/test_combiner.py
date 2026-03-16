"""Tests for ListCombiner."""

import pytest
from piholecombinelist.combiner import ListCombiner


@pytest.fixture
def combiner():
    return ListCombiner()


def test_add_plain_list(combiner):
    added = combiner.add_list("example.com\nads.com\n")
    assert added == 2
    assert combiner.get_stats()["unique_domains"] == 2


def test_add_ip_prefixed_list(combiner):
    content = "0.0.0.0 tracker.com\n127.0.0.1 spyware.net\n"
    added = combiner.add_list(content)
    assert added == 2


def test_deduplication_across_lists(combiner):
    combiner.add_list("example.com\nads.com\n")
    added = combiner.add_list("ads.com\nnewsite.com\n")
    assert added == 1  # only newsite.com is new
    stats = combiner.get_stats()
    assert stats["unique_domains"] == 3
    assert stats["duplicates_removed"] == 1


def test_deduplication_within_list(combiner):
    combiner.add_list("example.com\nexample.com\nexample.com\n")
    stats = combiner.get_stats()
    assert stats["unique_domains"] == 1
    assert stats["duplicates_removed"] == 2


def test_comments_skipped(combiner):
    content = "# comment\n! adblock\nexample.com\n"
    combiner.add_list(content)
    assert combiner.get_stats()["unique_domains"] == 1


def test_get_combined_sorted(combiner):
    combiner.add_list("zebra.com\napple.com\nmango.com\n")
    output = combiner.get_combined(include_header=False)
    lines = output.strip().splitlines()
    assert lines == sorted(lines)


def test_get_combined_header(combiner):
    combiner.add_list("example.com\n")
    output = combiner.get_combined(include_header=True)
    assert output.startswith("# Pi-hole Combined Blocklist")
    assert "Unique domains: 1" in output


def test_get_combined_allowlist_type(combiner):
    combiner.add_list("example.com\n")
    output = combiner.get_combined(list_type="Allowlist")
    assert output.startswith("# Pi-hole Combined Allowlist")


def test_get_combined_credits(combiner):
    combiner.add_list("example.com\n")
    output = combiner.get_combined(credits=["StevenBlack", "hagezi"])
    assert "# Credits: StevenBlack, hagezi" in output


def test_get_combined_no_credits_when_none(combiner):
    combiner.add_list("example.com\n")
    output = combiner.get_combined(credits=None)
    assert "Credits" not in output


def test_get_combined_no_header(combiner):
    combiner.add_list("example.com\n")
    output = combiner.get_combined(include_header=False)
    assert not output.startswith("#")
    assert "example.com" in output


def test_save_writes_file(combiner, tmp_path):
    combiner.add_list("example.com\nads.com\n")
    out = tmp_path / "out.txt"
    combiner.save(str(out))
    text = out.read_text()
    assert "example.com" in text
    assert "ads.com" in text


def test_clear_resets_state(combiner):
    combiner.add_list("example.com\n")
    combiner.clear()
    stats = combiner.get_stats()
    assert stats["unique_domains"] == 0
    assert stats["duplicates_removed"] == 0
    assert stats["lists_processed"] == 0
