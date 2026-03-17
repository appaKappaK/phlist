#!/usr/bin/env python3
"""Probe: Database save / get / update / delete operations.

Run:
    python scripts/probe_db.py

Uses a temporary database — never touches the real one.
"""

import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
from piholecombinelist.database import Database

# --- EDIT BELOW ---

LIST_NAME = "probe-list"
LIST_CONTENT = "example.com\nads.com\ntracker.net\n"
DOMAIN_COUNT = 3
DUPLICATES_REMOVED = 1
FOLDER_NAME = "Test Folder"

# --- END EDIT ---

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=Path(tmpdir) / "probe.db")

        print("=== Folder ops ===")
        fid = db.create_folder(FOLDER_NAME)
        print(f"  Created folder '{FOLDER_NAME}' (id={fid})")
        print(f"  Folders: {db.get_folders()}")

        print("\n=== Save list ===")
        lid = db.save_list(LIST_NAME, LIST_CONTENT, DOMAIN_COUNT, DUPLICATES_REMOVED, folder_id=fid)
        print(f"  Saved '{LIST_NAME}' (id={lid})")
        row = db.get_list(lid)
        print(f"  Retrieved: name={row['name']}, domains={row['domain_count']}, "
              f"dupes={row['duplicates_removed']}")

        print("\n=== Update list ===")
        db.update_list(lid, "new.com\n", 1, 0)
        row = db.get_list(lid)
        print(f"  After update: content={row['content']!r}, domains={row['domain_count']}, "
              f"updated_at={row['updated_at']}")

        print("\n=== Move list to root ===")
        db.move_list(lid, None)
        root_lists = db.get_lists(folder_id=None)
        print(f"  Root lists: {[r['name'] for r in root_lists]}")

        print("\n=== Delete list ===")
        db.delete_list(lid)
        print(f"  Deleted. get_list returns: {db.get_list(lid)}")

        print("\n=== Settings ===")
        db.set_setting("port", "9999")
        print(f"  port = {db.get_setting('port')}")
        print(f"  missing = {db.get_setting('missing', 'default_val')!r}")

        db.close()
        print("\nDone.")
