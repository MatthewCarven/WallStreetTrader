"""Headless tests for the V1.7 TUI persistence: Ctrl+S save modal, Ctrl+L slot browser
(load + delete), autosave-on-quit, and resume-on-launch."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import DataTable, Input  # noqa: E402
import trader_pro.persistence as P  # noqa: E402
from trader_pro.tui import TraderTUI, SaveScreen, LoadScreen  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402


U = load_seed_universe()


def _app(saves_dir: Path) -> TraderTUI:
    app = TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=10_000.0), universe=U))
    app.saves_dir = saves_dir
    return app


async def _scenario(tmp: Path) -> None:
    app = _app(tmp)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_day(); app.action_day()
        await pilot.pause()

        # Ctrl+S opens the save modal; the name is sanitised; the file appears
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SaveScreen)
        app.screen.query_one("#save-name", Input).value = "alpha run!!"
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert (tmp / "alpharun.world").exists()
        assert app.slot == "alpharun"

        # a second, later save
        app.action_day(); app.action_day()
        await pilot.pause()
        app._do_save("beta")
        await pilot.pause()

        # Ctrl+L browser: newest first; load the OLDER slot and verify the clock rewinds
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert isinstance(app.screen, LoadScreen)
        tbl = app.screen.query_one("#saves-tbl", DataTable)
        names = [tbl.coordinate_to_cell_key((r, 0)).row_key.value for r in range(tbl.row_count)]
        assert names[0] == "beta"            # newest first
        tbl.move_cursor(row=1)               # 'alpharun'
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.slot == "alpharun"
        assert app.trader.world.market.tick_index == 2 * 1440

        # delete a slot from the browser (x twice to confirm)
        await pilot.press("ctrl+l")
        await pilot.pause()
        sc = app.screen
        sc.query_one("#saves-tbl", DataTable).move_cursor(row=0)
        await pilot.pause()
        target = sc._cur
        await pilot.press("x")
        await pilot.pause()
        assert sc._pending_delete == target
        await pilot.press("x")
        await pilot.pause()
        assert not (tmp / f"{target}.world").exists()
        await pilot.press("escape")
        await pilot.pause()

        # autosave-on-quit writes the autosave slot
        app.action_day()
        await pilot.pause()
        app._autosave()
        assert P.has_autosave(tmp)


def test_tui_persistence() -> None:
    asyncio.run(_scenario(Path(tempfile.mkdtemp())))


async def _resume_scenario(tmp: Path) -> None:
    # write an autosave 5 days in, then launch a resumed app pointed at it
    seed_app = _app(tmp)
    for _ in range(5):
        seed_app.trader._advance(1440)
    P.save_game(seed_app.trader.world, P.autosave_path(tmp), label=P.AUTOSAVE_SLOT)

    world = P.load_game(P.autosave_path(tmp), U)
    app = TraderTUI(TraderApp(world, universe=U))
    app.saves_dir = tmp
    app.resumed = True
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # on_mount's resumed branch ran (it reads net worth etc.) without error,
        # and the resumed world is in place
        assert app.trader.world.market.tick_index == 5 * 1440
        assert app.resumed is True


def test_tui_resume() -> None:
    asyncio.run(_resume_scenario(Path(tempfile.mkdtemp())))


# ---- P3: autosave generations, from the front-end's side ---- #

async def _generations_scenario(tmp: Path) -> None:
    """The TUI's autosave must go *through* the rotation, not straight at gen 0 — otherwise the
    generations exist in persistence.py and never get written by the thing that autosaves."""
    app = _app(tmp)
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(3):
            app.action_day()
            await pilot.pause()
            app._autosave()
        assert P.autosave_path(tmp, 1).exists() and P.autosave_path(tmp, 2).exists()
        ticks = [P.read_info(p).tick for p in P.autosave_paths(tmp)]
        assert ticks == [3 * 1440, 2 * 1440, 1440]      # newest first, one day apart


def test_tui_autosave_writes_generations() -> None:
    asyncio.run(_generations_scenario(Path(tempfile.mkdtemp())))


async def _backup_resume_scenario(tmp: Path) -> None:
    """A torn gen 0 rewinds the player ~30 s; on_mount has to say so rather than let them
    wonder why their last few trades vanished."""
    seed = _app(tmp)
    seed.trader._advance(1440)
    P.save_autosave(seed.trader.world, tmp)             # becomes .1
    seed.trader._advance(1440)
    P.save_autosave(seed.trader.world, tmp)             # gen 0
    P.autosave_path(tmp).write_text("{ torn write")

    world, src = P.load_autosave(tmp, U)
    assert src == P.autosave_path(tmp, 1)

    app = TraderTUI(TraderApp(world, universe=U))
    app.saves_dir = tmp
    app.resumed = True
    app.resumed_from_backup = True
    logged: list[str] = []
    real_log = app._log
    app._log = lambda text: (logged.append(str(text)), real_log(text))[1]   # tap the news pane

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.trader.world.market.tick_index == 1440        # the older generation
        assert any("unreadable" in line for line in logged), logged
        assert any("backup" in line for line in logged), logged


def test_tui_resume_from_backup_warns() -> None:
    asyncio.run(_backup_resume_scenario(Path(tempfile.mkdtemp())))


if __name__ == "__main__":
    test_tui_persistence()
    print("ok  test_tui_persistence")
    test_tui_resume()
    print("ok  test_tui_resume")
    test_tui_autosave_writes_generations()
    print("ok  test_tui_autosave_writes_generations")
    test_tui_resume_from_backup_warns()
    print("ok  test_tui_resume_from_backup_warns")
    print("all tui-persistence tests passed")
