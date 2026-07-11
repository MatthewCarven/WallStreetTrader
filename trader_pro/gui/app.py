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

import pyqtgraph as pg
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from ..cli import TraderApp, fmt_clock, money
from ..core import AssetKind
from ..core.engine import DAY, HOUR
from ..persistence import AUTOSAVE_SLOT, autosave_path, save_game
from .model import (
    AMBER, AUTOSAVE_SECS, BG, BOARD_COLUMNS, CHART_RANGES, DIM, FG, GREEN, GREEN_HI, PANEL,
    RED, SPEEDS, TIMER_MS, asset_detail_html, boot, cell, default_watchlist, header_html,
    kind_ids, row_ctx, steps_for, visible_ids,
)


class BoardView(QTableView):
    """The board table. Type-ahead row search is disabled so single-letter shortcuts (0-4 views,
    `o` sort, `s`/`h`/`d` steps) reach their buttons instead of being swallowed as search keys."""

    def keyboardSearch(self, search: str) -> None:   # noqa: N802 — Qt override name
        pass


class BoardModel(QAbstractTableModel):
    """Feeds the market board's QTableView from the live world. Columns are BOARD_COLUMNS; each
    cell's text / colour / alignment / weight come from the pure `cell()` helper, so this model
    just maps them onto Qt roles. `refresh()` recomputes the row values in place and repaints
    without resetting (keeping selection); `set_aids()` swaps the whole list (a reset)."""

    def __init__(self, trader: TraderApp):
        super().__init__()
        self.trader = trader
        self.aids: list[str] = []
        self._rows: list = []

    def set_aids(self, aids) -> None:
        self.beginResetModel()
        self.aids = list(aids)
        self._recompute()
        self.endResetModel()

    def _recompute(self) -> None:
        w, eng = self.trader.world, self.trader.engine
        self._rows = [row_ctx(w, eng, aid) for aid in self.aids]

    def refresh(self) -> None:
        if not self.aids:
            return
        self._recompute()
        top = self.index(0, 0)
        bottom = self.index(self.rowCount() - 1, self.columnCount() - 1)
        self.dataChanged.emit(top, bottom, [Qt.DisplayRole, Qt.ForegroundRole])

    def aid_at(self, row: int) -> str | None:
        return self.aids[row] if 0 <= row < len(self.aids) else None

    # ---- Qt model interface ---- #

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(BOARD_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return BOARD_COLUMNS[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        c = cell(self._rows[index.row()], BOARD_COLUMNS[index.column()][0])
        if role == Qt.DisplayRole:
            return c.text
        if role == Qt.ForegroundRole:
            return QColor(c.color)
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if c.right else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.FontRole and c.bold:
            f = QFont()
            f.setBold(True)
            return f
        return None


class TraderGUI(QMainWindow):
    """The main window: header, time controls and the live market board; more panels (chart,
    positions, news) land in later slices. Holds a `TraderApp` and advances it on a QTimer,
    exactly as the TUI's `TraderTUI` does with `set_interval`/`_on_timer`."""

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

        # board view state (mirrors the TUI): which slice of the market, sort, paging, selection
        self.watch = default_watchlist(trader.world)
        self.view_source: list[str] | None = None   # None => holdings + watchlist
        self.view_label = "watchlist"
        self.owned_only = False
        self.sort_by_change = False
        self.view_page = 0
        self.page_size = 25
        self.cursor_aid: str | None = None
        self.chart_range = 1                        # index into CHART_RANGES (default 1D)
        self._curve = None                          # created in _build_ui; guards early refresh
        self._equity_curve = None

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

        # view toolbar — which slice of the market to show, sort, paging, and the highlighted asset
        views = QHBoxLayout()
        views.setSpacing(4)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_btns: dict[str, QPushButton] = {}
        for key, label, slug, handler in (
            ("0", "Owned", "owned", self.view_owned),
            ("1", "Crypto", "crypto", self.view_crypto),
            ("2", "Stocks", "stocks", self.view_stocks),
            ("3", "Bonds", "bonds", self.view_bonds),
            ("4", "Watch", "watchlist", self.view_watch),
        ):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setShortcut(key)
            b.setToolTip(f"{label}  ({key})")
            b.clicked.connect(handler)
            self.view_group.addButton(b)
            self.view_btns[slug] = b
            views.addWidget(b)
        self.view_btns["watchlist"].setChecked(True)

        views.addSpacing(14)
        self.sort_btn = QPushButton("Sort 1D%")
        self.sort_btn.setCheckable(True)
        self.sort_btn.setShortcut("o")
        self.sort_btn.setToolTip("Sort by 1D % (toggle)  (o)")
        self.sort_btn.clicked.connect(self.toggle_sort)
        views.addWidget(self.sort_btn)

        views.addSpacing(14)
        self.prev_btn = QPushButton("◂")
        self.prev_btn.setToolTip("Previous page")
        self.prev_btn.clicked.connect(self.prev_page)
        views.addWidget(self.prev_btn)
        self.page_label = QLabel("")
        self.page_label.setFont(mono)
        views.addWidget(self.page_label)
        self.next_btn = QPushButton("▸")
        self.next_btn.setToolTip("Next page")
        self.next_btn.clicked.connect(self.next_page)
        views.addWidget(self.next_btn)

        views.addStretch(1)
        self.selected_label = QLabel("")
        self.selected_label.setFont(mono)
        views.addWidget(self.selected_label)
        root.addLayout(views)

        self.board_model = BoardModel(self.trader)
        self.board = BoardView()
        self.board.setModel(self.board_model)
        self.board.setFont(mono)
        self.board.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.board.setSelectionMode(QAbstractItemView.SingleSelection)
        self.board.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.board.setShowGrid(False)
        self.board.setAlternatingRowColors(True)
        self.board.verticalHeader().setVisible(False)
        self.board.horizontalHeader().setHighlightSections(False)
        self.board.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.board.horizontalHeader().setStretchLastSection(True)
        self.board.selectionModel().currentRowChanged.connect(self._on_row_changed)

        # right column — the price chart now; equity curve / positions / news land in later slices
        right = QWidget()
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(6)

        # net-worth equity curve (from pf.nw_history) — small, fixed height at the top
        self.equity_chart = pg.PlotWidget()
        self.equity_chart.setBackground(PANEL)
        self.equity_chart.showGrid(x=False, y=True, alpha=0.12)
        self.equity_chart.setMenuEnabled(False)
        self.equity_chart.hideButtons()
        self.equity_chart.setMouseEnabled(x=False, y=False)
        self.equity_chart.getPlotItem().hideAxis("bottom")
        self.equity_chart.getAxis("left").setTextPen(DIM)
        self.equity_chart.setMaximumHeight(130)
        self._equity_curve = self.equity_chart.plot([], [])
        right_col.addWidget(self.equity_chart)

        chart_bar = QHBoxLayout()
        self.range_btn = QPushButton(f"Range: {CHART_RANGES[self.chart_range][0]}")
        self.range_btn.setShortcut("c")
        self.range_btn.setToolTip("Cycle chart range: 1H / 1D / 3D / 1W  (c)")
        self.range_btn.clicked.connect(self.cycle_chart_range)
        chart_bar.addWidget(self.range_btn)
        chart_bar.addStretch(1)
        right_col.addLayout(chart_bar)

        self.chart = pg.PlotWidget()
        self.chart.setBackground(PANEL)
        self.chart.showGrid(x=False, y=True, alpha=0.15)
        self.chart.setMenuEnabled(False)
        self.chart.hideButtons()
        self.chart.setMouseEnabled(x=False, y=False)
        self.chart.getPlotItem().hideAxis("bottom")     # tick-minute x labels aren't meaningful
        self.chart.getAxis("left").setTextPen(DIM)
        self._curve = self.chart.plot([], [])
        right_col.addWidget(self.chart, 1)

        # asset-detail fundamentals for the highlighted asset
        self.detail_label = QLabel("")
        self.detail_label.setTextFormat(Qt.RichText)
        self.detail_label.setWordWrap(True)
        self.detail_label.setFont(mono)
        self.detail_label.setAlignment(Qt.AlignTop)
        self.detail_label.setMaximumHeight(160)
        self.detail_label.setStyleSheet(f"background: {PANEL}; padding: 6px; border-radius: 4px;")
        right_col.addWidget(self.detail_label)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.board)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([680, 420])
        root.addWidget(splitter, 1)

        self._rebuild_board()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_detail()

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
            f"QTableView {{ background: {BG}; alternate-background-color: {PANEL}; color: {FG};"
            f" gridline-color: {PANEL}; selection-background-color: {GREEN};"
            f" selection-color: {BG}; border: 1px solid {PANEL}; outline: none; }}"
            f"QHeaderView::section {{ background: {PANEL}; color: {DIM}; padding: 4px 10px;"
            f" border: none; border-bottom: 1px solid {GREEN}; }}"
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
        self._refresh_board()
        self._refresh_chart()
        self._refresh_equity()

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
        self._refresh_board()
        self._refresh_chart()
        self._refresh_equity()
        if self.autosave_enabled and now - self._last_autosave >= AUTOSAVE_SECS:
            self._autosave()
            self._last_autosave = now

    def _refresh_header(self) -> None:
        self.header_label.setText(header_html(self.trader.world))

    def _refresh_board(self) -> None:
        self.board_model.refresh()

    # ---- board views / sort / paging / selection ---- #

    def view_owned(self) -> None:
        self._set_view(None, "owned", owned_only=True)

    def view_crypto(self) -> None:
        self._set_view(kind_ids(self.trader.world, AssetKind.CRYPTO), "crypto")

    def view_stocks(self) -> None:
        self._set_view(kind_ids(self.trader.world, AssetKind.STOCK), "stocks")

    def view_bonds(self) -> None:
        self._set_view(kind_ids(self.trader.world, AssetKind.BOND), "bonds")

    def view_watch(self) -> None:
        self._set_view(None, "watchlist")

    def _set_view(self, source, label: str, *, owned_only: bool = False) -> None:
        self.view_source = source
        self.view_label = label
        self.owned_only = owned_only
        self.view_page = 0
        if label in self.view_btns:
            self.view_btns[label].setChecked(True)
        self._rebuild_board()

    def toggle_sort(self) -> None:
        self.sort_by_change = not self.sort_by_change
        self.sort_btn.setChecked(self.sort_by_change)
        self.view_page = 0
        self._rebuild_board()

    def next_page(self) -> None:
        self.view_page += 1
        self._rebuild_board()

    def prev_page(self) -> None:
        self.view_page = max(0, self.view_page - 1)
        self._rebuild_board()

    def _rebuild_board(self) -> None:
        """Recompute which asset ids the board shows (view / sort / page changed) and reset the
        model. Live per-tick updates use _refresh_board() instead, which repaints values in place
        without reordering — so rows stay stable and clickable while playing."""
        ids, label = visible_ids(
            self.trader.world, self.trader.engine, view_source=self.view_source,
            owned_only=self.owned_only, sort_by_change=self.sort_by_change,
            watch=self.watch, view_page=self.view_page, page_size=self.page_size,
        )
        self.board_model.set_aids(ids)
        self._restore_selection(ids)
        self.page_label.setText(label or "")
        self.next_btn.setEnabled(label is not None)
        self.prev_btn.setEnabled(self.view_page > 0)

    def _restore_selection(self, ids) -> None:
        if self.cursor_aid in ids:
            self.board.selectRow(ids.index(self.cursor_aid))
        elif ids:
            self.board.selectRow(0)
        else:
            self.cursor_aid = None
            self._update_selected_label()

    def _on_row_changed(self, current, _previous) -> None:
        self.cursor_aid = self.board_model.aid_at(current.row())
        self._update_selected_label()
        self._refresh_chart()
        self._refresh_detail()

    def _update_selected_label(self) -> None:
        w = self.trader.world
        aid = self.cursor_aid
        if aid and w.has_asset(aid):
            self.selected_label.setText(
                f"▶ {aid.split(':', 1)[1]}  {w.name_of(aid)} · {w.kind_of(aid).name.title()}"
            )
        else:
            self.selected_label.setText("")

    # ---- price chart ---- #

    def cycle_chart_range(self) -> None:
        self.chart_range = (self.chart_range + 1) % len(CHART_RANGES)
        self.range_btn.setText(f"Range: {CHART_RANGES[self.chart_range][0]}")
        self._refresh_chart()

    def _refresh_chart(self) -> None:
        if self._curve is None:                     # chart not built yet — guard early refreshes
            return
        w, eng = self.trader.world, self.trader.engine
        aid = self.cursor_aid
        if not (aid and w.has_asset(aid)):
            self._curve.setData([], [])
            self.chart.setTitle("highlight an asset to chart it", color=DIM, size="10pt")
            return
        label, span = CHART_RANGES[self.chart_range]
        t = w.market.tick_index
        start = max(0, t - span)
        step = max(1, span // 240)                  # ~240 points across the panel
        series = eng.series(aid, start, t + 1, step)
        ys = [p for _, p in series]
        if not ys:
            self._curve.setData([], [])
            return
        xs = [tk for tk, _ in series]
        cur = w.price(aid)
        chg = (cur / ys[0] - 1) * 100 if ys[0] else 0.0
        color = GREEN if chg >= 0 else RED
        fill = QColor(color)
        fill.setAlpha(45)
        self._curve.setData(xs, ys, pen=pg.mkPen(color, width=2), fillLevel=min(ys), fillBrush=fill)
        self.chart.setTitle(
            f"{aid.split(':', 1)[1]} · {label}    {money(cur)}   {chg:+.2f}%",
            color=color, size="10pt",
        )

    def _refresh_equity(self) -> None:
        if self._equity_curve is None:
            return
        hist = self.trader.world.portfolio.nw_history
        if not hist:
            self._equity_curve.setData([], [])
            return
        xs = [t for t, _ in hist]
        ys = [v for _, v in hist]
        start_cash = self.trader.world.config.starting_cash
        color = GREEN if ys[-1] >= start_cash else RED
        fill = QColor(color)
        fill.setAlpha(40)
        self._equity_curve.setData(xs, ys, pen=pg.mkPen(color, width=2),
                                   fillLevel=min(ys), fillBrush=fill)
        ret = (ys[-1] / start_cash - 1) * 100 if start_cash else 0.0
        self.equity_chart.setTitle(f"net worth {money(ys[-1])}  ({ret:+.1f}%)",
                                   color=color, size="9pt")

    def _refresh_detail(self) -> None:
        w = self.trader.world
        aid = self.cursor_aid
        self.detail_label.setText(asset_detail_html(w, aid) if (aid and w.has_asset(aid)) else "")

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
