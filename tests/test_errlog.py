"""Tests for the silent error-logging shim (trader_pro/errlog.py). No Qt needed."""
import logging

import pytest

from trader_pro import errlog


def _flush():
    for h in logging.getLogger("trader_pro").handlers:
        h.flush()


def test_guard_passes_through_success():
    @errlog.guard
    def add(a, b):
        return a + b

    assert add(2, 3) == 5                       # happy path is untouched


def test_guard_swallows_and_returns_default_and_logs(tmp_path):
    path = errlog.setup_logging(tmp_path / "err.log", install_hooks=False)
    ran = []

    @errlog.guard(default=-1, context="unit-guard")
    def boom(x):
        ran.append(x)
        raise ValueError("kaboom-guard")

    result = boom(7)
    assert result == -1                         # exception swallowed -> default returned
    assert ran == [7]                           # the body actually executed
    _flush()
    text = path.read_text(encoding="utf-8")
    assert "kaboom-guard" in text or "ValueError" in text   # the error was described
    assert "unit-guard" in text                             # under our context tag


def test_guard_reraises_keyboardinterrupt():
    @errlog.guard
    def stop():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):      # control-flow signals still propagate
        stop()


def test_guard_never_raises_even_if_handler_missing(monkeypatch):
    # Simulate the vendored handler being unavailable: the hand-rolled fallback must still swallow.
    monkeypatch.setattr(errlog, "_eh", None)

    @errlog.guard(default="fallback")
    def boom():
        raise RuntimeError("no handler here")

    assert boom() == "fallback"


def test_setup_logging_is_idempotent(tmp_path):
    path = tmp_path / "e.log"
    errlog.setup_logging(path, install_hooks=False)
    before = len(logging.getLogger("trader_pro").handlers)
    errlog.setup_logging(path, install_hooks=False)
    after = len(logging.getLogger("trader_pro").handlers)
    assert before == after                      # no duplicate file handler on the second call


def test_log_error_is_silent_on_broken_exception(tmp_path):
    path = errlog.setup_logging(tmp_path / "broken.log", install_hooks=False)

    class Nasty(Exception):
        def __str__(self):
            raise RuntimeError("repr blows up")

    errlog.log_error(Nasty(), context="nasty")  # must not raise despite the hostile __str__
    _flush()
    assert path.exists()
