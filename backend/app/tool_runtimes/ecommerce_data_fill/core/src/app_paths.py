from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Return the folder containing the runnable application and its editable config."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    adjacent_config = app_base_dir() / "config"
    if adjacent_config.is_dir() or not getattr(sys, "frozen", False):
        return adjacent_config

    # PyInstaller one-folder builds place collected data files under
    # ``_internal`` (``sys._MEIPASS``).  Keep an EXE-adjacent config folder
    # supported for user overrides, then fall back to the bundled copy.
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        bundled_config = Path(bundle_dir) / "config"
        if bundled_config.is_dir():
            return bundled_config
    return adjacent_config
