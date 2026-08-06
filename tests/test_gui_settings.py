"""Unit tests for the GUI settings store and the accent-colour palette derivation.

All file I/O is aimed at pytest's ``tmp_path`` — never the real ``settings.json`` beside the saves
(same rule as the persistence tests). These are Qt-free: no PySide6 needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trader_pro.gui.settings as S            # noqa: E402
from trader_pro.gui.model import accent_palette, _scale_hex   # noqa: E402


# --------------------------------------------------------------------------- #
# is_hex_color
# --------------------------------------------------------------------------- #

def test_is_hex_color_accepts_rrggbb():
    assert S.is_hex_color("#2fae4e")
    assert S.is_hex_color("#FFFFFF")


def test_is_hex_color_rejects_junk():
    for bad in ("2fae4e", "#2fae4", "#2fae4ee", "#ggghhh", "", None, 123, "#12345"):
        assert not S.is_hex_color(bad)


# --------------------------------------------------------------------------- #
# load / save round-trip (against tmp_path only)
# --------------------------------------------------------------------------- #

def test_save_load_roundtrip(tmp_path: Path):
    p = tmp_path / "settings.json"
    S.save_settings({"accent": "#123456", "other": 1}, p)
    assert S.load_settings(p) == {"accent": "#123456", "other": 1}
    # atomic write leaves no temp turds behind
    assert not list(tmp_path.glob(".tmp*"))


def test_load_missing_file_is_empty(tmp_path: Path):
    assert S.load_settings(tmp_path / "nope.json") == {}


def test_load_corrupt_file_is_empty(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text("{ this is not json ", encoding="utf-8")
    assert S.load_settings(p) == {}          # defensive: garbage -> defaults, never raises


def test_load_non_object_json_is_empty(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert S.load_settings(p) == {}


# --------------------------------------------------------------------------- #
# accent get / set / clear
# --------------------------------------------------------------------------- #

def test_accent_unset_is_none(tmp_path: Path):
    assert S.accent_color(tmp_path / "settings.json") is None


def test_set_then_get_accent(tmp_path: Path):
    p = tmp_path / "settings.json"
    S.set_accent_color("#3B82F6", p)
    assert S.accent_color(p) == "#3b82f6"     # normalised to lower-case


def test_set_accent_rejects_bad_colour(tmp_path: Path):
    p = tmp_path / "settings.json"
    try:
        S.set_accent_color("blue", p)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a non-hex colour")
    assert not p.exists()                      # nothing written on rejection


def test_invalid_stored_accent_reads_as_none(tmp_path: Path):
    p = tmp_path / "settings.json"
    S.save_settings({"accent": "chartreuse"}, p)
    assert S.accent_color(p) is None           # invalid value -> fall back to default


def test_clear_accent(tmp_path: Path):
    p = tmp_path / "settings.json"
    S.set_accent_color("#abcdef", p)
    S.clear_accent_color(p)
    assert S.accent_color(p) is None
    # clearing keeps other keys intact
    S.save_settings({"accent": "#abcdef", "keep": 9}, p)
    S.clear_accent_color(p)
    assert S.load_settings(p) == {"keep": 9}


# --------------------------------------------------------------------------- #
# palette derivation
# --------------------------------------------------------------------------- #

def test_default_palette_matches_historical_constants():
    # None accent must reproduce the exact hand-tuned phosphor-green chrome (no drift for existing users)
    assert accent_palette(None) == ("#2fae4e", "#38c172", "#1c682f")


def test_custom_accent_derives_hi_and_selection():
    accent, hi, sel = accent_palette("#3b82f6")
    assert accent == "#3b82f6"                 # the picked colour is the accent verbatim
    assert hi == _scale_hex("#3b82f6", 1.2)    # brighter highlight
    assert sel == _scale_hex("#3b82f6", 0.6)   # dimmed row-selection


def test_scale_hex_clamps_and_brightens():
    assert _scale_hex("#000000", 2.0) == "#000000"
    assert _scale_hex("#ffffff", 2.0) == "#ffffff"   # clamped, no overflow
    assert _scale_hex("#804020", 0.5) == "#402010"   # halved channels


def test_selection_scale_reproduces_default_green():
    # the ×0.6 rule is exactly where the original SELECTION #1c682f came from
    assert _scale_hex("#2fae4e", 0.6) == "#1c682f"


# --------------------------------------------------------------------------- #
# P1: settings_path / get_setting / update_settings
# --------------------------------------------------------------------------- #

def test_settings_path_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADER_PRO_SETTINGS_DIR", str(tmp_path / "cfg"))
    assert S.settings_path() == tmp_path / "cfg" / "settings.json"
    # and the no-path helpers resolve through it at call time
    S.update_settings({"speed": 3})
    assert S.get_setting("speed") == 3
    assert (tmp_path / "cfg" / "settings.json").exists()


def test_get_setting_returns_default_when_absent(tmp_path: Path):
    p = tmp_path / "settings.json"
    assert S.get_setting("view", "watchlist", p) == "watchlist"     # no file at all
    S.save_settings({"other": 1}, p)
    assert S.get_setting("view", "watchlist", p) == "watchlist"     # file, but no key
    S.save_settings({"view": "stocks"}, p)
    assert S.get_setting("view", "watchlist", p) == "stocks"


def test_update_settings_merges_and_none_removes(tmp_path: Path):
    p = tmp_path / "settings.json"
    S.update_settings({"a": 1, "b": 2}, p)
    S.update_settings({"b": 3, "c": True}, p)                       # merge preserves untouched keys
    assert S.load_settings(p) == {"a": 1, "b": 3, "c": True}
    S.update_settings({"a": None, "missing": None}, p)              # None removes; absent = no-op
    assert S.load_settings(p) == {"b": 3, "c": True}
    assert not list(tmp_path.glob(".tmp*"))                         # still atomic, no temp turds


def test_accent_helpers_ride_the_generics(tmp_path: Path):
    p = tmp_path / "settings.json"
    S.update_settings({"keep": 9}, p)
    S.set_accent_color("#3B82F6", p)                                # refactored onto update_settings
    assert S.load_settings(p) == {"keep": 9, "accent": "#3b82f6"}
