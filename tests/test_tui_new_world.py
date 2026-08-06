"""The TUI's Ctrl+N new-world modal (P16): difficulty and fees are dropdowns, not text boxes.

The old screen made you *type* a profile name that wasn't even listed on screen, and a typo
silently kept your previous profile — you'd start a world that wasn't the one you asked for. These
tests pin the replacement: the dropdowns exist and are pre-selected, arrowing through difficulty
updates the tagline, Enter starts from any field (dropdowns included), and the world that comes
back really is the one that was picked.

Driven through Textual's pilot (the real runtime), matching the other TUI tests.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import Input, Static  # noqa: E402
from trader_pro.tui import NewWorldScreen, NewWorldSelect, TraderTUI  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import PROFILE_NAMES, World, get_profile, load_seed_universe  # noqa: E402
from trader_pro.core.orders import FEE_LEVELS, FEE_RATES  # noqa: E402

U = load_seed_universe()


def _tagline(screen) -> str:
    """The tagline line's text — Static.renderable is a rich Text, not a plain str."""
    r = screen.query_one("#nw-tagline", Static).renderable
    return getattr(r, "plain", str(r))


def _app() -> TraderTUI:
    return TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=5_000.0), universe=U))


# --------------------------------------------------------------------------- #
# option builders (pure — no runtime needed)
# --------------------------------------------------------------------------- #

def test_profile_options_cover_every_profile_and_stay_short() -> None:
    opts = NewWorldScreen._profile_options()
    assert [value for _, value in opts] == list(PROFILE_NAMES)      # all 8, in scale order
    for label, value in opts:
        assert label == f"{get_profile(value).level}. {value}"
        # the modal is 70 cols wide; labels must not wrap, taglines live on their own line
        assert len(label) <= 20, label


def test_fee_options_show_the_actual_rate() -> None:
    opts = NewWorldScreen._fee_options()
    assert [value for _, value in opts] == list(FEE_LEVELS)
    label, value = opts[FEE_LEVELS.index("medium")]
    assert value == "medium"
    assert f"{FEE_RATES['medium'] * 100:.2f}%" in label


def test_tagline_lookup_is_defensive() -> None:
    assert NewWorldScreen._tagline_for("Normal") == get_profile("Normal").tagline
    assert NewWorldScreen._tagline_for("Nomal") == ""       # a typo can't raise, it just says less


# --------------------------------------------------------------------------- #
# the modal, driven through the pilot
# --------------------------------------------------------------------------- #

async def _scenario() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        before_seed = app.trader.world.config.world_seed

        # --- opens pre-selected on the current game's settings, focus on difficulty ---
        await pilot.press("ctrl+n")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, NewWorldScreen)
        profile_sel = screen.query_one("#nw-profile", NewWorldSelect)
        fee_sel = screen.query_one("#nw-fees", NewWorldSelect)
        assert profile_sel.value == "Normal"                  # matches the running world
        assert fee_sel.value == "off"
        assert app.focused is profile_sel                     # the choice that matters is focused
        assert _tagline(screen) == get_profile("Normal").tagline

        # --- there is no free-text difficulty field left to mistype ---
        input_ids = {i.id for i in screen.query(Input)}
        assert input_ids == {"nw-seed", "nw-cash"}

        # --- picking a difficulty updates the tagline live ---
        profile_sel.value = "Apocalyptic"
        await pilot.pause()
        assert _tagline(screen) == get_profile("Apocalyptic").tagline

        # --- Enter starts, even with a dropdown focused (its own binding is rebound) ---
        fee_sel.value = "greedy"
        screen.query_one("#nw-seed", Input).value = "4242"
        await pilot.pause()
        profile_sel.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        cfg = app.trader.world.config
        assert cfg.profile == "Apocalyptic"                   # the picked world is the one we got
        assert cfg.fee_level == "greedy"
        assert cfg.world_seed == 4242 != before_seed
        assert len(app.screen_stack) == 1                     # modal closed behind us

        # --- ↑ ↓ still open the dropdown rather than starting ---
        await pilot.press("ctrl+n")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#nw-profile", NewWorldSelect).focus()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert screen.query_one("#nw-profile", NewWorldSelect).expanded
        assert len(app.screen_stack) == 2                     # still on the modal, nothing started

        # --- Esc closes the open dropdown first, then cancels the modal ---
        await pilot.press("escape")
        await pilot.pause()
        assert not screen.query_one("#nw-profile", NewWorldSelect).expanded
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.trader.world.config.profile == "Apocalyptic"   # cancel changed nothing


def test_tui_new_world_modal() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_profile_options_cover_every_profile_and_stay_short()
    test_fee_options_show_the_actual_rate()
    test_tagline_lookup_is_defensive()
    test_tui_new_world_modal()
    print("all new-world tests passed")
