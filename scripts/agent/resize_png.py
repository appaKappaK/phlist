#!/usr/bin/env python3
"""Resize a PNG image to a target size.

Tries: Pillow (Python) → ImageMagick.

Usage:
    python scripts/agent/resize_png.py INPUT.png OUTPUT.png SIZE

    SIZE is the target width=height (square). Use WxH for non-square.

Examples:
    python scripts/agent/resize_png.py logo.png logo_64.png 64
    python scripts/agent/resize_png.py logo.png banner.png 400x100
"""

import shutil
import subprocess
import sys


def _parse_size(s: str) -> tuple[int, int]:
    if "x" in s.lower():
        w, h = s.lower().split("x", 1)
        return int(w), int(h)
    n = int(s)
    return n, n


def _try_pillow(src: str, dst: str, w: int, h: int) -> bool:
    try:
        from PIL import Image
        img = Image.open(src)
        resized = img.resize((w, h), Image.LANCZOS)
        resized.save(dst, "PNG")
        print(f"  Resized {src} → {dst} ({w}x{h}) using Pillow")
        return True
    except ImportError:
        return False


def _try_imagemagick(src: str, dst: str, w: int, h: int) -> bool:
    cmd = shutil.which("magick") or shutil.which("convert")
    if not cmd:
        return False
    subprocess.run(
        [cmd, src, "-resize", f"{w}x{h}!", dst],
        check=True,
    )
    print(f"  Resized {src} → {dst} ({w}x{h}) using ImageMagick")
    return True


def resize(src: str, dst: str, w: int, h: int) -> None:
    for fn in (_try_pillow, _try_imagemagick):
        try:
            if fn(src, dst, w, h):
                return
        except Exception as exc:
            print(f"  Failed: {exc}")
    print("ERROR: No image resizer available. Install Pillow or ImageMagick.")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2]
    w, h = _parse_size(sys.argv[3])
    resize(src, dst, w, h)
