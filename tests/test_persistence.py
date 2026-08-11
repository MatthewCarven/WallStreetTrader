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


# --------------------------------------------------------------------------- #
# P3 — autosave generations
# --------------------------------------------------------------------------- #

def _autosave_ticks(tmp_path: Path) -> list[int]:
    """The clock of each generation, newest first — `[gen0, .1, .2]`, missing ones as None."""
    return [P.read_info(p).tick if p.exists() else None for p in P.autosave_paths(tmp_path)]


def test_autosave_rotates_generations(tmp_path: Path) -> None:
    w = _world()
    eng = MarketEngine(w)
    ticks = []
    for _ in range(3):
        eng.advance(1440)
        ticks.append(w.market.tick_index)
        P.save_autosave(w, tmp_path)
    # gen 0 is the newest write; .1 and .2 are the two before it, in order
    assert _autosave_ticks(tmp_path) == ticks[::-1]


def test_autosave_chain_caps_and_drops_the_oldest(tmp_path: Path) -> None:
    w = _world()
    eng = MarketEngine(w)
    for _ in range(6):
        eng.advance(1440)
        P.save_autosave(w, tmp_path)
    assert sorted(p.name for p in tmp_path.glob(f"*{P.EXT}")) == [
        "autosave.1.world", "autosave.2.world", "autosave.world"]
    # the survivors are the three most *recent* saves, not the first three
    assert _autosave_ticks(tmp_path) == [6 * 1440, 5 * 1440, 4 * 1440]


def test_rotation_ages_out_a_stale_generation_across_a_hole(tmp_path: Path) -> None:
    """Renaming alone only overwrites the generation *below* an existing one. If the chain has a
    hole — a backup deleted by hand, or a rename that failed — the tail would never age out and
    resume could fall all the way back to a save from an hour ago. Dropping the oldest first is
    what stops that."""
    w = _world()
    eng = MarketEngine(w)
    for _ in range(3):
        eng.advance(1440)
        P.save_autosave(w, tmp_path)
    P.autosave_path(tmp_path, 1).unlink()              # punch a hole in the middle
    eng.advance(1440)
    P.save_autosave(w, tmp_path)

    assert _autosave_ticks(tmp_path) == [4 * 1440, 3 * 1440, None]   # the day-1 save is gone


def test_resume_falls_back_when_the_newest_is_corrupt(tmp_path: Path) -> None:
    """The headline of P3: a torn gen 0 costs you the last autosave interval, not the game."""
    w = _world()
    eng = MarketEngine(w)
    eng.advance(1440)
    P.save_autosave(w, tmp_path)                       # ends up as .1
    eng.advance(1440)
    P.save_autosave(w, tmp_path)                       # gen 0
    P.autosave_path(tmp_path).write_text("{ half a save file")   # a write cut off by a power cut

    world, src = P.load_autosave(tmp_path, U)
    assert src == P.autosave_path(tmp_path, 1)
    assert world.market.tick_index == 1440             # the *older* generation, intact
    assert world.config.world_seed == 7
    assert world.portfolio.net_worth(world.price_of) > 0


def test_resume_walks_past_two_corrupt_generations(tmp_path: Path) -> None:
    w = _world()
    eng = MarketEngine(w)
    for _ in range(3):
        eng.advance(1440)
        P.save_autosave(w, tmp_path)
    P.autosave_path(tmp_path, 0).write_text("")        # empty file: not even valid JSON
    P.autosave_path(tmp_path, 1).write_text('{"config": {}}')   # valid JSON, wrong shape

    world, src = P.load_autosave(tmp_path, U)
    assert src == P.autosave_path(tmp_path, 2)
    assert world.market.tick_index == 1440


def test_load_autosave_raises_when_the_whole_chain_is_unusable(tmp_path: Path) -> None:
    for p in P.autosave_paths(tmp_path):
        p.write_text("not a save")
    try:
        P.load_autosave(tmp_path, U)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("an unreadable chain must not pretend to resume")


