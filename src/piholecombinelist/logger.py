"""Centralised logging setup — import ``setup_logging`` once at app startup."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging() -> None:
    """Configure the ``piholecombinelist`` logger hierarchy.

    * **File** (``~/.db/piholecombinelist.log``): DEBUG level, 1 MB max, 3 backups.
    * **Console**: WARNING level (errors still print to terminal).
    """
    root = logging.getLogger("piholecombinelist")
    if root.handlers:
        return  # already configured (e.g. tests importing twice)
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    # File handler — rotating log in the same directory as the database
    log_dir = Path.home() / ".db"
    log_dir.mkdir(exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / "piholecombinelist.log",
        maxBytes=1_048_576,  # 1 MB
        backupCount=3,
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
