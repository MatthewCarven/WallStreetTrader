"""Game persistence (V1.7) — enriched, crash-safe save slots + a browser API.

Builds on the core `World.to_dict()` / `load_world()`. A save file is the world's JSON plus a
small ``"meta"`` envelope (net worth, return, clock, profile, timestamp) so the load browser can
summarise a slot *without* rebuilding the engine or recomputing prices. ``from_dict`` ignores the
extra key, so saves stay backward/forward compatible.

Writes are **atomic**: we write a temp file in the same directory and ``os.replace`` it into place,
so a crash mid-write can never corrupt an existing slot (this matters for the frequent autosave).

The autosave is additionally kept in **generations** (P3): every autosave rotates the previous one
down the chain ``autosave`` → ``autosave.1`` → ``autosave.2`` before writing, and resume walks that
chain newest-first until a file actually loads. Atomic writes stop a crash mid-write from eating a
save; generations are the second net, for the failures atomicity can't cover — a bad sector, a
half-synced file after a hard power cut, a world that was already wrong when we serialised it.
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
from ._paths import user_data_dir
from .errlog import log_error

# repo-root/saves  (this file is trader_pro/persistence.py)
SAVES_DIR = user_data_dir() / "saves"        # <repo>/saves from source; beside the .exe when frozen
EXT = ".world"
AUTOSAVE_SLOT = "autosave"
AUTOSAVE_GENERATIONS = 2                     # backups kept behind the live slot: .1 (newer), .2


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def slot_path(name: str, saves_dir: Path | str = SAVES_DIR) -> Path:
    return Path(saves_dir) / (f"{name}{EXT}")


def autosave_path(saves_dir: Path | str = SAVES_DIR, gen: int = 0) -> Path:
    """Path of one autosave generation. `gen` 0 is the live slot (``autosave.world``); 1..N are
    the backups behind it, oldest last (``autosave.1.world``, ``autosave.2.world``)."""
    if not 0 <= gen <= AUTOSAVE_GENERATIONS:
        raise ValueError(f"autosave generation out of range: {gen}")
    name = AUTOSAVE_SLOT if gen == 0 else f"{AUTOSAVE_SLOT}.{gen}"
    return slot_path(name, saves_dir)


def autosave_paths(saves_dir: Path | str = SAVES_DIR) -> list[Path]:
    """The whole autosave chain, newest first — the order resume tries them in."""
    return [autosave_path(saves_dir, g) for g in range(AUTOSAVE_GENERATIONS + 1)]


_BACKUP_STEMS = frozenset(f"{AUTOSAVE_SLOT}.{g}" for g in range(1, AUTOSAVE_GENERATIONS + 1))


def is_autosave_backup(path: Path | str) -> bool:
    """True for ``autosave.1.world`` / ``autosave.2.world`` — recovery generations, not slots."""
    return Path(path).stem in _BACKUP_STEMS


def has_autosave(saves_dir: Path | str = SAVES_DIR) -> bool:
    """True if *any* generation exists. Deliberately not just the live slot: a rotation
    interrupted between the rename and the write leaves gen 0 missing while `.1` survives, and
    that is still a perfectly resumable game."""
    return any(p.exists() for p in autosave_paths(saves_dir))


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
# Autosave generations (P3)
# --------------------------------------------------------------------------- #

def rotate_autosaves(saves_dir: Path | str = SAVES_DIR) -> None:
    """Shift the chain down one so gen 0 is free for a fresh write: the oldest backup is dropped,
    every surviving generation moves back, and the live slot becomes ``.1``.

    Renames, never copies — rotating a 25 KB save costs the same as rotating a 25 MB one, which
    is what makes this affordable on the 30-second autosave. Each step is best-effort: a
    generation that won't move (a backup open in another window on Windows, say) is skipped
    rather than aborting the autosave that follows it. Losing a backup is survivable; losing the
    save that was about to be written is not.
    """
    paths = autosave_paths(saves_dir)
    oldest = paths[-1]
    if oldest.exists():
        try:
            oldest.unlink()
        except OSError:
            pass
    for gen in range(AUTOSAVE_GENERATIONS, 0, -1):
        src, dst = paths[gen - 1], paths[gen]
        if src.exists():
            try:
                os.replace(src, dst)           # atomic, and overwrites dst on Windows too
            except OSError:
                pass


def save_autosave(world: World, saves_dir: Path | str = SAVES_DIR,
                  *, label: str = AUTOSAVE_SLOT) -> dict[str, Any]:
    """Rotate the generations, then write a fresh live autosave. Returns the meta.

    This — not ``save_game(world, autosave_path(...))`` — is what the front-ends call every 30 s
    and on the way out. Writing gen 0 directly still works, it just throws the safety net away.
    """
    rotate_autosaves(saves_dir)
    return save_game(world, autosave_path(saves_dir), label=label)


def load_autosave(saves_dir: Path | str = SAVES_DIR, universe=None) -> tuple[World, Path]:
    """Resume from the newest autosave generation that actually loads.

    The live slot is tried first; if it is missing, truncated, or unreadable for any other
    reason, we walk back through the backups. Returns the world *and* the path it came from, so
    the caller can tell the player when they landed on a backup instead of silently rewinding
    them 30 seconds. Raises ``FileNotFoundError`` when the whole chain is unusable — callers
    treat that exactly as they used to treat a failed load, and start a fresh world.
    """
    for p in autosave_paths(saves_dir):
        if not p.exists():
            continue
        try:
            return load_game(p, universe), p
        except Exception as exc:
            log_error(exc, f"autosave generation unreadable: {p.name}")
    raise FileNotFoundError(f"no readable autosave in {Path(saves_dir)}")


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
    is_auto = name == AUTOSAVE_SLOT or is_autosave_backup(path)
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
    """All saves in `saves_dir`, newest first.

    Autosave *backups* never appear: they're a crash-recovery chain that resume walks on its own,
    and listing three near-identical `autosave` rows 30 seconds apart would bury the real slots.
    """
    d = Path(saves_dir)
    if not d.exists():
        return []
    infos = []
    for p in sorted(d.glob(f"*{EXT}")):
        if is_autosave_backup(p):
            continue
        if not include_autosave and p.stem == AUTOSAVE_SLOT:
            continue
        infos.append(read_info(p))
    infos.sort(key=lambda i: i.saved_epoch, reverse=True)
    return infos


def delete_save(name_or_path: str | Path, saves_dir: Path | str = SAVES_DIR) -> bool:
    """Delete a slot. Returns True if the file is gone afterwards.

    Deleting the autosave takes its whole generation chain with it. Otherwise the next launch
    would resume from `.1` and the slot the player just deleted would appear to come back.
    """
    p = name_or_path if isinstance(name_or_path, Path) else slot_path(str(name_or_path), saves_dir)
    p = Path(p)
    targets = (autosave_paths(p.parent)
               if p.stem == AUTOSAVE_SLOT or is_autosave_backup(p)
               else [p])
    for t in targets:
        if t.exists():
            try:
                t.unlink()
            except OSError:
                return False
    return not any(t.exists() for t in targets)