def test_has_autosave_sees_a_backup_only_chain(tmp_path: Path) -> None:
    """Rotation renames *before* it writes, so a crash in that window leaves .1 and no gen 0.
    That is still a resumable game and resume must find it."""
    P.save_autosave(_world(days=2), tmp_path)
    P.rotate_autosaves(tmp_path)                       # died here, before the write
    assert not P.autosave_path(tmp_path).exists()
    assert P.has_autosave(tmp_path)
    world, src = P.load_autosave(tmp_path, U)
    assert src == P.autosave_path(tmp_path, 1)
    assert world.market.tick_index == 2 * 1440


def test_backups_stay_out_of_the_slot_browser(tmp_path: Path) -> None:
    w = _world()
    eng = MarketEngine(w)
    for _ in range(3):
        eng.advance(60)
        P.save_autosave(w, tmp_path)
    P.save_game(_world(seed=2), P.slot_path("manual", tmp_path), label="manual")

    assert sorted(i.name for i in P.list_saves(tmp_path)) == ["autosave", "manual"]
    assert [i.name for i in P.list_saves(tmp_path, include_autosave=False)] == ["manual"]
    # ...but asked about one directly, read_info still calls a backup an autosave
    assert P.read_info(P.autosave_path(tmp_path, 1)).is_autosave
    assert P.is_autosave_backup(P.autosave_path(tmp_path, 1))
    assert not P.is_autosave_backup(P.autosave_path(tmp_path))


def test_deleting_the_autosave_takes_its_generations_with_it(tmp_path: Path) -> None:
    """Otherwise the next launch resumes from .1 and the slot you just deleted comes back."""
    w = _world()
    eng = MarketEngine(w)
    for _ in range(3):
        eng.advance(60)
        P.save_autosave(w, tmp_path)
    assert P.delete_save(P.AUTOSAVE_SLOT, tmp_path)
    assert not P.has_autosave(tmp_path)
    assert list(tmp_path.glob(f"*{P.EXT}")) == []


def test_autosave_path_rejects_a_generation_off_the_chain(tmp_path: Path) -> None:
    for bad in (-1, P.AUTOSAVE_GENERATIONS + 1):
        try:
            P.autosave_path(tmp_path, bad)
        except ValueError:
            continue
        raise AssertionError(f"generation {bad} is off the chain and should not resolve")


def test_paths_resolve_to_repo_root_from_source() -> None:
    # From source (not frozen), resources and writable state both live under the repo root, so the
    # PyInstaller frozen-path indirection is invisible in dev.
    from trader_pro._paths import resource_dir, user_data_dir, is_frozen
    assert not is_frozen()
    assert resource_dir() == ROOT and user_data_dir() == ROOT
    assert (resource_dir() / "data" / "seeds").exists()      # seeds where the loader looks
    assert P.SAVES_DIR == ROOT / "saves"


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp())
    for fn in (test_save_embeds_meta_and_roundtrips, test_list_saves_newest_first,
               test_read_info_handles_pre_meta_save, test_read_info_handles_corrupt,
               test_delete_save, test_autosave_helpers,
               test_autosave_rotates_generations, test_autosave_chain_caps_and_drops_the_oldest,
               test_rotation_ages_out_a_stale_generation_across_a_hole,
               test_resume_falls_back_when_the_newest_is_corrupt,
               test_resume_walks_past_two_corrupt_generations,
               test_load_autosave_raises_when_the_whole_chain_is_unusable,
               test_has_autosave_sees_a_backup_only_chain,
               test_backups_stay_out_of_the_slot_browser,
               test_deleting_the_autosave_takes_its_generations_with_it,
               test_autosave_path_rejects_a_generation_off_the_chain):
        fn(Path(tempfile.mkdtemp()))
        print("ok ", fn.__name__)
    print("all persistence tests passed")
