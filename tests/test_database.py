"""Tests for Database (SQLite library)."""

import os
import shutil
import sqlite3
import stat

import pytest
from phlist.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=tmp_path / "test.db")
    yield d
    d.close()


def test_create_and_get_folder(db):
    fid = db.create_folder("Ads")
    folders = db.get_folders()
    assert len(folders) == 1
    assert folders[0]["name"] == "Ads"
    assert folders[0]["id"] == fid


def test_rename_folder(db):
    fid = db.create_folder("Old Name")
    db.rename_folder(fid, "New Name")
    assert db.get_folders()[0]["name"] == "New Name"


def test_save_and_get_list_in_folder(db):
    fid = db.create_folder("Trackers")
    lid = db.save_list("my-list", "example.com\n", 1, 0, folder_id=fid)
    lists = db.get_lists(folder_id=fid)
    assert len(lists) == 1
    assert lists[0]["name"] == "my-list"
    assert lists[0]["id"] == lid


def test_save_list_root(db):
    db.save_list("root-list", "ads.com\n", 1, 0, folder_id=None)
    lists = db.get_lists(folder_id=None)
    assert len(lists) == 1
    assert lists[0]["name"] == "root-list"


def test_get_list_content(db):
    lid = db.save_list("test", "example.com\nads.com\n", 2, 1)
    row = db.get_list(lid)
    assert row["content"] == "example.com\nads.com\n"
    assert row["domain_count"] == 2
    assert row["duplicates_removed"] == 1


def test_delete_list(db):
    lid = db.save_list("to-delete", "x.com\n", 1, 0)
    db.delete_list(lid)
    assert db.get_list(lid) is None


def test_move_list_to_folder(db):
    fid = db.create_folder("Malware")
    lid = db.save_list("my-list", "x.com\n", 1, 0, folder_id=None)
    assert db.get_lists(folder_id=None)[0]["id"] == lid
    db.move_list(lid, fid)
    assert db.get_lists(folder_id=None) == []
    assert db.get_lists(folder_id=fid)[0]["id"] == lid


def test_delete_folder_moves_lists_to_root(db):
    fid = db.create_folder("Temp")
    lid = db.save_list("orphan", "x.com\n", 1, 0, folder_id=fid)
    db.delete_folder(fid)
    root_lists = db.get_lists(folder_id=None)
    assert any(l["id"] == lid for l in root_lists)
    assert db.get_folders() == []


def test_get_setting_default(db):
    assert db.get_setting("port", "8765") == "8765"
    assert db.get_setting("missing") == ""


def test_set_and_get_setting(db):
    db.set_setting("port", "9000")
    assert db.get_setting("port", "8765") == "9000"
    db.set_setting("port", "1234")
    assert db.get_setting("port") == "1234"


def test_save_list_with_sources(db):
    sources = '[{"type": "url", "label": "https://example.com/list.txt"}]'
    lid = db.save_list("with-sources", "x.com\n", 1, 0, sources=sources)
    row = db.get_list(lid)
    assert row["sources"] == sources


def test_save_list_no_sources(db):
    lid = db.save_list("no-sources", "x.com\n", 1, 0)
    row = db.get_list(lid)
    assert row["sources"] == ""


def test_update_list_overwrites_content(db):
    lid = db.save_list("original", "old.com\n", 1, 0)
    db.update_list(lid, "new.com\nanother.com\n", 2, 5)
    row = db.get_list(lid)
    assert row["content"] == "new.com\nanother.com\n"
    assert row["domain_count"] == 2
    assert row["duplicates_removed"] == 5


def test_update_list_sets_updated_at(db):
    lid = db.save_list("ts-test", "x.com\n", 1, 0)
    row_before = db.get_list(lid)
    assert row_before["updated_at"] == ""
    db.update_list(lid, "y.com\n", 1, 0)
    row_after = db.get_list(lid)
    assert row_after["updated_at"] != ""


def test_get_all_lists_includes_sources(db):
    sources = '[{"type": "url", "label": "https://example.com/list.txt"}]'
    db.save_list("a", "x.com\n", 1, 0, sources=sources)
    db.save_list("b", "y.com\n", 1, 0)
    all_lists = db.get_all_lists()
    assert len(all_lists) == 2
    sources_by_name = {r["name"]: r["sources"] for r in all_lists}
    assert sources_by_name["a"] == sources
    assert sources_by_name["b"] == ""


def test_get_library_stats_empty(db):
    stats = db.get_library_stats()
    assert stats["folder_count"] == 0
    assert stats["list_count"] == 0
    assert stats["total_domains"] == 0
    assert stats["db_bytes"] > 0


