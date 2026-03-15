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
