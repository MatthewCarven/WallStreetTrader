"""User preferences for the desktop GUI, persisted as a small JSON file.

Holds install-level trivia — the theme **accent** plus, since P1 of the polish pass, session
memory (window geometry, board view + sort, chart range, speed). The shape is a plain dict so
more knobs can join without a migration. Game-state knobs (e.g. the brokerage fee level) do NOT
belong here: they live on ``world.config`` and travel with the save, not the install. The file
lives beside the saves (see ``_paths.user_data_dir``), so a portable Trader PRO carries your
preferences next to the ``.exe`` — same philosophy as the save slots.

Deliberately **Qt-free and defensive**: a missing, unreadable, or garbage file yields defaults and
never raises. The app must boot even if this file is corrupt, so every reader swallows errors and
falls back — mirroring the codebase's "never crash the UI over I/O" stance. Writes are atomic
(temp file + ``os.replace``), the same crash-safe trick the save layer uses.

Paths are resolved **at call time** via :func:`settings_path`, which honours the
``TRADER_PRO_SETTINGS_DIR`` env var. That override exists for test isolation — the GUI tests
construct the real ``TraderGUI`` (which now *reads* settings at boot), and must never see, nor
write, a developer's live ``settings.json`` (``tests/conftest.py`` points the var at ``tmp_path``).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .._paths import user_data_dir

# Historical default location; kept as a constant for reference/back-compat, but callers that
# pass no explicit path get settings_path(), resolved at call time (env-var aware).
SETTINGS_PATH = user_data_dir() / "settings.json"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def settings_path() -> Path:
    """Where the settings file lives *right now*.

    ``TRADER_PRO_SETTINGS_DIR`` (a directory) overrides the default — the hook the GUI tests use
    to aim all settings I/O at a temp dir. Otherwise: ``<user data>/settings.json`` — beside
    ``saves/`` from source; beside the ``.exe`` when frozen."""
    override = os.environ.get("TRADER_PRO_SETTINGS_DIR")
    if override:
        return Path(override) / "settings.json"
    return user_data_dir() / "settings.json"


def is_hex_color(value: Any) -> bool:
    """True for a ``#rrggbb`` string (the form QColorDialog.name() returns)."""
    return isinstance(value, str) and bool(_HEX_RE.match(value))


# --------------------------------------------------------------------------- #
# Raw load / save
# --------------------------------------------------------------------------- #

def load_settings(path: Path | str | None = None) -> dict:
    """The settings dict, or ``{}`` if the file is missing / unreadable / not a JSON object."""
    try:
        with Path(path if path is not None else settings_path()).open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data: dict, path: Path | str | None = None) -> None:
    """Atomically write ``data`` as JSON (temp file in the same dir, then ``os.replace``)."""
    path = Path(path if path is not None else settings_path())
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
# Generic get / update  (P1)
# --------------------------------------------------------------------------- #

def get_setting(key: str, default: Any = None, path: Path | str | None = None) -> Any:
    """One value from the settings file, or ``default`` when the file or key is absent.

    Values come back exactly as stored — callers validate (settings are user-editable JSON,
    so treat every value as untrusted input)."""
    return load_settings(path).get(key, default)


def update_settings(changes: Mapping[str, Any], path: Path | str | None = None) -> None:
    """Merge ``changes`` into the settings file in one atomic write.

    A value of ``None`` **removes** its key (settings are trivia with defaults — "unset" beats
    storing nulls). Keys not named in ``changes`` are preserved untouched."""
    data = load_settings(path)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    save_settings(data, path)


# --------------------------------------------------------------------------- #
# Accent colour
# --------------------------------------------------------------------------- #

def accent_color(path: Path | str | None = None) -> str | None:
    """The saved accent hex, or ``None`` when unset or invalid (so callers fall back to default)."""
    value = get_setting("accent", path=path)
    return value.lower() if is_hex_color(value) else None


def set_accent_color(hex_color: str, path: Path | str | None = None) -> None:
    """Persist ``hex_color`` (a ``#rrggbb`` string) as the accent. Raises ValueError on bad input."""
    if not is_hex_color(hex_color):
        raise ValueError(f"not a #rrggbb colour: {hex_color!r}")
    update_settings({"accent": hex_color.lower()}, path)


def clear_accent_color(path: Path | str | None = None) -> None:
    """Drop any saved accent so the app reverts to its default phosphor green next launch."""
    data = load_settings(path)
    if data.pop("accent", None) is not None:
        save_settings(data, path)
