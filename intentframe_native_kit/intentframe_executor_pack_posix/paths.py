"""Platform-neutral default storage locations for the POSIX executor pack."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def default_data_dir() -> Path:
    """Default directory for executor SQLite databases.

    Preserves the historical macOS location so existing installs keep using
    the same path, and uses an XDG-style location everywhere else (Linux,
    containers, cloud).
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "IntentFrame"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "intentframe"
