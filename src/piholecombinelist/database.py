"""SQLite-backed library for storing and organizing combined blocklists."""
# v1.1.0

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional


class Database:
    """Manages the local SQLite library of saved blocklists organized in folders."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            data_dir = Path.home() / ".db"
            data_dir.mkdir(exist_ok=True)
            db_path = data_dir / "piholecombinelist.db"
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS folders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lists (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT NOT NULL,
                folder_id         INTEGER REFERENCES folders(id) ON DELETE SET NULL,
                content           TEXT NOT NULL,
                domain_count      INTEGER NOT NULL DEFAULT 0,
                duplicates_removed INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self._conn.commit()
        # Migrate existing DBs: add sources column if missing
        try:
            self._conn.execute("ALTER TABLE lists ADD COLUMN sources TEXT DEFAULT ''")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def create_folder(self, name: str) -> int:
        """Create a new folder. Returns its id."""
        cur = self._conn.execute(
            "INSERT INTO folders (name, created_at) VALUES (?, ?)",
            (name, _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    def rename_folder(self, folder_id: int, name: str) -> None:
        self._conn.execute(
            "UPDATE folders SET name = ? WHERE id = ?", (name, folder_id)
        )
        self._conn.commit()

    def delete_folder(self, folder_id: int) -> None:
        """Delete a folder. Lists inside it are moved to root (folder_id = NULL)."""
        self._conn.execute(
            "UPDATE lists SET folder_id = NULL WHERE folder_id = ?", (folder_id,)
        )
        self._conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        self._conn.commit()

    def get_folders(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT id, name, created_at FROM folders ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Lists
    # ------------------------------------------------------------------

    def save_list(
        self,
        name: str,
        content: str,
        domain_count: int,
        duplicates_removed: int,
        folder_id: Optional[int] = None,
        sources: str = "",
    ) -> int:
        """Save a combined blocklist. Returns its id."""
        cur = self._conn.execute(
            """INSERT INTO lists
               (name, folder_id, content, domain_count, duplicates_removed, created_at, sources)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, folder_id, content, domain_count, duplicates_removed, _now(), sources),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_lists(self, folder_id: Optional[int] = None) -> List[dict]:
        """
        Get lists in a folder. Pass None for root (lists with no folder).
        Pass a folder id for a specific folder.
        """
        rows = self._conn.execute(
            """SELECT id, name, folder_id, domain_count, duplicates_removed, created_at
               FROM lists WHERE folder_id IS ? ORDER BY created_at DESC""",
            (folder_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_lists(self) -> List[dict]:
        """Return every list regardless of folder."""
        rows = self._conn.execute(
            """SELECT id, name, folder_id, domain_count, duplicates_removed, created_at
               FROM lists ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_list(self, list_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM lists WHERE id = ?", (list_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_list(self, list_id: int) -> None:
        self._conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
        self._conn.commit()

    def move_list(self, list_id: int, folder_id: Optional[int]) -> None:
        """Move a list to a folder (or to root if folder_id is None)."""
        self._conn.execute(
            "UPDATE lists SET folder_id = ? WHERE id = ?", (folder_id, list_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        """Return the stored value for key, or default if not set."""
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Persist key=value, replacing any existing entry."""
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
