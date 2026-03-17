#!/usr/bin/env python3
"""Render an SVG to PNG at a given size.

Tries renderers in order: cairosvg (Python) → rsvg-convert → magick/convert (ImageMagick).
Falls back gracefully with a clear error if none are available.

Usage:
    python scripts/agent/render_svg.py INPUT.svg OUTPUT.png [SIZE]

    SIZE defaults to 128. Produces a SIZExSIZE PNG.

Examples:
    python scripts/agent/render_svg.py src/piholecombinelist/assets/piholecombinelist.svg splash_logo.png 128
    python scripts/agent/render_svg.py src/piholecombinelist/assets/piholecombinelist.svg icon_64.png 64
"""

import shutil
import subprocess
import sys


def _try_cairosvg(svg_path: str, png_path: str, size: int) -> bool:
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png_path,
                         output_width=size, output_height=size)
        return True
    except ImportError:
        return False


def _try_rsvg(svg_path: str, png_path: str, size: int) -> bool:
    cmd = shutil.which("rsvg-convert")
    if not cmd:
        return False
    subprocess.run(
        [cmd, "-w", str(size), "-h", str(size), svg_path, "-o", png_path],
        check=True,
    )
    return True


def _try_imagemagick(svg_path: str, png_path: str, size: int) -> bool:
    magick = shutil.which("magick")
    convert = shutil.which("convert")
    if magick:
        # IMv7: magick INPUT [options] OUTPUT
        subprocess.run(
            [magick, svg_path, "-background", "none", "-density", "300",
             "-resize", f"{size}x{size}", png_path],
            check=True,
        )
        return True
    elif convert:
        # IMv6: convert [options] INPUT OUTPUT
        subprocess.run(
            [convert, "-background", "none", "-density", "300",
             "-resize", f"{size}x{size}", svg_path, png_path],
            check=True,
        )
        return True
    return False


def render(svg_path: str, png_path: str, size: int = 128) -> None:
    for name, fn in [("cairosvg", _try_cairosvg),
                     ("rsvg-convert", _try_rsvg),
                     ("ImageMagick", _try_imagemagick)]:
        try:
            if fn(svg_path, png_path, size):
                print(f"  Rendered {svg_path} → {png_path} ({size}x{size}) using {name}")
                return
        except Exception as exc:
            print(f"  {name} failed: {exc}")
    print("ERROR: No SVG renderer available.")
    print("  Install one of: cairosvg (pip), librsvg2-tools (apt/dnf), imagemagick")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    svg = sys.argv[1]
    png = sys.argv[2]
    sz = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    render(svg, png, sz)
