"""Settings tab: two-column layout with appearance, stats, log, timeout, and more."""

import subprocess
from collections import deque
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..database import Database, _DATA_DIR
from ..server import ListServer
from .tooltip import Tooltip


def _format_bytes(n: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class SettingsTab(ctk.CTkFrame):
    """The Settings tab: server port, appearance, stats, log, and more."""

    def __init__(self, parent, server: ListServer, list_type_var: ctk.StringVar,
                 db: Database) -> None:
        super().__init__(parent, fg_color="transparent")
        self._server = server
        self._list_type_var = list_type_var
        self._db = db
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # ── Left column ────────────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)

        # ── LIST TYPE ──────────────────────────────────────────────
        ctk.CTkLabel(
            left, text="LIST TYPE", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))

        type_frame = ctk.CTkFrame(left)
        type_frame.pack(fill="x", padx=12)
        type_toggle = ctk.CTkSegmentedButton(
            type_frame,
            values=["Blocklist", "Allowlist"],
            variable=self._list_type_var,
        )
        type_toggle.pack(padx=12, pady=12)
        Tooltip(type_toggle, "Cosmetic only: changes the .txt header and window title. Does not affect how Pi-hole processes the list.")

        # ── SERVER ─────────────────────────────────────────────────
        ctk.CTkLabel(
            left, text="SERVER", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(16, 6))

        port_frame = ctk.CTkFrame(left)
        port_frame.pack(fill="x", padx=12)
        ctk.CTkLabel(port_frame, text="Listen port:").pack(side="left", padx=(12, 8), pady=12)
        self._port_entry = ctk.CTkEntry(port_frame, width=80)
        self._port_entry.insert(0, str(self._server._port))
        self._port_entry.pack(side="left", padx=(0, 8))
        Tooltip(self._port_entry, "The port the HTTP server listens on. Default: 8765.")
        apply_btn = ctk.CTkButton(port_frame, text="Apply", width=70, command=self._apply_port)
        apply_btn.pack(side="left")
        Tooltip(apply_btn, "Save the port. Takes effect the next time you host a list.")

        # ── DESKTOP INTEGRATION ────────────────────────────────────
        ctk.CTkLabel(
            left, text="DESKTOP INTEGRATION", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(16, 6))

        desktop_frame = ctk.CTkFrame(left)
        desktop_frame.pack(fill="x", padx=12)
        desktop_btn = ctk.CTkButton(
            desktop_frame, text="Install Desktop Shortcut", width=190,
            command=self._install_desktop,
        )
        desktop_btn.pack(side="left", padx=12, pady=12)
        Tooltip(desktop_btn, "Create a .desktop launcher entry so the app appears in your GNOME/KDE app menu.")
        self._desktop_status = ctk.CTkLabel(desktop_frame, text="", text_color=("gray15", "gray60"))
        self._desktop_status.pack(side="left", padx=(0, 12))

        # ── FETCH TIMEOUT ──────────────────────────────────────────
        ctk.CTkLabel(
            left, text="FETCH TIMEOUT", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(16, 6))

        timeout_frame = ctk.CTkFrame(left)
        timeout_frame.pack(fill="x", padx=12)
        ctk.CTkLabel(timeout_frame, text="Timeout:").pack(side="left", padx=(12, 8), pady=12)
        self._timeout_entry = ctk.CTkEntry(timeout_frame, width=60)
        saved_timeout = self._db.get_setting("fetch_timeout", "30")
        self._timeout_entry.insert(0, saved_timeout)
        self._timeout_entry.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(timeout_frame, text="seconds", text_color=("gray15", "gray60")).pack(side="left", padx=(0, 8))
        timeout_btn = ctk.CTkButton(timeout_frame, text="Apply", width=70, command=self._apply_timeout)
        timeout_btn.pack(side="left")
        Tooltip(self._timeout_entry, "How long to wait for each URL before giving up. Default: 30 seconds.")

        # ── DEFAULT FILENAME ───────────────────────────────────────
        ctk.CTkLabel(
            left, text="DEFAULT FILENAME", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(16, 6))

        fname_frame = ctk.CTkFrame(left)
        fname_frame.pack(fill="x", padx=12)
        ctk.CTkLabel(fname_frame, text="Default:").pack(side="left", padx=(12, 8), pady=12)
        self._fname_entry = ctk.CTkEntry(fname_frame, width=140, placeholder_text="blocklist")
        saved_fname = self._db.get_setting("default_host_filename", "")
        if saved_fname:
            self._fname_entry.insert(0, saved_fname)
        self._fname_entry.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(fname_frame, text=".txt", text_color=("gray15", "gray60")).pack(side="left", padx=(0, 8))
        fname_btn = ctk.CTkButton(fname_frame, text="Save", width=70, command=self._save_filename)
        fname_btn.pack(side="left")
        Tooltip(self._fname_entry, "Pre-fills the host filename on the Combine tab. Leave blank for 'blocklist'.")

        # ── Right column ───────────────────────────────────────────
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.columnconfigure(0, weight=1)

        # ── APPEARANCE ─────────────────────────────────────────────
        ctk.CTkLabel(
            right, text="APPEARANCE", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))

        appearance_frame = ctk.CTkFrame(right)
        appearance_frame.pack(fill="x", padx=12)
        saved_mode = self._db.get_setting("appearance_mode", "Dark")
        self._appearance_var = ctk.StringVar(value=saved_mode)
        appearance_toggle = ctk.CTkSegmentedButton(
            appearance_frame,
            values=["Light", "Dark", "System"],
            variable=self._appearance_var,
            command=self._on_appearance_change,
        )
        appearance_toggle.pack(padx=12, pady=12)
        Tooltip(appearance_toggle, "Switch between light, dark, or system-matched theme.")

        # ── LIBRARY STATS ──────────────────────────────────────────
        ctk.CTkLabel(
            right, text="LIBRARY", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(16, 6))

        stats_frame = ctk.CTkFrame(right)
        stats_frame.pack(fill="x", padx=12)
        self._stats_labels: dict[str, ctk.CTkLabel] = {}
        for key in ("folders", "lists", "domains", "db_size"):
            lbl = ctk.CTkLabel(stats_frame, text="", anchor="w")
            lbl.pack(anchor="w", padx=12, pady=1)
            self._stats_labels[key] = lbl
        stats_btn = ctk.CTkButton(stats_frame, text="Refresh Stats", width=120, command=self._refresh_stats)
        stats_btn.pack(padx=12, pady=(6, 12))
        self._refresh_stats()

        # ── LOG VIEWER ─────────────────────────────────────────────
        ctk.CTkLabel(
            right, text="LOG", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(16, 6))

        log_frame = ctk.CTkFrame(right)
        log_frame.pack(fill="x", padx=12)
        self._log_box = ctk.CTkTextbox(log_frame, height=120, wrap="none", state="disabled",
                                        font=ctk.CTkFont(size=11))
        self._log_box.pack(fill="x", padx=12, pady=(12, 6))
        log_btn_row = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(log_btn_row, text="Refresh", width=80, command=self._refresh_log).pack(side="left", padx=(0, 8))
        ctk.CTkButton(log_btn_row, text="Open Log File", width=110, command=self._open_log).pack(side="left")
        self._refresh_log()

        # ── EXPORT / IMPORT (full width) ───────────────────────────
        export_frame = ctk.CTkFrame(self)
        export_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            export_frame, text="DATA", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))

        btn_row = ctk.CTkFrame(export_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        export_btn = ctk.CTkButton(btn_row, text="Export Library...", width=140, command=self._export_stub)
        export_btn.pack(side="left", padx=(0, 8))
        Tooltip(export_btn, "Export your entire library as a backup file.")
        import_btn = ctk.CTkButton(btn_row, text="Import Library...", width=140, command=self._import_stub)
        import_btn.pack(side="left")
        Tooltip(import_btn, "Import a previously exported library backup.")

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

    def _on_appearance_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)
        self._db.set_setting("appearance_mode", value)

    def _refresh_stats(self) -> None:
        stats = self._db.get_library_stats()
        self._stats_labels["folders"].configure(text=f"Folders: {stats['folder_count']}")
        self._stats_labels["lists"].configure(text=f"Lists: {stats['list_count']}")
        self._stats_labels["domains"].configure(text=f"Total domains: {stats['total_domains']:,}")
        self._stats_labels["db_size"].configure(text=f"Database size: {_format_bytes(stats['db_bytes'])}")

    def _refresh_log(self) -> None:
        log_path = _DATA_DIR / "piholecombinelist.log"
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                lines = deque(f, maxlen=15)
            text = "".join(lines).rstrip("\n")
        except FileNotFoundError:
            text = "(no log file found)"
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.insert("1.0", text)
        self._log_box.configure(state="disabled")

    def _open_log(self) -> None:
        log_path = _DATA_DIR / "piholecombinelist.log"
        if not log_path.exists():
            messagebox.showinfo("No log", "Log file does not exist yet.")
            return
        try:
            subprocess.Popen(["xdg-open", str(log_path)])
        except Exception as exc:
            messagebox.showerror("Could not open", f"Failed to open log file:\n{exc}")

    def _apply_timeout(self) -> None:
        raw = self._timeout_entry.get().strip()
        try:
            val = int(raw)
            if not (1 <= val <= 300):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid timeout", "Enter a number between 1 and 300.")
            saved = self._db.get_setting("fetch_timeout", "30")
            self._timeout_entry.delete(0, "end")
            self._timeout_entry.insert(0, saved)
            return
        self._db.set_setting("fetch_timeout", str(val))

    def _save_filename(self) -> None:
        name = self._fname_entry.get().strip()
        # Strip .txt if user typed it
        if name.lower().endswith(".txt"):
            name = name[:-4]
        self._db.set_setting("default_host_filename", name)

    def _export_stub(self) -> None:
        messagebox.showinfo("Coming soon", "Export is not yet implemented.")

    def _import_stub(self) -> None:
        messagebox.showinfo("Coming soon", "Import is not yet implemented.")
