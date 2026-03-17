"""Unit tests for Deduplicator."""

import pytest
from piholecombinelist.deduplicator import Deduplicator


def test_add_new_domain():
    d = Deduplicator()
    assert d.add("example.com") is True
    assert d.count == 1
    assert d.duplicates == 0


def test_add_duplicate():
    d = Deduplicator()
    d.add("example.com")
    assert d.add("example.com") is False
    assert d.count == 1
    assert d.duplicates == 1


def test_add_multiple_duplicates():
    d = Deduplicator()
    d.add("a.com")
    d.add("a.com")
    d.add("a.com")
    assert d.count == 1
    assert d.duplicates == 2


def test_domains_returns_copy():
    d = Deduplicator()
    d.add("a.com")
    snapshot = d.domains
    snapshot.add("evil.com")  # mutating the returned set should not affect internal state
    assert "evil.com" not in d.domains
    assert d.count == 1


def test_clear():
    d = Deduplicator()
    d.add("a.com")
    d.add("b.com")
    d.add("a.com")
    d.clear()
    assert d.count == 0
    assert d.duplicates == 0
    assert d.domains == set()


def test_domains_content():
    d = Deduplicator()
    d.add("alpha.com")
    d.add("beta.com")
    d.add("alpha.com")
    assert d.domains == {"alpha.com", "beta.com"}


def test_count_tracks_unique():
    d = Deduplicator()
    for i in range(100):
        d.add(f"domain{i}.com")
    for i in range(50):
        d.add(f"domain{i}.com")  # duplicates
    assert d.count == 100
    assert d.duplicates == 50


def test_add_after_clear():
    d = Deduplicator()
    d.add("a.com")
    d.clear()
    assert d.add("a.com") is True
    assert d.count == 1
    assert d.duplicates == 0
