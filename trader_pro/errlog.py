"""Silent error logging for the Trader PRO GUI.

Wraps the vendored `_errhandler` (a frozen copy of Matthew's sibling *Python ErrorHandler*
project) into the two things the front-end needs:

    setup_logging()      # route captured reports to a rotating file, once, at startup
    @guard               # decorate a Qt slot: on error, log a full report and DON'T raise

Design contract, inherited from error_handler: nothing here raises out of `guard`. If the
vendored handler is missing or itself explodes, `guard` still swallows the exception and logs a
primitive fallback line — so a bug in a slot can never crash the app, and a bug in the *logger*
can never crash a slot either. That is the whole point: "silently log errors and never raise."

Everything is funnelled through the stdlib `logging` module (logger name ``trader_pro``) so the
file sink, the global uncaught-exception hooks, and the per-slot guard all land in one place.
"""
from __future__ import annotations

import functools
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Any, Callable, Optional

from ._paths import user_data_dir

log = logging.getLogger("trader_pro")

# A library's logger must be inert until an application configures it. Without a handler,
# `log.error(...)` falls through to logging's *handler of last resort*, which prints the whole
# report to stderr — and in the TUI that lands on top of a full-screen terminal app, in the exe
# it pops a console. The NullHandler is what makes "silent" true even before setup_logging().
log.addHandler(logging.NullHandler())

try:                                       # the vendored handler is stdlib-only; this shouldn't fail
    from . import _errhandler as _eh
except Exception:                          # ...but if it ever does, degrade instead of hard-failing
    _eh = None


# ---------------------------------------------------------------------------
# Report rendering — the one place that reaches into the vendored handler.
# ---------------------------------------------------------------------------

def _report_text(exc: BaseException) -> str:
    """A full description of `exc` via the vendored handler, or a primitive fallback if it is
    unavailable or fails. Never raises."""
    if _eh is not None:
        try:
            return str(_eh.describe_error(exc))     # __str__ == concise .to_string()
        except Exception:
            pass
    try:
        return f"{type(exc).__name__}: {exc}"
    except Exception:
        return "<unrenderable exception>"


def log_error(exc: BaseException, context: str = "") -> None:
    """Log a captured exception silently to the ``trader_pro`` logger. Never raises."""
    try:
        head = f"[{context}] " if context else ""
        log.error("%s%s", head, _report_text(exc))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# File sink + global hooks
# ---------------------------------------------------------------------------

class _LogStream:
    """A minimal file-like that pipes error_handler.install()'s output into our logger, so the
    global uncaught-exception hooks share the same sink as everything else."""

    def write(self, s: str) -> int:
        try:
            s = s.rstrip("\n")
            if s:
                log.error("%s", s)
        except Exception:
            pass
        return len(s) if isinstance(s, str) else 0

    def flush(self) -> None:
        pass


def install_global_hooks() -> bool:
    """Wire the vendored handler's global hooks (sys.excepthook / threading / unraisable) to log
    through us. Returns True if wired, False if the handler is unavailable. Never raises."""
    if _eh is None:
        return False
    try:
        _eh.install(hooks=("excepthook", "threading", "unraisable"),
                    style="concise", stream=_LogStream())
        return True
    except Exception:
        return False


def setup_logging(path: Optional[os.PathLike | str] = None, *, level: int = logging.ERROR,
                  install_hooks: bool = True) -> Path:
    """Send ``trader_pro`` logger output to a rotating file (default ``<repo>/logs/trader_pro.log``)
    and, unless told otherwise, wire the global uncaught-exception hooks. Idempotent: calling it
    twice will not double-add the file handler. Returns the log-file path. Never raises."""
    try:
        if path is None:
            path = user_data_dir() / "logs" / "trader_pro.log"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tag = str(path)
        if not any(getattr(h, "_trader_pro_file", None) == tag for h in log.handlers):
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            handler._trader_pro_file = tag          # marker so we don't add it twice
            log.addHandler(handler)
        log.setLevel(level)
        log.propagate = False                       # our sink is the file, not the root logger
        if install_hooks:
            install_global_hooks()
        return path
    except Exception:
        # Even setup must not crash the app; fall back to a path object without a handler.
        return Path(path) if path is not None else Path("trader_pro.log")


# ---------------------------------------------------------------------------
# The per-slot guard
# ---------------------------------------------------------------------------

def guard(fn: Optional[Callable] = None, *, context: str = "", default: Any = None):
    """Decorator for a callable (typically a Qt slot) that must never let an exception escape.
    On error it logs a full report and returns ``default`` instead of raising.

        @guard
        def open_trade(self): ...

        @guard(context="timer tick")
        def _on_timer(self): ...

    KeyboardInterrupt / SystemExit pass through unreported, matching error_handler.capture."""
    if fn is None:
        return functools.partial(guard, context=context, default=default)

    label = context or getattr(fn, "__name__", "")

    # Prefer the vendored capture() — the real integration path — when available.
    if _eh is not None:
        try:
            sink = functools.partial(_sink, label)
            return _eh.capture(fn, reraise=False, default=default, on_report=sink)
        except Exception:
            pass                                    # fall through to the hand-rolled guard

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:                # noqa: BLE001 — swallowing is the contract
            log_error(exc, label)
            return default

    return wrapper


def _sink(context: str, report: Any) -> None:
    """on_report callback for the vendored capture(): log the report under our context tag."""
    try:
        log.error("[%s] %s", context, report)       # str(report) == concise .to_string()
    except Exception:
        pass
