"""Unit tests for the V1.7 persistence layer: enriched atomic saves + the slot browser API."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import load_seed_universe, World, MarketEngine, save_world  # noqa: E402
import trader_pro.persistence as P  # noqa: E402


U = load_seed_universe()


def _world(seed=7, cash=5000.0, days=0):
    w = World.new(U, seed, profile="Normal", starting_cash=cash)
    if days:
        MarketEngine(w).advance(days * 1440)
    return w


def test_save_embeds_meta_and_roundtrips(tmp_path: Path) -> None:
    w = _world(days=3)
    nw = w.portfolio.net_worth(w.price_of)
    meta = P.save_game(w, P.slot_path("run", tmp_path), label="run")
    # meta is embedded in the file
    d = json.loads((tmp_path / "run.world").read_text())
    assert d["meta"]["label"] == "run"
    assert abs(d["meta"]["net_worth"] - nw) < 1e-6
    assert d["meta"]["tick"] == 3 * 1440
    # atomic write leaves no temp turds
    assert not list(tmp_path.glob(".tmp*"))
    # load restores the same net worth
    w2 = P.load_game(P.slot_path("run", tmp_path), U)
    assert abs(w2.portfolio.net_worth(w2.price_of) - nw) < 1.0


def test_list_saves_newest_first(tmp_path: Path) -> None:
    P.save_game(_world(seed=1), P.slot_path("first", tmp_path), label="first")
    time.sleep(0.02)
    P.save_game(_world(seed=2), P.slot_path("second", tmp_path), label="second")
    infos = P.list_saves(tmp_path)
    assert [i.name for i in infos] == ["second", "first"]
    assert all(i.net_worth is not None and i.profile == "Normal" for i in infos)


def test_read_info_handles_pre_meta_save(tmp_path: Path) -> None:
    # a save written by the core helper has no "meta" envelope
    w = _world(seed=5, days=1)
    save_world(w, tmp_path / "old.world")
    info = P.read_info(tmp_path / "old.world")
    assert not info.corrupt
    assert info.profile == "Normal"
    assert info.seed == 5
    assert info.tick == 1440
    # net worth derived from the last nw_history sample
    assert info.net_worth is not None


def test_read_info_handles_corrupt(tmp_path: Path) -> None:
    (tmp_path / "bad.world").write_text("{ this is not json")
    info = P.read_info(tmp_path / "bad.world")
    assert info.corrupt and info.name == "bad"


def test_delete_save(tmp_path: Path) -> None:
    P.save_game(_world(), P.slot_path("doomed", tmp_path), label="doomed")
    assert (tmp_path / "doomed.world").exists()
    assert P.delete_save("doomed", tmp_path)
    assert not (tmp_path / "doomed.world").exists()
    assert P.list_saves(tmp_path) == []


def test_autosave_helpers(tmp_path: Path) -> None:
    assert not P.has_autosave(tmp_path)
    P.save_game(_world(), P.autosave_path(tmp_path), label=P.AUTOSAVE_SLOT)
    assert P.has_autosave(tmp_path)
    info = P.read_info(P.autosave_path(tmp_path))
    assert info.is_autosave


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp())
    for fn in (test_save_embeds_meta_and_roundtrips, test_list_saves_newest_first,
               test_read_info_handles_pre_meta_save, test_read_info_handles_corrupt,
               test_delete_save, test_autosave_helpers):
        fn(Path(tempfile.mkdtemp()))
        print("ok ", fn.__name__)
    print("all persistence tests passed")
