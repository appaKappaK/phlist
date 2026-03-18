"""Settings tab: two-column card layout with appearance, stats, log, and more."""

import shutil
import sqlite3
import subprocess
import threading
from collections import deque
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from ..database import Database, _DATA_DIR
from ..remote import check_connection as _check_connection
from ..server import ListServer
from .tooltip import Tooltip


def _format_bytes(n: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _card(parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
    """Create a labelled card frame with header and optional subtitle inside."""
    card = ctk.CTkFrame(parent, border_width=1, border_color=("gray75", "gray30"))
    card.pack(fill="x", padx=12, pady=(0, 10))
    ctk.CTkLabel(
        card, text=title, font=ctk.CTkFont(size=13, weight="bold"),
    ).pack(anchor="w", padx=12, pady=(12, 0))
    if subtitle:
        ctk.CTkLabel(
            card, text=subtitle, font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        ).pack(anchor="w", padx=12, pady=(2, 0))
    return card


class SettingsTab(ctk.CTkFrame):
    """The Settings tab: server port, appearance, stats, log, and more."""

    def __init__(self, parent, server: ListServer,
                 db: Database,
                 refresh_library_cb: Optional[Callable[[], None]] = None,
                 refresh_push_btn_cb: Optional[Callable[[], None]] = None,
                 notify_server_reachable_cb: Optional[Callable[[bool], None]] = None) -> None:
        super().__init__(parent, fg_color="transparent")
        self._server = server
        self._db = db
        self._refresh_library_cb = refresh_library_cb
        self._refresh_push_btn_cb = refresh_push_btn_cb
        self._notify_server_reachable_cb = notify_server_reachable_cb
        self._build_ui()

    def _build_ui(self) -> None:
        # Scrollable wrapper so nothing clips on small windows
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        scroll.columnconfigure(0, weight=1)
        scroll.columnconfigure(1, weight=1)

        # ── Left column ────────────────────────────────────────────
        left = ctk.CTkFrame(scroll, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=0)

        # ── SERVER ─────────────────────────────────────────────────
        card = _card(left, "SERVER", "Built-in HTTP host for Pi-hole gravity")
        port_row = ctk.CTkFrame(card, fg_color="transparent")
        port_row.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(port_row, text="Listen port:").pack(side="left", padx=(0, 8))
        self._port_entry = ctk.CTkEntry(port_row, width=80)
        self._port_entry.insert(0, str(self._server._port))
        self._port_entry.pack(side="left", padx=(0, 8))
        Tooltip(self._port_entry, "The port the HTTP server listens on. Default: 8765.")
        apply_btn = ctk.CTkButton(port_row, text="Apply", width=70, command=self._apply_port)
        apply_btn.pack(side="left")
        Tooltip(apply_btn, "Save the port. Takes effect the next time you host a list.")

        # ── DESKTOP INTEGRATION ────────────────────────────────────
        card = _card(left, "DESKTOP", "Linux app launcher integration")
        desktop_row = ctk.CTkFrame(card, fg_color="transparent")
        desktop_row.pack(fill="x", padx=12, pady=12)
        desktop_btn = ctk.CTkButton(
            desktop_row, text="Install Desktop Shortcut", width=190,
            command=self._install_desktop,
        )
        desktop_btn.pack(side="left", padx=(0, 8))
        Tooltip(desktop_btn, "Create a .desktop launcher entry so the app appears in your GNOME/KDE app menu.")
        self._desktop_status = ctk.CTkLabel(desktop_row, text="", text_color=("gray15", "gray60"))
        self._desktop_status.pack(side="left")

        # ── LOG VIEWER ─────────────────────────────────────────────
        card = _card(left, "LOG", "Recent app activity")
        self._log_box = ctk.CTkTextbox(card, height=120, wrap="none", state="disabled",
                                        font=ctk.CTkFont(size=11),
                                        text_color=("gray10", "gray90"))
        self._log_box.pack(fill="x", padx=12, pady=(8, 6))
        log_btn_row = ctk.CTkFrame(card, fg_color="transparent")
        log_btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(log_btn_row, text="Refresh", width=80, command=self._refresh_log).pack(side="left", padx=(0, 8))
        ctk.CTkButton(log_btn_row, text="Open Log File", width=110, command=self._open_log).pack(side="left")
        self._refresh_log()

        # ── Right column ───────────────────────────────────────────
        right = ctk.CTkFrame(scroll, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=0)

        # ── REMOTE SERVER ──────────────────────────────────────────
        card = _card(right, "REMOTE SERVER", "Push lists to a phlist-server instance")

        url_row = ctk.CTkFrame(card, fg_color="transparent")
        url_row.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(url_row, text="Server URL:", width=80, anchor="w").pack(side="left", padx=(0, 6))
        self._remote_url_entry = ctk.CTkEntry(url_row, width=200,
                                               placeholder_text="http://device.ts.net:8765")
        saved_url = self._db.get_setting("remote_server_url", "")
        if saved_url:
            self._remote_url_entry.insert(0, saved_url)
        self._remote_url_entry.pack(side="left")
        Tooltip(self._remote_url_entry, "Base URL of your phlist-server (LAN IP or Tailscale hostname).")

        key_row = ctk.CTkFrame(card, fg_color="transparent")
        key_row.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(key_row, text="API key:", width=80, anchor="w").pack(side="left", padx=(0, 6))
        self._remote_key_entry = ctk.CTkEntry(key_row, width=200, show="*")
        saved_key = self._db.get_setting("remote_server_key", "")
        if saved_key:
            self._remote_key_entry.insert(0, saved_key)
        self._remote_key_entry.pack(side="left")
        Tooltip(self._remote_key_entry, "Bearer token the server requires for PUT requests.")

        save_row = ctk.CTkFrame(card, fg_color="transparent")
        save_row.pack(fill="x", padx=12, pady=(6, 0))
        save_remote_btn = ctk.CTkButton(save_row, text="Save", width=70,
                                         command=self._save_remote_settings)
        save_remote_btn.pack(side="left", padx=(0, 8))

        self._remote_test_status = ctk.CTkLabel(save_row, text="",
                                                  font=ctk.CTkFont(size=11),
                                                  text_color=("gray40", "gray60"))
        self._remote_test_status.pack(side="left")

        test_row = ctk.CTkFrame(card, fg_color="transparent")
        test_row.pack(fill="x", padx=12, pady=(4, 0))
        test_btn = ctk.CTkButton(test_row, text="Test Connection", width=130,
                                  command=self._test_remote_connection)
        test_btn.pack(side="left", padx=(0, 8))
        self._remote_conn_status = ctk.CTkLabel(test_row, text="",
                                                 font=ctk.CTkFont(size=11),
                                                 text_color=("gray40", "gray60"))
        self._remote_conn_status.pack(side="left")

        autopush_row = ctk.CTkFrame(card, fg_color="transparent")
        autopush_row.pack(fill="x", padx=12, pady=(6, 10))
        saved_autopush = self._db.get_setting("remote_auto_push", "0")
        self._autopush_var = ctk.StringVar(value="1" if saved_autopush == "1" else "0")
        autopush_switch = ctk.CTkSwitch(
            autopush_row, text="Auto-push on Save to Library",
            variable=self._autopush_var, onvalue="1", offvalue="0",
            command=self._on_autopush_toggle,
        )
        autopush_switch.pack(side="left")
        Tooltip(autopush_switch,
                "When enabled, saving a combined list to the library also pushes it to the remote server.")

        # ── LIBRARY STATS ──────────────────────────────────────────
        card = _card(right, "LIBRARY", "Saved lists and folders at a glance")
        self._stats_labels: dict[str, ctk.CTkLabel] = {}
        stats_grid = ctk.CTkFrame(card, fg_color="transparent")
        stats_grid.pack(fill="x", padx=12, pady=(6, 4))
        for col in range(2):
            stats_grid.columnconfigure(col, weight=1)
        positions = [("folders", 0, 0), ("lists", 0, 1), ("domains", 1, 0), ("db_size", 1, 1)]
        for key, row, col in positions:
            lbl = ctk.CTkLabel(stats_grid, text="", anchor="w")
            lbl.grid(row=row, column=col, sticky="w", pady=1)
            self._stats_labels[key] = lbl
        refresh_stats_btn = ctk.CTkButton(card, text="Refresh Stats", width=110, command=self._refresh_stats)
        refresh_stats_btn.pack(anchor="w", padx=12, pady=(4, 10))
        Tooltip(refresh_stats_btn, "Update the library stats shown here.")
        self._refresh_stats()

        # ── DATA (full width, compact single row) ─────────────────
        data_card = ctk.CTkFrame(scroll, border_width=1, border_color=("gray75", "gray30"))
        data_card.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        data_row = ctk.CTkFrame(data_card, fg_color="transparent")
        data_row.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(
            data_row, text="DATA", font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 16))
        export_btn = ctk.CTkButton(data_row, text="Export DB", width=90, command=self._export_db)
        export_btn.pack(side="left", padx=(0, 8))
        Tooltip(export_btn, "Save a backup copy of your entire library database (phlist.db).")
        import_btn = ctk.CTkButton(data_row, text="Import DB", width=90, command=self._import_db)
        import_btn.pack(side="left", padx=(0, 8))
        Tooltip(import_btn, "Restore the library from a previously exported backup. Replaces all current data.")
        folder_btn = ctk.CTkButton(data_row, text="Open Folder", width=100, command=self._open_data_folder)
        folder_btn.pack(side="left")
        Tooltip(folder_btn, f"Open {_DATA_DIR} in the file manager.")

        # Auto-hide scrollbar when content fits
        def _update_scroll_vis(canvas=scroll._parent_canvas, sb=scroll._scrollbar):
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                sb.grid()
            else:
                sb.grid_remove()
        scroll._parent_canvas.bind("<Configure>", lambda _: self.after(0, _update_scroll_vis))

    # ── Actions ─────────────────────────────────────────────────────

    def _apply_port(self) -> None:
        if self._server.is_running:
            messagebox.showwarning(
                "Server is running", "Stop the server before changing the port."
            )
            self._port_entry.delete(0, "end")
            self._port_entry.insert(0, str(self._server._port))
            return
        raw = self._port_entry.get().strip()
        try:
            port = int(raw)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Enter a number between 1 and 65535.")
            self._port_entry.delete(0, "end")
            self._port_entry.insert(0, str(self._server._port))
            return
        self._server._port = port
        self._db.set_setting("port", str(port))

    def _install_desktop(self) -> None:
        from .._install_desktop import install as _install
        ok, msg = _install()
        if ok:
            self._desktop_status.configure(text=msg)
            messagebox.showinfo("Shortcut installed", msg)
        else:
            messagebox.showerror("Install failed", msg)

    def _refresh_stats(self) -> None:
        stats = self._db.get_library_stats()
        self._stats_labels["folders"].configure(text=f"Folders: {stats['folder_count']}")
        self._stats_labels["lists"].configure(text=f"Lists: {stats['list_count']}")
        self._stats_labels["domains"].configure(text=f"Total domains: {stats['total_domains']:,}")
        self._stats_labels["db_size"].configure(text=f"Database size: {_format_bytes(stats['db_bytes'])}")

    def _refresh_log(self) -> None:
        log_path = _DATA_DIR / "phlist.log"
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                lines = deque(f, maxlen=15)
            # Newest entry first so it's visible without scrolling
            text = "".join(reversed(lines)).rstrip("\n")
        except FileNotFoundError:
            text = "(no log file found)"
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.insert("1.0", text)
        self._log_box.configure(state="disabled")

    def _open_log(self) -> None:
        log_path = _DATA_DIR / "phlist.log"
        if not log_path.exists():
            messagebox.showinfo("No log", "Log file does not exist yet.")
            return
        try:
            subprocess.Popen(["xdg-open", str(log_path)])
        except Exception as exc:
            messagebox.showerror("Could not open", f"Failed to open log file:\n{exc}")

    def _export_db(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export Library Database",
            initialfile="phlist-backup.db",
            defaultextension=".db",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            shutil.copy2(self._db._path, path)
            messagebox.showinfo("Exported", f"Library backed up to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not export database:\n{exc}")

    def _import_db(self) -> None:
        if not messagebox.askyesno(
            "Import Library",
            "This will REPLACE your entire library with the backup.\n"
            "All current lists and folders will be lost.\n\nContinue?",
            icon="warning",
        ):
            return
        path = filedialog.askopenfilename(
            title="Import Library Database",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            src = sqlite3.connect(path)
            src.backup(self._db._conn)
            src.close()
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not import database:\n{exc}")
            return
        if self._refresh_library_cb:
            self._refresh_library_cb()
        messagebox.showinfo("Imported", "Library imported successfully.")

    def _open_data_folder(self) -> None:
        try:
            subprocess.Popen(["xdg-open", str(_DATA_DIR)])
        except Exception as exc:
            messagebox.showerror("Could not open", f"Failed to open data folder:\n{exc}")

    def _save_remote_settings(self) -> None:
        url = self._remote_url_entry.get().strip().rstrip("/")
        key = self._remote_key_entry.get().strip()
        self._db.set_setting("remote_server_url", url)
        self._db.set_setting("remote_server_key", key)
        self._remote_test_status.configure(text="Saved.", text_color=("gray40", "gray60"))
        # Changing credentials invalidates the last connection test
        if self._notify_server_reachable_cb:
            self._notify_server_reachable_cb(False)
        if self._refresh_push_btn_cb:
            self._refresh_push_btn_cb()

    def _test_remote_connection(self) -> None:
        url = self._remote_url_entry.get().strip().rstrip("/")
        key = self._remote_key_entry.get().strip()
        if not url:
            self._remote_conn_status.configure(text="Enter a server URL first.",
                                                text_color=("#C0392B", "#E74C3C"))
            return
        self._remote_conn_status.configure(text="Testing…", text_color=("gray40", "gray60"))
        self.update_idletasks()

        def _worker():
            ok, msg = _check_connection(url, key)
            color = ("#27AE60", "#2ECC71") if ok else ("#C0392B", "#E74C3C")

            def _done():
                self._remote_conn_status.configure(text=msg, text_color=color)
                if self._notify_server_reachable_cb:
                    self._notify_server_reachable_cb(ok)

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_autopush_toggle(self) -> None:
        self._db.set_setting("remote_auto_push", self._autopush_var.get())
