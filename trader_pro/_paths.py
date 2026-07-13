"""Runtime path resolution that works both from source and when frozen with PyInstaller.

From source, read-only resources (the seed universe) and writable state (saves, logs) both live
under the repo root. When frozen into a `.exe`:

* bundled read-only data is unpacked to PyInstaller's ``_MEIPASS`` temp dir, and
* writable state must live somewhere that *persists* between runs — next to the executable — so a
  portable Trader PRO keeps your saves right beside the `.exe`.

Both helpers return the repo root when running from source, so behaviour is identical in dev.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]        # <repo>/  (this file is trader_pro/_paths.py)


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Base dir for read-only bundled resources (seed data lives under ``data/seeds``).

    Frozen: PyInstaller's extraction dir (``sys._MEIPASS``). From source: the repo root."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    return _REPO_ROOT


def user_data_dir() -> Path:
    """Base dir for writable state (``saves/``, ``logs/``).

    Frozen: alongside the ``.exe`` so it survives between runs. From source: the repo root."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _REPO_ROOT
