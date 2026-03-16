"""Main application window."""

import base64
import importlib.resources as _ir
import tkinter as _tk

import customtkinter as ctk

from .. import __version__
from ..database import Database
from ..server import ListServer
from .combine_tab import CombineTab
from .library_tab import LibraryTab
from .settings_tab import SettingsTab

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.geometry("1000x700")
        self.minsize(800, 580)

        # Set window/taskbar icon
        try:
            _png = (_ir.files("piholecombinelist") / "assets" / "piholecombinelist.png").read_bytes()
            self._icon = _tk.PhotoImage(data=base64.b64encode(_png).decode())
            self.iconphoto(True, self._icon)
        except Exception:
            pass  # Non-fatal — icon is cosmetic

        self._db = Database()
        self._server = ListServer()

        # Restore persisted port
        self._server._port = int(self._db.get_setting("port", "8765"))

        # Restore persisted list type; trace fires on every subsequent change
        list_type = self._db.get_setting("list_type", "Blocklist")
        self._list_type_var = ctk.StringVar(value=list_type)
        self._list_type_var.trace_add("write", self._on_list_type_change)

        # Title reflects the loaded list type immediately
        self.title(f"Pi-hole Combined {list_type} Generator  v{__version__}")

        self._tabs = ctk.CTkTabview(self, command=self._on_tab_change)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self._tabs.add("Combine")
        self._tabs.add("Library")
        self._tabs.add("Settings")

        self._combine_tab = CombineTab(
            self._tabs.tab("Combine"),
            self._db,
            switch_to_library_cb=lambda: self._tabs.set("Library"),
            server=self._server,
            list_type_var=self._list_type_var,
        )
        self._combine_tab.pack(fill="both", expand=True)

        self._library_tab = LibraryTab(
            self._tabs.tab("Library"),
            self._db,
            get_combine_tab_cb=lambda: self._combine_tab,
            switch_to_combine_cb=lambda: self._tabs.set("Combine"),
        )
        self._library_tab.pack(fill="both", expand=True)

        self._settings_tab = SettingsTab(
            self._tabs.tab("Settings"),
            self._server,
            self._list_type_var,
            db=self._db,
        )
        self._settings_tab.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_list_type_change(self, *_) -> None:
        list_type = self._list_type_var.get()
        self.title(f"Pi-hole Combined {list_type} Generator  v{__version__}")
        self._db.set_setting("list_type", list_type)

    def _on_tab_change(self) -> None:
        if self._tabs.get() == "Library":
            self._library_tab.refresh()

    def _on_close(self) -> None:
        self._server.stop()
        self._db.close()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
