"""Game persistence (V1.7) — enriched, crash-safe save slots + a browser API.

Builds on the core `World.to_dict()` / `load_world()`. A save file is the world's JSON plus a
small ``"meta"`` envelope (net worth, return, clock, profile, timestamp) so the load browser can
summarise a slot *without* rebuilding the engine or recomputing prices. ``from_dict`` ignores the
extra key, so saves stay backward/forward compatible.

Writes are **atomic**: we write a temp file in the same directory and ``os.replace`` it into place,
so a crash mid-write can never corrupt an existing slot (this matters for the frequent autosave).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import World, load_world

# repo-root/saves  (this file is trader_pro/persistence.py)
SAVES_DIR = Path(__file__).resolve().parents[1] / "saves"
EXT = ".world"
AUTOSAVE_SLOT = "autosave"


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def slot_path(name: str, saves_dir: Path | str = SAVES_DIR) -> Path:
    return Path(saves_dir) / (f"{name}{EXT}")


def autosave_path(saves_dir: Path | str = SAVES_DIR) -> Path:
    return slot_path(AUTOSAVE_SLOT, saves_dir)


def has_autosave(saves_dir: Path | str = SAVES_DIR) -> bool:
    return autosave_path(saves_dir).exists()


# --------------------------------------------------------------------------- #
# Save / load
# --------------------------------------------------------------------------- #

def summarize(world: World) -> dict[str, Any]:
    """The small meta envelope embedded in each save (and used by the browser)."""
    pf = world.portfolio
    po = world.price_of
    nw = pf.net_worth(po)
    start = world.config.starting_cash
    return {
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "saved_epoch": time.time(),
        "profile": world.config.profile,
        "seed": world.config.world_seed,
        "fee_level": getattr(world.config, "fee_level", "off"),
        "tick": world.market.tick_index,
        "starting_cash": start,
        "cash": pf.cash,
        "net_worth": nw,
        "return_pct": (nw / start - 1) * 100 if start else 0.0,
        "n_positions": len(pf.positions),
        "loan_balance": pf.loan_balance(),
    }


def save_game(world: World, path: Path | str, *, label: str | None = None) -> dict[str, Any]:
    """Serialise `world` to `path` atomically, embedding a meta summary. Returns the meta."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = world.to_dict()
    meta = summarize(world)
    if label:
        meta["label"] = label
    data["meta"] = meta
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_save_", suffix=EXT)
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
    return meta


def load_game(path: Path | str, universe=None) -> World:
    """Load a save (tolerates the extra meta key)."""
    return load_world(path, universe)


# --------------------------------------------------------------------------- #
# Browser
# --------------------------------------------------------------------------- #

@dataclass
class SaveInfo:
    name: str
    path: Path
    saved_at: str | None
    saved_epoch: float
    profile: str
    seed: int | None
    tick: int
    net_worth: float | None
    return_pct: float | None
    n_positions: int
    label: str | None = None
    is_autosave: bool = False
    corrupt: bool = False


def read_info(path: Path | str) -> SaveInfo:
    """Summarise one save file. Falls back gracefully for pre-meta saves and corrupt files."""
    path = Path(path)
    name = path.stem
    is_auto = name == AUTOSAVE_SLOT
    try:
        with path.open(encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        mtime = path.stat().st_mtime if path.exists() else 0.0
        return SaveInfo(name, path, None, mtime, "?", None, 0, None, None, 0,
                        is_autosave=is_auto, corrupt=True)
    meta = d.get("meta") or {}
    cfg = d.get("config", {}) or {}
    mkt = d.get("market", {}) or {}
    pf = d.get("portfolio", {}) or {}
    nw = meta.get("net_worth")
    if nw is None:                                   # pre-meta save: derive net worth
        hist = pf.get("nw_history") or []
        if hist:
            nw = hist[-1][1]                         # last equity sample, if any
        else:                                        # else compute straight from the blob
            try:
                prices = mkt.get("prices", {}) or {}
                positions = pf.get("positions", {}) or {}
                cash = pf.get("cash", 0.0)
                holdings = sum(pos["quantity"] * prices.get(aid, 0.0)
                               for aid, pos in positions.items())
                loans = sum(l.get("balance", 0.0) for l in pf.get("loans", []) or [])
                nw = cash + holdings - loans
            except Exception:
                nw = None
    start = meta.get("starting_cash", cfg.get("starting_cash"))
    ret = meta.get("return_pct")
    if ret is None and nw is not None and start:
        ret = (nw / start - 1) * 100
    return SaveInfo(
        name=name,
        path=path,
        saved_at=meta.get("saved_at"),
        saved_epoch=float(meta.get("saved_epoch", path.stat().st_mtime)),
        profile=meta.get("profile", cfg.get("profile", "?")),
        seed=meta.get("seed", cfg.get("world_seed")),
        tick=int(meta.get("tick", mkt.get("tick_index", 0))),
        net_worth=nw,
        return_pct=ret,
        n_positions=int(meta.get("n_positions", len(pf.get("positions", {}) or {}))),
        label=meta.get("label"),
        is_autosave=is_auto,
    )


def list_saves(saves_dir: Path | str = SAVES_DIR, *, include_autosave: bool = True) -> list[SaveInfo]:
    """All saves in `saves_dir`, newest first."""
    d = Path(saves_dir)
    if not d.exists():
        return []
    infos = []
    for p in sorted(d.glob(f"*{EXT}")):
        if not include_autosave and p.stem == AUTOSAVE_SLOT:
            continue
        infos.append(read_info(p))
    infos.sort(key=lambda i: i.saved_epoch, reverse=True)
    return infos


def delete_save(name_or_path: str | Path, saves_dir: Path | str = SAVES_DIR) -> bool:
    """Delete a slot. Returns True if the file is gone afterwards."""
    p = name_or_path if isinstance(name_or_path, Path) else slot_path(str(name_or_path), saves_dir)
    p = Path(p)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            return False
    return not p.exists()
