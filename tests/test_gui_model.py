"""Pure unit tests for the GUI's Qt-free helpers (no PySide6 needed)."""
from trader_pro.core import World, load_seed_universe
from trader_pro.gui.model import boot, header_html, steps_for


def test_steps_for_accumulates_fractional():
    s, acc = steps_for(0.3, 1, 0.0)
    assert s == 0 and abs(acc - 0.3) < 1e-9
    s, acc = steps_for(0.3, 1, acc)            # 0.6 banked
    assert s == 0
    s, acc = steps_for(0.5, 1, acc)            # crosses 1.0 -> one whole minute
    assert s == 1 and abs(acc - 0.1) < 1e-9


def test_steps_for_caps_a_single_stall():
    # a long stall at 1 tick/s still advances only one minute (elapsed clamped to 1.0s)
    s, _ = steps_for(100.0, 1, 0.0)
    assert s == 1


def test_steps_for_fast_speed():
    s, acc = steps_for(1.0, 60, 0.0)           # 1 hr/s
    assert s == 60 and abs(acc) < 1e-9


def test_header_html_has_key_fields():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    html = header_html(world)
    for token in ("TRADER PRO", "net worth", "buying power", "Normal", "sentiment"):
        assert token in html


def test_boot_returns_a_trader():
    trader, resumed = boot()
    assert trader.world is not None
    assert isinstance(resumed, bool)
