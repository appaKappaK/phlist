#!/usr/bin/env python3
"""Print image metadata (dimensions, format, file size).

Tries: Pillow (Python) → ImageMagick identify → file command.

Usage:
    python scripts/agent/image_info.py IMAGE_PATH [IMAGE_PATH ...]

Examples:
    python scripts/agent/image_info.py src/piholecombinelist/assets/*.png
"""

import os
import shutil
import subprocess
import sys


def _try_pillow(path: str) -> bool:
    try:
        from PIL import Image
        img = Image.open(path)
        size_kb = os.path.getsize(path) / 1024
        print(f"  {path}")
        print(f"    Format: {img.format}  Size: {img.size[0]}x{img.size[1]}  "
              f"Mode: {img.mode}  File: {size_kb:.1f} KB")
        return True
    except ImportError:
        return False


def _try_identify(path: str) -> bool:
    cmd = shutil.which("identify") or shutil.which("magick")
    if not cmd:
        return False
    args = [cmd] + (["identify"] if "magick" in cmd else []) + [path]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  {result.stdout.strip()}")
        return True
    return False


def _try_file(path: str) -> bool:
    cmd = shutil.which("file")
    if not cmd:
        return False
    result = subprocess.run([cmd, path], capture_output=True, text=True)
    if result.returncode == 0:
        size_kb = os.path.getsize(path) / 1024
        print(f"  {result.stdout.strip()}  ({size_kb:.1f} KB)")
        return True
    return False


def info(path: str) -> None:
    for fn in (_try_pillow, _try_identify, _try_file):
        if fn(path):
            return
    print(f"  {path}: could not read image info")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for p in sys.argv[1:]:
        info(p)
