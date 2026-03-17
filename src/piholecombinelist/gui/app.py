"""Main application window."""

import base64
import importlib.resources as _ir
import logging
import tkinter as _tk

import customtkinter as ctk

from .. import __version__
from ..database import Database
from ..logger import setup_logging
from ..server import ListServer
from .combine_tab import CombineTab
from .library_tab import LibraryTab
from .settings_tab import SettingsTab

_log = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Splash screen colours (easy to tweak) ─────────────────────────────
_SPLASH_BG = "#1a1a2e"       # dark navy background
_SPLASH_FG = "#e0e0e0"       # light text
_SPLASH_ACCENT = "#3B8ED0"   # accent / version text
_SPLASH_MS = 1500            # auto-dismiss after this many ms


class _SplashScreen(ctk.CTkToplevel):
    """Borderless splash shown while the main window initialises."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.overrideredirect(True)  # borderless
        self.configure(fg_color=_SPLASH_BG)
        self.attributes("-topmost", True)

        # Size + center on screen
        w, h = 380, 280
        sx = (self.winfo_screenwidth() - w) // 2
        sy = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{sx}+{sy}")

        # Load the larger splash logo
        try:
            from PIL import Image
            logo_path = _ir.files("piholecombinelist") / "assets" / "splash_logo.png"
            pil_img = Image.open(str(logo_path))
            self._logo = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(128, 128))
            ctk.CTkLabel(self, image=self._logo, text="", fg_color=_SPLASH_BG).pack(pady=(24, 8))
        except Exception:
            pass  # Non-fatal — splash still shows text

        ctk.CTkLabel(
            self,
            text="Block/Allowlist Combiner",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=_SPLASH_FG,
            fg_color=_SPLASH_BG,
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            self,
            text=f"for Pi-hole  v{__version__}",
            font=ctk.CTkFont(size=12),
            text_color=_SPLASH_ACCENT,
            fg_color=_SPLASH_BG,
        ).pack()

        ctk.CTkLabel(
            self,
            text="Loading...",
            font=ctk.CTkFont(size=11),
            text_color="gray50",
            fg_color=_SPLASH_BG,
        ).pack(pady=(12, 0))

        # Block interaction with busy cursor
        self.configure(cursor="watch")
        self.update_idletasks()
        self.grab_set()


class App(ctk.CTk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        setup_logging()
        _log.info("App started — v%s", __version__)

        # Hide main window during init
        self.withdraw()

        self.geometry("1000x700")
        self.minsize(800, 580)

        # Set window/taskbar icon
        self._icon = None
        try:
            _png = (_ir.files("piholecombinelist") / "assets" / "piholecombinelist.png").read_bytes()
            self._icon = _tk.PhotoImage(data=base64.b64encode(_png).decode())
            self.iconphoto(True, self._icon)
        except Exception:
            pass  # Non-fatal — icon is cosmetic

        # Show splash while we set up
        splash = _SplashScreen(self)
        self.update()

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
            server=self._server,
            list_type_var=self._list_type_var,
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

        # Dismiss splash and reveal main window
        def _dismiss_splash():
            splash.grab_release()
            splash.destroy()
            self.deiconify()

        self.after(_SPLASH_MS, _dismiss_splash)

    def _on_list_type_change(self, *_) -> None:
        list_type = self._list_type_var.get()
        self.title(f"Pi-hole Combined {list_type} Generator  v{__version__}")
        self._db.set_setting("list_type", list_type)

    def _on_tab_change(self) -> None:
        if self._tabs.get() == "Library":
            self._library_tab.refresh()

    def _on_close(self) -> None:
        _log.info("App closed")
        self._server.stop()
        self._db.close()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
