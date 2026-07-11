"""PySide6 desktop front-end for Trader PRO — Slice 0: the shell & lifecycle.

    python play_gui.py        # or:  python -m trader_pro.gui

A third front-end (alongside the CLI and Textual TUI) over the same UI-agnostic core. Like the
TUI it wraps a `TraderApp` and drives it with a live clock; unlike the TUI it renders with Qt.

Slice 0 establishes: the main window, the dashboard header, the live tick loop (play/pause at
1 sim-minute per real second, frame-rate independent), and the resume/autosave lifecycle. The
board, charts, positions, news and trading dialogs arrive in later slices. Requires PySide6.
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from ..cli import TraderApp, fmt_clock, money
from ..core.engine import DAY, HOUR
from ..persistence import AUTOSAVE_SLOT, autosave_path, save_game
from .model import (
    AMBER, AUTOSAVE_SECS, BG, DIM, FG, GREEN, GREEN_HI, PANEL, SPEEDS, TIMER_MS,
    boot, header_html, steps_for,
)


class TraderGUI(QMainWindow):
    """The main window: header + controls now, panels later. Holds a `TraderApp` and advances it
    on a QTimer, exactly as the TUI's `TraderTUI` does with `set_interval`/`_on_timer`."""

    def __init__(self, trader: TraderApp, resumed: bool = False):
        super().__init__()
        self.trader = trader
        self.resumed = resumed
        self.playing = False
        self.speed_idx = 0                      # default: 1 sim-minute per real second
        self.autosave_enabled = True
        self._play_clock: float | None = None   # monotonic ts of last advance; None while paused
        self._tick_accum = 0.0                   # carries fractional sim-minutes across timer ticks
        self._last_autosave = time.monotonic()

        self.setWindowTitle("TRADER PRO")
        self.resize(1120, 720)
        self._build_ui()
        self._refresh_header()

        self._timer = QTimer(self)
        self._timer.setInterval(TIMER_MS)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start()

    # ---- layout ---- #

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(12)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(11)

        self.header_label = QLabel()
        self.header_label.setTextFormat(Qt.RichText)
        self.header_label.setFont(mono)
        root.addWidget(self.header_label)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setShortcut("Space")
        self.play_btn.setToolTip("Play / pause  (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_btn)

        self.slower_btn = QPushButton("«")
        self.slower_btn.setShortcut(QKeySequence("["))
        self.slower_btn.setToolTip("Slower  ( [ )")
        self.slower_btn.clicked.connect(self.slower)
        controls.addWidget(self.slower_btn)

        self.speed_label = QLabel(SPEEDS[self.speed_idx][0])
        self.speed_label.setFont(mono)
        self.speed_label.setAlignment(Qt.AlignCenter)
        self.speed_label.setMinimumWidth(88)
        controls.addWidget(self.speed_label)

        self.faster_btn = QPushButton("»")
        self.faster_btn.setShortcut(QKeySequence("]"))
        self.faster_btn.setToolTip("Faster  ( ] )")
        self.faster_btn.clicked.connect(self.faster)
        controls.addWidget(self.faster_btn)

        controls.addSpacing(18)
        self.step_btn = QPushButton("Step")
        self.step_btn.setShortcut("s")
        self.step_btn.setToolTip("Advance 1 minute  (s)")
        self.step_btn.clicked.connect(self.step_minute)
        controls.addWidget(self.step_btn)
        self.hour_btn = QPushButton("+1h")
        self.hour_btn.setShortcut("h")
        self.hour_btn.setToolTip("Advance 1 hour  (h)")
        self.hour_btn.clicked.connect(self.step_hour)
        controls.addWidget(self.hour_btn)
        self.day_btn = QPushButton("+1d")
        self.day_btn.setShortcut("d")
        self.day_btn.setToolTip("Advance 1 day  (d)")
        self.day_btn.clicked.connect(self.step_day)
        controls.addWidget(self.day_btn)

        controls.addStretch(1)
        self.state_label = QLabel("paused")
        self.state_label.setFont(mono)
        controls.addWidget(self.state_label)
        root.addLayout(controls)

        placeholder = QLabel(
            "Slice 0 shell — live clock, header, play/pause, autosave.\n\n"
            "Market board, charts, positions, news and trading arrive in the next slices."
        )
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet(f"color: {DIM};")
        root.addWidget(placeholder, 1)

        self.setCentralWidget(central)
        self._apply_theme()
        self.statusBar().showMessage(self._welcome_text())

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"QMainWindow {{ background: {BG}; }}"
            f"QWidget {{ background: {BG}; color: {FG}; }}"
            f"QLabel {{ color: {FG}; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {GREEN};"
            f" padding: 5px 16px; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 1px solid {GREEN_HI}; }}"
            f"QStatusBar {{ color: {AMBER}; }}"
        )

    def _welcome_text(self) -> str:
        if self.resumed:
            w = self.trader.world
            nw = w.portfolio.net_worth(w.price_of)
            ret = (nw / w.config.starting_cash - 1) * 100
            return (f"Resumed your last game · {fmt_clock(w.market.tick_index)} · "
                    f"net worth {money(nw)} ({ret:+.1f}%)")
        return "New world · press Space (or Play) to run at 1 sim-minute per real second"

    # ---- live clock ---- #

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self._play_clock = None                 # reset baseline so toggling can't bank/jump time
        if self.playing:
            self.play_btn.setText("⏸  Pause")
            self.state_label.setText(f"playing · {SPEEDS[self.speed_idx][0]}")
        else:
            self.play_btn.setText("▶  Play")
            self.state_label.setText("paused")

    def faster(self) -> None:
        self.speed_idx = min(len(SPEEDS) - 1, self.speed_idx + 1)
        self._update_speed()

    def slower(self) -> None:
        self.speed_idx = max(0, self.speed_idx - 1)
        self._update_speed()

    def _update_speed(self) -> None:
        label = SPEEDS[self.speed_idx][0]
        self.speed_label.setText(label)
        if self.playing:
            self.state_label.setText(f"playing · {label}")

    def step_minute(self) -> None:
        self._advance_now(1)

    def step_hour(self) -> None:
        self._advance_now(HOUR)

    def step_day(self) -> None:
        self._advance_now(DAY)

    def _advance_now(self, ticks: int) -> None:
        """A discrete manual advance (Step / +1h / +1d) — jumps the market immediately, whether
        playing or paused, and never banks against the play clock. Mirrors the TUI's
        action_step/hour/day. Cheap even for +1d: the engine evaluates seeded anchors directly."""
        self.trader._advance(ticks)             # events/closures surface in the news slice (8)
        self._refresh_header()

    def _on_timer(self) -> None:
        if not self.playing:
            self._play_clock = None
            return
        now = time.monotonic()
        if self._play_clock is None:            # just (re)started playing — set baseline, no jump
            self._play_clock = now
            self._tick_accum = 0.0
            return
        elapsed = now - self._play_clock
        self._play_clock = now
        steps, self._tick_accum = steps_for(elapsed, SPEEDS[self.speed_idx][1], self._tick_accum)
        if steps <= 0:                          # not a whole sim-minute yet; wait for more time
            return
        self.trader._advance(steps)             # events/closures surface in the news slice (8)
        self._refresh_header()
        if self.autosave_enabled and now - self._last_autosave >= AUTOSAVE_SECS:
            self._autosave()
            self._last_autosave = now

    def _refresh_header(self) -> None:
        self.header_label.setText(header_html(self.trader.world))

    # ---- persistence ---- #

    def _autosave(self) -> None:
        try:
            save_game(self.trader.world, autosave_path(), label=AUTOSAVE_SLOT)
        except Exception:
            pass                                # autosave is best-effort, exactly like the TUI

    def closeEvent(self, event) -> None:        # noqa: N802 — Qt override name
        if self.autosave_enabled:
            self._autosave()
        super().closeEvent(event)


def run_gui() -> None:
    """Boot a world (resume last autosave or start fresh) and open the window — mirrors run_tui()."""
    trader, resumed = boot()
    app = QApplication.instance() or QApplication(sys.argv)
    window = TraderGUI(trader, resumed=resumed)
    window.show()
    app.exec()
