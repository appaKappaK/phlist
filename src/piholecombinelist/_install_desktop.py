"""Desktop shortcut installer for Pi-hole Combine List."""
# v1.1.3

import shutil
import subprocess
import sys
from pathlib import Path

try:
    import importlib.resources as _ir
    _ASSETS = _ir.files("piholecombinelist") / "assets"
except Exception:
    _ASSETS = None


def _read_asset(name: str) -> bytes:
    """Read a bundled asset, falling back to a path relative to this file."""
    if _ASSETS is not None:
        try:
            return (_ASSETS / name).read_bytes()
        except Exception:
            pass
    # Editable install / fallback
    return (Path(__file__).parent / "assets" / name).read_bytes()


def install() -> tuple[bool, str]:
    """Install the .desktop entry and icon into the user's local share dirs.

    Returns (success: bool, message: str).
    """
    if sys.platform != "linux":
        return False, "Desktop installation is only supported on Linux."

    icon_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"
    apps_dir = Path.home() / ".local/share/applications"

    png_dir = Path.home() / ".local/share/icons/hicolor/256x256/apps"

    try:
        icon_dir.mkdir(parents=True, exist_ok=True)
        png_dir.mkdir(parents=True, exist_ok=True)
        apps_dir.mkdir(parents=True, exist_ok=True)

        (icon_dir / "piholecombinelist.svg").write_bytes(
            _read_asset("piholecombinelist.svg")
        )
        # Also install a PNG at the size-specific hicolor path and use its
        # absolute path in Icon= so the desktop environment never needs to
        # resolve a symbolic name via the icon theme cache.
        png_path = png_dir / "piholecombinelist.png"
        png_path.write_bytes(_read_asset("piholecombinelist.png"))

        # Resolve the absolute path to phlist so the launcher works without
        # the user's shell PATH being inherited by the desktop environment.
        exec_cmd = shutil.which("phlist") or f"{sys.executable} -m piholecombinelist.gui"
        desktop_content = _read_asset("piholecombinelist.desktop").decode()
        desktop_content = "\n".join(
            f"Exec={exec_cmd}" if line.startswith("Exec=") else
            f"Icon={png_path}" if line.startswith("Icon=") else
            line
            for line in desktop_content.splitlines()
        ) + "\n"
        (apps_dir / "piholecombinelist.desktop").write_text(desktop_content, encoding="utf-8")

        # Update caches (best-effort — missing tools are fine)
        for cmd in (
            ["update-desktop-database", str(apps_dir)],
            [
                "gtk-update-icon-cache", "-f", "-t",
                str(Path.home() / ".local/share/icons/hicolor"),
            ],
        ):
            try:
                subprocess.run(cmd, check=False, capture_output=True)
            except FileNotFoundError:
                pass

        return True, "Desktop shortcut installed — check your app launcher."

    except Exception as exc:
        return False, f"Installation failed: {exc}"


def main() -> None:
    ok, msg = install()
    print(msg)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
