"""Console + rotating file logging."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import load_settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    s = load_settings()
    s.log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, s.log_level.upper(), logging.INFO))
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = RotatingFileHandler(s.log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    _configured = True
