#!/usr/bin/env python3
"""Regenerate all derived image assets from the source SVG.

This is the one-stop script to run when the SVG icon changes.
It regenerates every size variant used by the app.

Usage:
    python scripts/agent/gen_assets.py
"""

import os
import sys

# Ensure we can import sibling scripts
sys.path.insert(0, os.path.dirname(__file__))
from render_svg import render
from image_info import info

ASSETS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "piholecombinelist", "assets"
)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated")
SVG_SOURCE = os.path.join(ASSETS_DIR, "piholecombinelist.svg")

# (output_filename, size) — add new entries here when the app needs more sizes
TARGETS = [
    ("piholecombinelist.png", 256),   # taskbar / window icon
    ("splash_logo.png", 128),         # splash screen logo
]

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Source:  {SVG_SOURCE}")
    print(f"Output:  {OUTPUT_DIR}")
    print()

    for filename, size in TARGETS:
        out = os.path.join(OUTPUT_DIR, filename)
        render(SVG_SOURCE, out, size)

    print()
    print("=== Asset summary ===")
    for filename, _ in TARGETS:
        info(os.path.join(OUTPUT_DIR, filename))

    print()
    print("To use: copy the files you need into src/piholecombinelist/assets/")