def test_get_library_stats_with_data(db):
    fid = db.create_folder("test-folder")
    db.save_list("a", "x.com\ny.com\n", 2, 1, folder_id=fid)
    db.save_list("b", "z.com\n", 1, 0)
    stats = db.get_library_stats()
    assert stats["folder_count"] == 1
    assert stats["list_count"] == 2
    assert stats["total_domains"] == 3
    assert stats["db_bytes"] > 0


# ── Export / Import (mirrors what SettingsTab does) ───────────────────


def test_export_db_produces_valid_copy(db, tmp_path):
    """shutil.copy2 of _path produces a readable database with the same data."""
    db.create_folder("Ads")
    db.save_list("my-list", "example.com\n", 1, 0)

    backup_path = tmp_path / "backup.db"
    shutil.copy2(db._path, backup_path)

    restored = Database(db_path=backup_path)
    try:
        assert len(restored.get_folders()) == 1
        assert restored.get_folders()[0]["name"] == "Ads"
        assert len(restored.get_all_lists()) == 1
        assert restored.get_all_lists()[0]["name"] == "my-list"
    finally:
        restored.close()


def test_import_db_replaces_live_connection(db, tmp_path):
    """sqlite3 backup() restores a backup into the live connection."""
    # Set up the backup source
    src_db = Database(db_path=tmp_path / "source.db")
    src_db.create_folder("Source Folder")
    src_db.save_list("source-list", "ads.com\n", 1, 0)
    src_db.close()

    # Populate the live db with different data
    db.create_folder("Original Folder")
    db.save_list("original-list", "tracker.com\n", 1, 0)

    # Perform import: same code path as SettingsTab._import_db
    src_conn = sqlite3.connect(str(tmp_path / "source.db"))
    src_conn.backup(db._conn)
    src_conn.close()

    # Live db should now reflect the backup
    folders = db.get_folders()
    lists = db.get_all_lists()
    assert len(folders) == 1
    assert folders[0]["name"] == "Source Folder"
    assert len(lists) == 1
    assert lists[0]["name"] == "source-list"


def test_rename_list(db):
    lid = db.save_list("original", "x.com\n", 1, 0)
    db.rename_list(lid, "renamed")
    assert db.get_list(lid)["name"] == "renamed"


def test_get_lists_sort_order(db):
    """get_lists() returns lists newest-first (ORDER BY created_at DESC)."""
    from unittest.mock import patch
    with patch("phlist.database._now", side_effect=[
        "2024-01-01 00:00:01",
        "2024-01-01 00:00:02",
        "2024-01-01 00:00:03",
    ]):
        db.save_list("first", "a.com\n", 1, 0)
        db.save_list("second", "b.com\n", 1, 0)
        db.save_list("third", "c.com\n", 1, 0)
    names = [r["name"] for r in db.get_lists(folder_id=None)]
    assert names == ["third", "second", "first"]


def test_get_folders_sort_order(db):
    """get_folders() returns folders alphabetically (ORDER BY name)."""
    db.create_folder("Zebra")
    db.create_folder("Alpha")
    db.create_folder("Middle")
    names = [f["name"] for f in db.get_folders()]
    assert names == ["Alpha", "Middle", "Zebra"]


def test_save_list_strips_bidi_unicode(db):
    """U+202E (RLO) and similar chars are stripped from list names on save."""
    name_with_rlo = "My List\u202e"
    lid = db.save_list(name_with_rlo, "x.com\n", 1, 0)
    assert db.get_list(lid)["name"] == "My List"


def test_create_folder_strips_zero_width(db):
    """U+200B (zero-width space) is stripped from folder names on save."""
    name_with_zwsp = "Folder\u200bName"
    db.create_folder(name_with_zwsp)
    assert db.get_folders()[0]["name"] == "FolderName"


def test_import_db_overwrites_all_existing_data(db, tmp_path):
    """Import leaves no trace of the pre-import data."""
    db.create_folder("Old")
    db.save_list("old-list", "x.com\n", 1, 0)

    empty_db = Database(db_path=tmp_path / "empty.db")
    empty_db.close()

    src_conn = sqlite3.connect(str(tmp_path / "empty.db"))
    src_conn.backup(db._conn)
    src_conn.close()

    assert db.get_folders() == []
    assert db.get_all_lists() == []


def test_db_file_permissions(tmp_path):
    """Database file must be owner read/write only (0o600)."""
    db_path = tmp_path / "secure.db"
    d = Database(db_path=db_path)
    d.close()
    mode = os.stat(db_path).st_mode & 0o777
    assert mode == 0o600
