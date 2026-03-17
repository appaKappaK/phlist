"""Tests for Database (SQLite library)."""

import pytest
from piholecombinelist.database import Database


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
