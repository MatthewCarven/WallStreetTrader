"""The TUI's Textual-version guard: < 0.72 is supported; >= 0.72 freezes the trade dialog
on teardown (docs/freeze-bug/README.md), so run_tui() must refuse and explain."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import textual  # noqa: E402
from trader_pro import tui  # noqa: E402


def test_guard_accepts_installed_textual() -> None:
    ok, ver = tui.textual_version_ok()
    assert ver == textual.__version__
    assert ok is True                     # the sandbox/CI pins 0.71.x


def test_guard_flags_versions(monkeypatch) -> None:
    cases = {
        "0.50.1": True, "0.71.0": True, "0.71.9": True,
        "0.72.0": False, "0.73.0": False, "0.72.0rc1": False,
        "1.0.0": False, "2.5.3": False,
    }
    for ver, expected in cases.items():
        monkeypatch.setattr(textual, "__version__", ver)
        ok, reported = tui.textual_version_ok()
        assert reported == ver
        assert ok is expected, f"{ver} -> {ok}, expected {expected}"


def test_run_tui_refuses_new_textual(monkeypatch, capsys) -> None:
    monkeypatch.setattr(textual, "__version__", "0.99.0")
    # must return without launching, and tell the user how to fix it
    tui.run_tui()
    out = capsys.readouterr().out
    assert "textual<0.72" in out and "0.99.0" in out


def test_run_tui_configures_the_error_log_first(monkeypatch, capsys) -> None:
    """The TUI was the one front-end that never called setup_logging, so anything it logged went
    nowhere useful. Since P3's resume path logs an unreadable autosave generation, wire the sink
    up before anything that can fail — the version guard is a convenient early exit to observe
    it from, and patching setup_logging keeps the test off the real logs/ directory."""
    calls = []
    monkeypatch.setattr(tui, "setup_logging", lambda **kw: calls.append(kw))
    monkeypatch.setattr(textual, "__version__", "0.99.0")
    tui.run_tui()
    capsys.readouterr()
    assert calls == [{"install_hooks": False}]   # hooks off: they'd fight Textual's own handling


if __name__ == "__main__":
    test_guard_accepts_installed_textual()
    print("ok  test_guard_accepts_installed_textual")
    print("guard tests need pytest for monkeypatch; run via pytest for the rest")
