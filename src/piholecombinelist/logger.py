"""Centralised logging setup — import ``setup_logging`` once at app startup."""

import logging
from logging.handlers import RotatingFileHandler

from .database import _DATA_DIR


def setup_logging() -> None:
    """Configure the ``piholecombinelist`` logger hierarchy.

    * **File** (``~/.local/share/piholecombinelist/piholecombinelist.log``): DEBUG level, 1 MB max, 1 backup.
    * **Console**: WARNING level (errors still print to terminal).
    """
    root = logging.getLogger("piholecombinelist")
    if root.handlers:
        return  # already configured (e.g. tests importing twice)
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    # File handler — rotating log in the XDG data directory
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        _DATA_DIR / "piholecombinelist.log",
        maxBytes=1_048_576,  # 1 MB
        backupCount=1,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — only warnings and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)
