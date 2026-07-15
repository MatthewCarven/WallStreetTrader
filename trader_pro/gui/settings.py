"""User preferences for the desktop GUI, persisted as a small JSON file.

Currently holds just the theme **accent** colour, but the shape is a plain dict so more knobs can
join later without a migration. The file lives beside the saves (see ``_paths.user_data_dir``), so
a portable Trader PRO carries your theme next to the ``.exe`` — same philosophy as the save slots.

Deliberately **Qt-free and defensive**: a missing, unreadable, or garbage file yields defaults and
never raises. The app must boot even if this file is corrupt, so every reader swallows errors and
falls back — mirroring the codebase's "never crash the UI over I/O" stance. Writes are atomic
(temp file + ``os.replace``), the same crash-safe trick the save layer uses.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .._paths import user_data_dir

# <user data>/settings.json  — beside saves/ from source; beside the .exe when frozen.
SETTINGS_PATH = user_data_dir() / "settings.json"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex_color(value: Any) -> bool:
    """True for a ``#rrggbb`` string (the form QColorDialog.name() returns)."""
    return isinstance(value, str) and bool(_HEX_RE.match(value))


# --------------------------------------------------------------------------- #
# Raw load / save
# --------------------------------------------------------------------------- #

def load_settings(path: Path | str = SETTINGS_PATH) -> dict:
    """The settings dict, or ``{}`` if the file is missing / unreadable / not a JSON object."""
    try:
        with Path(path).open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data: dict, path: Path | str = SETTINGS_PATH) -> None:
    """Atomically write ``data`` as JSON (temp file in the same dir, then ``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_settings_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)              # atomic on POSIX & Windows
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Accent colour
# --------------------------------------------------------------------------- #

def accent_color(path: Path | str = SETTINGS_PATH) -> str | None:
    """The saved accent hex, or ``None`` when unset or invalid (so callers fall back to default)."""
    value = load_settings(path).get("accent")
    return value.lower() if is_hex_color(value) else None


def set_accent_color(hex_color: str, path: Path | str = SETTINGS_PATH) -> None:
    """Persist ``hex_color`` (a ``#rrggbb`` string) as the accent. Raises ValueError on bad input."""
    if not is_hex_color(hex_color):
        raise ValueError(f"not a #rrggbb colour: {hex_color!r}")
    data = load_settings(path)
    data["accent"] = hex_color.lower()
    save_settings(data, path)


def clear_accent_color(path: Path | str = SETTINGS_PATH) -> None:
    """Drop any saved accent so the app reverts to its default phosphor green next launch."""
    data = load_settings(path)
    if data.pop("accent", None) is not None:
        save_settings(data, path)
