"""Settings tab: list type toggle, server port, desktop shortcut."""

from tkinter import messagebox

import customtkinter as ctk

from ..database import Database
from ..server import ListServer


class SettingsTab(ctk.CTkFrame):
    """The Settings tab: server port and desktop shortcut."""

    def __init__(self, parent, server: ListServer, list_type_var: ctk.StringVar,
                 db: Database) -> None:
        super().__init__(parent, fg_color="transparent")
        self._server = server
        self._list_type_var = list_type_var
        self._db = db
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # ── List type section ────────────────────────────────────────
        ctk.CTkLabel(
            self, text="LIST TYPE", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        type_frame = ctk.CTkFrame(self)
        type_frame.grid(row=1, column=0, sticky="w", padx=20)

        ctk.CTkSegmentedButton(
            type_frame,
            values=["Blocklist", "Allowlist"],
            variable=self._list_type_var,
        ).pack(padx=12, pady=12)

        ctk.CTkLabel(
            self, text="Sets the output header and window title.",
            text_color="gray60",
        ).grid(row=2, column=0, sticky="w", padx=20, pady=(4, 20))

        # ── Server section ───────────────────────────────────────────
        ctk.CTkLabel(
            self, text="SERVER", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=3, column=0, sticky="w", padx=20, pady=(0, 8))

        port_frame = ctk.CTkFrame(self)
        port_frame.grid(row=4, column=0, sticky="w", padx=20)

        ctk.CTkLabel(port_frame, text="Listen port:").pack(side="left", padx=(12, 8), pady=12)
        self._port_entry = ctk.CTkEntry(port_frame, width=80)
        self._port_entry.insert(0, str(self._server._port))
        self._port_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(port_frame, text="Apply", width=70, command=self._apply_port).pack(side="left")

        ctk.CTkLabel(
            self, text="Takes effect the next time you start serving.",
            text_color="gray60",
        ).grid(row=5, column=0, sticky="w", padx=20, pady=(4, 20))

        # ── Desktop integration section ──────────────────────────────
        ctk.CTkLabel(
            self, text="DESKTOP INTEGRATION", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=6, column=0, sticky="w", padx=20, pady=(0, 8))

        desktop_frame = ctk.CTkFrame(self)
        desktop_frame.grid(row=7, column=0, sticky="w", padx=20)

        ctk.CTkButton(
            desktop_frame, text="Install Desktop Shortcut", width=190,
            command=self._install_desktop,
        ).pack(side="left", padx=12, pady=12)
        self._desktop_status = ctk.CTkLabel(desktop_frame, text="", text_color="gray60")
        self._desktop_status.pack(side="left", padx=(0, 12))

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
