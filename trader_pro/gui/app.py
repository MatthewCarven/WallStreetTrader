"""PySide6 desktop front-end for Trader PRO — Slice 0: the shell & lifecycle.

    python play_gui.py        # or:  python -m trader_pro.gui

A third front-end (alongside the CLI and Textual TUI) over the same UI-agnostic core. Like the
TUI it wraps a `TraderApp` and drives it with a live clock; unlike the TUI it renders with Qt.

Slice 0 establishes: the main window, the dashboard header, the live tick loop (play/pause at
1 sim-minute per real second, frame-rate independent), and the resume/autosave lifecycle. The
board, charts, positions, news and trading dialogs arrive in later slices. Requires PySide6.
"""
from __future__ import annotations

import random
import re
import sys
import time

import pyqtgraph as pg
from PySide6.QtCore import QAbstractTableModel, QByteArray, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSplitter,
    QTableView, QVBoxLayout, QWidget,
)

from ..cli import TraderApp, fmt_clock, money, fmt_qty
from ..core import (
    PROFILE_NAMES, AssetKind, Order, OrderSide, OrderKind, World, execute_order, get_profile,
    place_pending, cancel_pending, infer_order_kind, make_prediction, quote_cost,
)
from ..core.engine import DAY, HOUR
from ..core.orders import FEE_LEVELS
from ..persistence import (
    AUTOSAVE_SLOT, SAVES_DIR, autosave_path, delete_save, list_saves, load_game, save_game,
    slot_path,
)
from .settings import clear_accent_color, get_setting, set_accent_color, update_settings
from .model import (
    THEME, AMBER, AUTOSAVE_SECS, BG, BOARD_COLUMNS, CHART_RANGES, DIM, FG, GREEN, GREEN_HI,
    PANEL, POSITION_COLUMNS, RED, SPEEDS, TIMER_MS, asset_detail_html, boot, cell,
    closure_entry, default_watchlist, event_entry, fill_entry, header_html, kind_ids,
    margin_call_message, pending_fill_entry,
    margin_color, margin_fill, movers_ids, position_rows, prediction_summary, row_ctx,
    save_info_line, steps_for, ticker_text, trade_quantity, visible_ids,
)
from ..errlog import guard, setup_logging
from ..fmt import abbrev_money, signed_money


class MoneyAxis(pg.AxisItem):
    """Left axis that renders ticks as compact money ($1.2M, $110k) instead of pyqtgraph's
    default scientific notation (1.2e+06) — matching the no-sci-notation rule everywhere else."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enableAutoSIPrefix(False)          # suppress the '×1e6' exponent label

    def tickStrings(self, values, scale, spacing):
        return [abbrev_money(v) for v in values]


class MarginMeter(QWidget):
    """A compact [▮▮▮░░] margin-risk gauge — blue (all cash) → amber (buying power gone) → red
    (margin-call line). Set the level with set_fill(0..1). (Matthew's requested indicator.)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fill = 0.0
        self.setFixedSize(150, 18)

    def set_fill(self, fill: float) -> None:
        fill = max(0.0, min(1.0, fill))
        if fill != self._fill:
            self._fill = fill
            self.update()

    def paintEvent(self, event) -> None:   # noqa: N802 — Qt override
        p = QPainter(self)
        w, h, pad = self.width(), self.height(), 2
        p.fillRect(0, 0, w, h, QColor(BG))                       # empty track
        fw = int((w - 2 * pad) * self._fill)
        if fw > 0:
            p.fillRect(pad, pad, fw, h - 2 * pad, QColor(*margin_color(self._fill)))
        p.setPen(QColor(DIM))                                    # bracket border
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


class PlaceholderTableView(QTableView):
    """A table that paints centered dim text over an empty viewport, so a board view with no
    matches or a flat positions table reads as intentional rather than broken."""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.placeholder_text = placeholder

    def paintEvent(self, event) -> None:   # noqa: N802 — Qt override name
        super().paintEvent(event)
        model = self.model()
        if self.placeholder_text and (model is None or model.rowCount() == 0):
            painter = QPainter(self.viewport())
            painter.setPen(QColor(DIM))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, self.placeholder_text)


class BoardView(PlaceholderTableView):
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
        self.sort_active = False          # drives the ▼ glyph on the sorted (1D %) column header

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
            key, label = BOARD_COLUMNS[section]
            return f"{label} ▼" if self.sort_active and key == "chg" else label
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


class PositionsModel(QAbstractTableModel):
    """Feeds the positions table from pf.positions via the pure model.position_rows. Columns are
    POSITION_COLUMNS. refresh() resets when the set of held assets changes, else repaints values
    in place (so live P&L updates without flicker)."""

    def __init__(self, trader: TraderApp):
        super().__init__()
        self.trader = trader
        self._rows = []          # (aid, sym, qty, cost, value, pnl, pnlpct)
        self._aids = []

    def refresh(self) -> None:
        rows = position_rows(self.trader.world)
        aids = [r[0] for r in rows]
        if aids != self._aids:
            self.beginResetModel()
            self._rows, self._aids = rows, aids
            self.endResetModel()
        else:
            self._rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0),
                                      self.index(len(rows) - 1, self.columnCount() - 1),
                                      [Qt.DisplayRole, Qt.ForegroundRole])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(POSITION_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return POSITION_COLUMNS[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        _aid, sym, qty, cost, value, pnl, pnlpct = self._rows[index.row()]
        col = POSITION_COLUMNS[index.column()][0]
        if role == Qt.DisplayRole:
            return {"sym": sym, "qty": fmt_qty(qty), "cost": money(cost), "value": money(value),
                    "pnl": signed_money(pnl), "pnlpct": f"{pnlpct:+.2f}%"}[col]
        if role == Qt.ForegroundRole:
            if col == "qty":
                return QColor(AMBER if qty < 0 else FG)
            if col == "value":
                return QColor(GREEN if value > 0 else (RED if value < 0 else DIM))
            if col in ("pnl", "pnlpct"):                 # neutral at break-even, like the board
                return QColor(GREEN if pnl > 0 else (RED if pnl < 0 else DIM))
            return QColor(FG)
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignLeft if col == "sym" else Qt.AlignRight) | Qt.AlignVCenter)
        return None


class TradeDialog(QDialog):
    """Buy / sell / short / cover a single asset — a Qt port of the TUI's TradeDialog. Quantity
    parsing (empty=max, 'all', '$amount', plain number) is the pure model.trade_quantity; the order
    runs through execute_order. On a fill, `self.fill` = (verb, qty, sym, ExecutionResult) and the
    dialog accepts; a rejection shows the reason (res.message) and stays open."""

    def __init__(self, trader: TraderApp, aid: str, parent=None):
        super().__init__(parent)
        self.trader = trader
        self.aid = aid
        self.fill = None
        self.setWindowTitle(f"Trade · {aid.split(':', 1)[1]}")
        self.setModal(True)
        self.setMinimumWidth(390)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(11)

        layout = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setFont(mono)
        layout.addWidget(self.info)

        self.qty = QLineEdit()
        self.qty.setPlaceholderText("quantity:   10    ·    $500    ·    all")
        self.qty.setFont(mono)
        self.qty.returnPressed.connect(lambda: self._act("buy"))
        layout.addWidget(self.qty)

        self.trigger = QLineEdit()
        self.trigger.setPlaceholderText("trigger price to rest a stop/limit (optional):   110")
        self.trigger.setFont(mono)
        self.trigger.returnPressed.connect(lambda: self._act("buy"))
        layout.addWidget(self.trigger)
        hint = QLabel(f'<span style="color:{DIM}">blank trigger = market now · with a trigger, '
                      f'Buy/Sell rest a stop/limit (type inferred from the price)</span>')
        hint.setTextFormat(Qt.RichText)
        hint.setFont(mono)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        for verb, label, color in (("buy", "Buy", GREEN), ("sell", "Sell", RED),
                                   ("short", "Short", AMBER), ("cover", "Cover", GREEN_HI)):
            b = QPushButton(label)
            b.clicked.connect(lambda _checked=False, v=verb: self._act(v))
            b.setStyleSheet(f"border: 1px solid {color}; padding: 5px 14px; border-radius: 4px;")
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self.msg = QLabel("")
        self.msg.setTextFormat(Qt.RichText)
        self.msg.setFont(mono)
        self.msg.setWordWrap(True)
        layout.addWidget(self.msg)

        self.setStyleSheet(
            f"QDialog {{ background: {BG}; }}"
            f"QLabel {{ color: {FG}; }}"
            f"QLineEdit {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px; border-radius: 4px; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; }}"
            f"QPushButton:hover {{ background: {BG}; }}"
        )
        self._refresh_info()
        self.qty.setFocus()

    def _refresh_info(self) -> None:
        w = self.trader.world
        aid = self.aid
        pos = w.portfolio.positions.get(aid)
        held = pos.quantity if pos else 0.0
        self.info.setText(
            f'<b>{aid.split(":", 1)[1]}  {w.name_of(aid)}</b><br>'
            f'price {money(w.price(aid))}<br>'
            f'<span style="color:{DIM}">you hold {fmt_qty(held)}    cash {money(w.portfolio.cash)}<br>'
            f'buying power {money(w.portfolio.buying_power(w.price_of))}</span>'
        )

    def _act(self, verb: str) -> None:
        w = self.trader.world
        if self.trigger.text().strip():             # trigger set => rest a stop/limit, not trade now
            self._rest(verb, w)
            return
        qty = trade_quantity(w, self.aid, verb, self.qty.text())
        if qty <= 0:
            self._show("enter a valid quantity", AMBER)
            return
        side = OrderSide.BUY if verb in ("buy", "cover") else OrderSide.SELL
        res = execute_order(w, Order(self.aid, side, qty))
        if not res.filled:                          # rejected — keep open, show why
            self._show(res.message, RED)
            return
        self.fill = (verb, qty, self.aid.split(":", 1)[1], res)
        self.accept()

    @staticmethod
    def _resting_qty(token: str, trigger: float):
        """Share qty for a resting order; a $amount converts at the trigger price. 'all'/blank
        are refused — a resting size must be fixed up front (holdings can change before it fires)."""
        token = token.strip().lower().replace(",", "")
        if not token or token == "all":
            return None
        try:
            return float(token[1:]) / trigger if token.startswith("$") else float(token)
        except (ValueError, ZeroDivisionError):
            return None

    def _rest(self, verb: str, w) -> None:
        try:
            trigger = float(self.trigger.text().strip().lstrip("@").replace(",", ""))
        except ValueError:
            self._show("enter a valid trigger price", AMBER)
            return
        if trigger <= 0:
            self._show("trigger price must be positive", AMBER)
            return
        qty = self._resting_qty(self.qty.text(), trigger)
        if qty is None or qty <= 0:
            self._show("enter a share quantity or $amount (no 'all' for resting orders)", AMBER)
            return
        side = OrderSide.BUY if verb in ("buy", "cover") else OrderSide.SELL
        kind = infer_order_kind(side, trigger, w.price(self.aid))
        res = place_pending(w, self.aid, side, qty, kind, trigger)
        if not res:
            self._show(res.message, RED)
            return
        self.fill = ("resting", res.order)
        self.accept()

    def _show(self, text: str, color: str) -> None:
        self.msg.setText(f'<span style="color:{color}">{text}</span>')


class OrdersDialog(QDialog):
    """The resting stop/limit order book — 'Cancel order' drops the selected one. New orders are
    rested from the Trade dialog (add a trigger price there)."""

    def __init__(self, trader: TraderApp, parent=None):
        super().__init__(parent)
        self.trader = trader
        self.setWindowTitle("Resting orders")
        self.setModal(True)
        self.setMinimumSize(580, 320)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setFont(mono)
        self.list.itemDoubleClicked.connect(lambda _item: self._cancel())
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        cancel_b = QPushButton("Cancel order")
        cancel_b.clicked.connect(self._cancel)
        close_b = QPushButton("Close")
        close_b.clicked.connect(self.accept)
        buttons.addWidget(cancel_b)
        buttons.addStretch(1)
        buttons.addWidget(close_b)
        layout.addLayout(buttons)
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; }} QLabel {{ color: {FG}; }}"
            f"QListWidget {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent}; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px 14px; border-radius: 4px; }}"
        )
        self._fill()

    def _fill(self):
        self.list.clear()
        w = self.trader.world
        pending = w.portfolio.pending
        if not pending:
            item = QListWidgetItem("(no resting orders — set one from the Trade dialog: add a trigger price)")
            item.setForeground(QColor(DIM))
            self.list.addItem(item)
            return
        for o in pending:
            now = w.price(o.asset_id) if w.has_asset(o.asset_id) else 0.0
            armed = "  ●" if o.is_triggered(now) else ""
            line = (f"#{o.id:<3} {o.kind.value:<5} {o.side.value:<4} {fmt_qty(o.quantity):>11}  "
                    f"@ {money(o.trigger_price):>13}   now {money(now):>13}   "
                    f"{o.asset_id.split(':', 1)[1]}{armed}")
            item = QListWidgetItem(line)
            item.setData(Qt.UserRole, o.id)
            if o.is_triggered(now):
                item.setForeground(QColor(GREEN))
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def _cancel(self):
        item = self.list.currentItem()
        oid = item.data(Qt.UserRole) if item else None
        if oid is None:
            return
        cancel_pending(self.trader.world, int(oid))
        self._fill()


class LoadDialog(QDialog):
    """Browse the save slots (persistence.list_saves) — Load or Delete. On accept, self.chosen is
    the slot name to load."""

    def __init__(self, saves_dir, parent=None):
        super().__init__(parent)
        self.saves_dir = saves_dir
        self.chosen = None
        self.setWindowTitle("Saved games")
        self.setModal(True)
        self.setMinimumSize(560, 340)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setFont(mono)
        self.list.itemDoubleClicked.connect(lambda _item: self._load())
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        load_b = QPushButton("Load")
        load_b.clicked.connect(self._load)
        del_b = QPushButton("Delete")
        del_b.clicked.connect(self._delete)
        close_b = QPushButton("Close")
        close_b.clicked.connect(self.reject)
        buttons.addWidget(load_b)
        buttons.addWidget(del_b)
        buttons.addStretch(1)
        buttons.addWidget(close_b)
        layout.addLayout(buttons)
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; }} QLabel {{ color: {FG}; }}"
            f"QListWidget {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent}; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px 14px; border-radius: 4px; }}"
        )
        self._fill()

    def _fill(self):
        self.list.clear()
        for info in list_saves(self.saves_dir):
            item = QListWidgetItem(save_info_line(info))
            item.setData(Qt.UserRole, info.name)
            if info.corrupt:
                item.setForeground(QColor(RED))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _name(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _load(self):
        name = self._name()
        if name:
            self.chosen = name
            self.accept()

    def _delete(self):
        name = self._name()
        if not name:
            return
        # Confirm before a one-click, irreversible data loss (matches the TUI's delete guard).
        confirm = QMessageBox.question(
            self, "Delete save",
            f"Permanently delete '{name}'?\nThis can't be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)      # default focus: No
        if confirm == QMessageBox.Yes:
            delete_save(name, self.saves_dir)
            self._fill()


class NewWorldDialog(QDialog):
    """Configure a new world. On accept, self.config = (seed, profile, starting_cash, fee_level)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = None
        self.setWindowTitle("New world")
        self.setModal(True)
        self.setMinimumWidth(440)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)

        form = QFormLayout(self)
        self.profile = QComboBox()
        for name in PROFILE_NAMES:
            self.profile.addItem(f"{name} — {get_profile(name).tagline}", name)
        self.profile.setCurrentIndex(PROFILE_NAMES.index("Normal"))
        self.seed = QLineEdit(str(random.randint(1, 99_999_999)))
        self.cash = QLineEdit("5000")
        self.fee = QComboBox()
        self.fee.addItems(FEE_LEVELS)
        for widget in (self.profile, self.seed, self.cash, self.fee):
            widget.setFont(mono)
        form.addRow("Profile", self.profile)
        form.addRow("World seed", self.seed)
        form.addRow("Starting cash $", self.cash)
        form.addRow("Fees", self.fee)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; }} QLabel {{ color: {FG}; }}"
            f"QLineEdit, QComboBox {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 4px; border-radius: 4px; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px 14px; border-radius: 4px; }}"
        )

    def _accept(self):
        try:
            seed = int(self.seed.text().strip())
        except ValueError:
            seed = random.randint(1, 99_999_999)
        try:
            cash = float(self.cash.text().strip().replace(",", "").lstrip("$"))
        except ValueError:
            cash = 5000.0
        self.config = (seed, self.profile.currentData(), max(1.0, cash), self.fee.currentText())
        self.accept()


class PredictDialog(QDialog):
    """Buy a price forecast for an asset (predictions.quote_cost / make_prediction). Deducts the
    cost from cash on purchase; on buy, self.bought holds the forecast summary line."""

    HORIZONS = [("1 day", DAY), ("6 hours", 6 * HOUR), ("1 hour", HOUR)]

    def __init__(self, trader: TraderApp, aid: str, parent=None):
        super().__init__(parent)
        self.trader = trader
        self.aid = aid
        self.bought = None
        self.setWindowTitle(f"Predict · {aid.split(':', 1)[1]}")
        self.setModal(True)
        self.setMinimumWidth(430)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)

        layout = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setFont(mono)
        layout.addWidget(self.info)
        row = QHBoxLayout()
        cap = QLabel("Horizon")
        cap.setFont(mono)
        row.addWidget(cap)
        self.horizon = QComboBox()
        for label, ticks in self.HORIZONS:
            self.horizon.addItem(label, ticks)
        self.horizon.setFont(mono)
        self.horizon.currentIndexChanged.connect(self._update_cost)
        row.addWidget(self.horizon)
        row.addStretch(1)
        self.cost_label = QLabel()
        self.cost_label.setFont(mono)
        row.addWidget(self.cost_label)
        layout.addLayout(row)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setFont(mono)
        self.result.setTextFormat(Qt.RichText)
        layout.addWidget(self.result)
        buttons = QHBoxLayout()
        buy_b = QPushButton("Buy forecast")
        buy_b.clicked.connect(self._buy)
        close_b = QPushButton("Close")
        close_b.clicked.connect(self.reject)
        buttons.addWidget(buy_b)
        buttons.addStretch(1)
        buttons.addWidget(close_b)
        layout.addLayout(buttons)
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; }} QLabel {{ color: {FG}; }}"
            f"QComboBox {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 4px; border-radius: 4px; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px 14px; border-radius: 4px; }}"
        )
        self._refresh_info()
        self._update_cost()

    def _refresh_info(self):
        w = self.trader.world
        self.info.setText(f'<b>{self.aid.split(":", 1)[1]}  {w.name_of(self.aid)}</b><br>'
                          f'price {money(w.price(self.aid))}    cash {money(w.portfolio.cash)}')

    def _update_cost(self):
        cost = quote_cost(self.trader.world, self.aid, self.horizon.currentData())
        self.cost_label.setText(f"cost {money(cost)}")

    def _buy(self):
        w = self.trader.world
        horizon = self.horizon.currentData()
        cost = quote_cost(w, self.aid, horizon)
        if w.portfolio.cash < cost:
            self.result.setText(f'<span style="color:{RED}">not enough cash '
                                f'(need {money(cost)})</span>')
            return
        pred = make_prediction(w, self.trader.engine, self.aid, horizon)
        w.portfolio.cash -= pred.cost
        self.bought = prediction_summary(pred)
        color = GREEN if pred.direction == "UP" else RED
        self.result.setText(f'<span style="color:{color}">{self.bought}</span>')
        self._refresh_info()


HELP_HTML = (
    "<b>Keys</b><br>"
    "Space play/pause &nbsp; [ ] slower/faster &nbsp; s / h / d step minute/hour/day<br>"
    "0–5 views (owned · crypto · stocks · bonds · watch · movers) &nbsp; o sort 1D% &nbsp; c chart range<br>"
    "Enter / double-click a row to trade &nbsp; : command line &nbsp; ? help<br>"
    "Ctrl+N new world &nbsp; Ctrl+S save &nbsp; Ctrl+L saves / load<br><br>"
    "<b>Command line</b> (press : )<br>"
    "predict &lt;SYM&gt; [1d|6h] &nbsp; loan &lt;amount&gt; &nbsp; repay [amount|all] &nbsp; "
    "fees &lt;off…diabolic&gt;<br>"
    "find &lt;text&gt; &nbsp; look &lt;SYM&gt; &nbsp; market &nbsp; news &nbsp; "
    "buy / sell / short / cover &lt;SYM&gt; &lt;qty | $amt | all&gt;<br>"
    "(every CLI command works here)"
)


class HelpDialog(QDialog):
    """Keyboard shortcuts + command-line reference."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trader PRO — help")
        self.setModal(True)
        self.setMinimumWidth(560)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)
        layout = QVBoxLayout(self)
        body = QLabel(HELP_HTML)
        body.setTextFormat(Qt.RichText)
        body.setFont(mono)
        body.setWordWrap(True)
        layout.addWidget(body, 1)
        close_b = QPushButton("Close")
        close_b.clicked.connect(self.accept)
        layout.addWidget(close_b)
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; }} QLabel {{ color: {FG}; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px 14px; border-radius: 4px; }}"
        )


class TraderGUI(QMainWindow):
    """The main window: header, time controls, the live market board, chart/equity/detail,
    positions, news & ticker. Holds a `TraderApp` and advances it on a QTimer, exactly as the
    TUI's `TraderTUI` does with `set_interval`/`_on_timer`."""

    def __init__(self, trader: TraderApp, resumed: bool = False):
        super().__init__()
        self.trader = trader
        self.resumed = resumed
        self.playing = False
        self.speed_idx = 0                      # default: 1 sim-minute per real second
        self.autosave_enabled = True
        self.slot = None                        # current manual save slot (Ctrl+S default)
        self.saves_dir = SAVES_DIR
        self._play_clock: float | None = None   # monotonic ts of last advance; None while paused
        self._tick_accum = 0.0                   # carries fractional sim-minutes across timer ticks
        self._last_autosave = time.monotonic()

        # board view state (mirrors the TUI): which slice of the market, sort, paging, selection
        self.watch = default_watchlist(trader.world)
        self.view_source: list[str] | None = None   # None => holdings + watchlist
        self.view_label = "watchlist"
        self.owned_only = False
        self.sort_by_change = False
        self.movers = False                         # top-movers board mode
        self.view_page = 0
        self.page_size = 25
        self.cursor_aid: str | None = None
        self._ticker_base = ""
        self._ticker_off = 0
        self.chart_range = 1                        # index into CHART_RANGES (default 1D)
        self._curve = None                          # created in _build_ui; guards early refresh
        self._equity_curve = None
        self.margin_meter = None
        self.positions_model = None

        # P1 session memory: speed + chart range are plain indices _build_ui bakes into its
        # initial labels, so they restore *before* the widgets exist…
        self._restore_prefs_pre()

        self.setWindowTitle("TRADER PRO")
        self.resize(1120, 720)                  # default; a saved geometry overrides below
        self._build_ui()
        self._refresh_header()

        # …while geometry / view / sort need the widgets, so they restore after.
        self._restore_prefs_post()

        self._timer = QTimer(self)
        self._timer.setInterval(TIMER_MS)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start()

    # ---- layout ---- #

    def _build_ui(self) -> None:
        game_menu = self.menuBar().addMenu("Game")
        act_new = game_menu.addAction("New World")
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self.action_new_world)
        act_save = game_menu.addAction("Save…")
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.action_save)
        act_load = game_menu.addAction("Saves / Load…")
        act_load.setShortcut("Ctrl+L")
        act_load.triggered.connect(self.action_load)
        act_orders = game_menu.addAction("Resting orders…")
        act_orders.setShortcut("Ctrl+O")
        act_orders.triggered.connect(self.action_orders)
        game_menu.addSeparator()
        fees_menu = game_menu.addMenu("Fees")
        for level in FEE_LEVELS:
            fee_act = fees_menu.addAction(level)
            fee_act.triggered.connect(lambda _checked=False, lv=level: self.set_fee(lv))
        appearance_menu = self.menuBar().addMenu("Appearance")
        act_accent = appearance_menu.addAction("Accent colour…")
        act_accent.triggered.connect(self.action_pick_accent)
        act_reset_accent = appearance_menu.addAction("Reset accent to green")
        act_reset_accent.triggered.connect(self.action_reset_accent)
        help_act = self.menuBar().addMenu("Help").addAction("Shortcuts & commands")
        help_act.setShortcut("?")
        help_act.triggered.connect(self.show_help)

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

        self.ticker = QLabel("")                     # amber scrolling marquee (scrolls in _on_timer)
        self.ticker.setFont(mono)
        self.ticker.setFixedHeight(22)
        self.ticker.setStyleSheet(f"color: {AMBER}; background: {BG}; padding: 1px 6px;")
        # Ignore the (huge, ~3400px) text width for sizing — it's a marquee, it fills the bar and
        # clips. Without this the populated ticker forces the whole window's minimum width off-screen.
        self.ticker.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        root.addWidget(self.ticker)

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
        margin_cap = QLabel("margin")
        margin_cap.setFont(mono)
        controls.addWidget(margin_cap)
        self.margin_meter = MarginMeter()
        self.margin_meter.setToolTip(
            "Margin risk — blue: all cash · amber: buying power gone · red: margin call")
        controls.addWidget(self.margin_meter)
        controls.addSpacing(16)
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
            ("5", "Movers", "movers", self.view_movers),
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
        views.addSpacing(10)
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.setToolTip("Buy a price forecast for the highlighted asset")
        self.predict_btn.clicked.connect(self.open_predict)
        views.addWidget(self.predict_btn)
        self.trade_btn = QPushButton("Trade ▸")
        self.trade_btn.setToolTip("Buy / sell / short / cover the highlighted asset  (Enter or double-click)")
        self.trade_btn.clicked.connect(self.open_trade)
        views.addWidget(self.trade_btn)
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
        self.board.activated.connect(lambda _idx: self.open_trade())   # Enter / double-click a row

        # right column — the price chart now; equity curve / positions / news land in later slices
        right = QWidget()
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(6)

        # net-worth equity curve (from pf.nw_history) — small, fixed height at the top
        self.equity_chart = pg.PlotWidget(axisItems={"left": MoneyAxis(orientation="left")})
        self.equity_chart.setBackground(PANEL)
        self.equity_chart.showGrid(x=False, y=True, alpha=0.12)
        self.equity_chart.setMenuEnabled(False)
        self.equity_chart.hideButtons()
        self.equity_chart.setMouseEnabled(x=False, y=False)
        self.equity_chart.getPlotItem().hideAxis("bottom")
        self.equity_chart.getAxis("left").setTextPen(DIM)   # accent-derived pen: _style_panels()
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

        self.chart = pg.PlotWidget(axisItems={"left": MoneyAxis(orientation="left")})
        self.chart.setBackground(PANEL)
        self.chart.showGrid(x=False, y=True, alpha=0.15)
        self.chart.setMenuEnabled(False)
        self.chart.hideButtons()
        self.chart.setMouseEnabled(x=False, y=False)
        self.chart.setClipToView(True)                  # render only what's in view ...
        self.chart.getPlotItem().setDownsampling(auto=True, mode="peak")  # ... cheap even at ~1440 pts
        self.chart.getPlotItem().hideAxis("bottom")     # tick-minute x labels aren't meaningful
        self.chart.getAxis("left").setTextPen(DIM)      # accent-derived pen: _style_panels()
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

        # positions panel — summary line + table, tucked under the board on the left
        pos_panel = QWidget()
        pos_layout = QVBoxLayout(pos_panel)
        pos_layout.setContentsMargins(0, 0, 0, 0)
        pos_layout.setSpacing(4)
        self.pos_summary = QLabel("Positions")
        self.pos_summary.setFont(mono)
        self.pos_summary.setTextFormat(Qt.RichText)
        pos_layout.addWidget(self.pos_summary)
        self.positions_model = PositionsModel(self.trader)
        self.positions = PlaceholderTableView(
            "No open positions yet — Enter or double-click a board row to trade.")
        self.positions.setModel(self.positions_model)
        self.positions.setFont(mono)
        self.positions.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.positions.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.positions.setShowGrid(False)
        self.positions.setAlternatingRowColors(True)
        self.positions.verticalHeader().setVisible(False)
        self.positions.horizontalHeader().setHighlightSections(False)
        self.positions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.positions.horizontalHeader().setStretchLastSection(True)
        pos_layout.addWidget(self.positions, 1)

        left_split = QSplitter(Qt.Vertical)
        left_split.addWidget(self.board)
        left_split.addWidget(pos_panel)
        left_split.setStretchFactor(0, 3)
        left_split.setStretchFactor(1, 1)
        left_split.setSizes([520, 200])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_split)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([680, 420])
        root.addWidget(splitter, 1)

        self.news = QListWidget()                    # market story — newest on top
        self.news.setFont(mono)
        self.news.setMaximumHeight(140)
        self.news.setSelectionMode(QAbstractItemView.NoSelection)
        self.news.setFocusPolicy(Qt.NoFocus)
        root.addWidget(self.news)                       # accent border: _style_panels()

        self.command_line = QLineEdit()
        self.command_line.setFont(mono)
        self.command_line.setPlaceholderText(
            "press :  —  predict NVDA 1d · loan 1000 · repay all · fees high · find tesla · help")
        self.command_line.returnPressed.connect(self._run_command)
        root.addWidget(self.command_line)               # accent border: _style_panels()
        QShortcut(QKeySequence(":"), self, activated=self.command_line.setFocus)

        self._rebuild_board()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_detail()
        self._refresh_positions()
        self._build_ticker()
        self._log_line("Welcome to TRADER PRO — the market ticks live; news lands here.", GREEN_HI)
        if self.resumed:
            self._log_line("Resumed your last game.  (Ctrl+N starts a new world)", AMBER)

        self.setCentralWidget(central)
        self._apply_theme()
        self._style_panels()
        self.statusBar().showMessage(self._welcome_text())

    # ---- theming ---- #
    # Everything that bakes an accent colour into a *long-lived* widget is applied from
    # _apply_theme() / _style_panels(), never inline at construction, so both can simply be run
    # again when the accent changes (see _restyle_theme). Modal dialogs are exempt on purpose:
    # they read THEME when they're constructed, and they're constructed each time you open them.

    def _style_panels(self) -> None:
        """Accent-derived styling for the panels the main window keeps alive: both pyqtgraph
        charts (border + axis/gridline pen), the news list, and the command line."""
        for widget in (self.equity_chart, self.chart):
            widget.setStyleSheet(f"border: 1px solid {THEME.accent}; border-radius: 4px;")
            widget.getAxis("left").setPen(THEME.selection)      # dim-accent axis + gridlines
        self.news.setStyleSheet(
            f"QListWidget {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent}; }}")
        self.command_line.setStyleSheet(
            f"background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent_hi}; padding: 4px;")

    def _restyle_theme(self) -> None:
        """Repaint the whole window in the current THEME — the live half of the accent picker.

        Qt re-parses a stylesheet whenever you set one, so re-running the two styling passes is
        all it takes; the accent-coloured HTML labels (the TRADER PRO banner, the resting-order
        badge) just need their text regenerated. P&L colours are untouched by design."""
        self._apply_theme()
        self._style_panels()
        self._refresh_header()
        self._refresh_positions()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"QMainWindow {{ background: {BG}; }}"
            f"QWidget {{ background: {BG}; color: {FG}; }}"
            f"QLabel {{ color: {FG}; }}"
            f"QPushButton {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent};"
            f" padding: 5px 16px; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 1px solid {THEME.accent_hi}; }}"
            f"QStatusBar {{ color: {AMBER}; }}"
            f"QMenuBar {{ background: {PANEL}; color: {FG}; }}"
            f"QMenuBar::item:selected {{ background: {THEME.accent}; color: {BG}; }}"
            f"QMenu {{ background: {PANEL}; color: {FG}; border: 1px solid {THEME.accent}; }}"
            f"QMenu::item:selected {{ background: {THEME.accent}; color: {BG}; }}"
            f"QTableView {{ background: {BG}; alternate-background-color: {PANEL}; color: {FG};"
            f" gridline-color: {PANEL}; selection-background-color: {THEME.selection};"
            f" selection-color: {FG}; border: 1px solid {PANEL}; outline: none; }}"
            f"QHeaderView::section {{ background: {PANEL}; color: {DIM}; padding: 4px 10px;"
            f" border: none; border-bottom: 1px solid {THEME.accent}; }}"
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

    @guard(context="play/pause")
    def toggle_play(self) -> None:
        self.playing = not self.playing
        self._play_clock = None                 # reset baseline so toggling can't bank/jump time
        if self.playing:
            self.play_btn.setText("⏸  Pause")
            self.state_label.setText(f"playing · {SPEEDS[self.speed_idx][0]}")
        else:
            self.play_btn.setText("▶  Play")
            self.state_label.setText("paused")

    @guard(context="speed")
    def faster(self) -> None:
        self.speed_idx = min(len(SPEEDS) - 1, self.speed_idx + 1)
        self._update_speed()

    @guard(context="speed")
    def slower(self) -> None:
        self.speed_idx = max(0, self.speed_idx - 1)
        self._update_speed()

    def _update_speed(self) -> None:
        label = SPEEDS[self.speed_idx][0]
        self.speed_label.setText(label)
        if self.playing:
            self.state_label.setText(f"playing · {label}")

    @guard(context="step")
    def step_minute(self) -> None:
        self._advance_now(1)

    @guard(context="step")
    def step_hour(self) -> None:
        self._advance_now(HOUR)

    @guard(context="step")
    def step_day(self) -> None:
        self._advance_now(DAY)

    def _advance_now(self, ticks: int) -> None:
        """A discrete manual advance (Step / +1h / +1d) — jumps the market immediately, whether
        playing or paused, and never banks against the play clock. Mirrors the TUI's
        action_step/hour/day. Cheap even for +1d: the engine evaluates seeded anchors directly."""
        events, closures, fills = self.trader._advance(ticks)
        self._refresh_header()
        self._refresh_board()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_positions()
        self._log_news(events, closures, fills)
        if closures:
            self._notify_margin_call(closures)

    @guard(context="timer tick")
    def _on_timer(self) -> None:
        self._scroll_ticker()                   # marquee scrolls even while paused
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
        events, closures, fills = self.trader._advance(steps)
        self._refresh_header()
        self._refresh_board()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_positions()
        self._log_news(events, closures, fills)
        if self.autosave_enabled and now - self._last_autosave >= AUTOSAVE_SECS:
            self._autosave()
            self._last_autosave = now
        if closures:
            self._notify_margin_call(closures)

    def _refresh_header(self) -> None:
        self.header_label.setText(header_html(self.trader.world))
        if self.margin_meter is not None:
            self.margin_meter.set_fill(margin_fill(self.trader.world))
        self._build_ticker()

    # ---- news feed & ticker ---- #

    def _build_ticker(self) -> None:
        self._ticker_base = ticker_text(self.trader.world, self.trader.engine, self.watch)

    def _scroll_ticker(self) -> None:
        base = self._ticker_base
        if not base:
            self.ticker.setText("")
            return
        self._ticker_off = (self._ticker_off + 1) % len(base)
        self.ticker.setText(base[self._ticker_off:] + base[:self._ticker_off])

    def _log_news(self, events, closures, fills=()) -> None:
        for ev in events:
            self._log_line(*event_entry(ev))
        for r in fills:                             # resting stop/limit orders that fired
            self._log_line(*pending_fill_entry(r))
        for c in closures:                          # inserted last => shown on top (most recent)
            self._log_line(*closure_entry(c))

    def _log_line(self, text: str, color: str) -> None:
        item = QListWidgetItem(text)
        item.setForeground(QColor(color))
        self.news.insertItem(0, item)               # newest on top
        while self.news.count() > 200:
            self.news.takeItem(self.news.count() - 1)

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

    def view_movers(self) -> None:
        self.movers = True
        self.view_label = "movers"
        self.owned_only = False
        self.view_page = 0
        self.view_btns["movers"].setChecked(True)
        self._rebuild_board()

    def _set_view(self, source, label: str, *, owned_only: bool = False) -> None:
        self.view_source = source
        self.view_label = label
        self.owned_only = owned_only
        self.movers = False
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
        self.board_model.sort_active = self.sort_by_change      # header ▼ on the sorted column
        if self.movers:
            ids, label = movers_ids(self.trader.world, self.trader.engine), None
        else:
            ids, label = visible_ids(
                self.trader.world, self.trader.engine, view_source=self.view_source,
                owned_only=self.owned_only, sort_by_change=self.sort_by_change,
                watch=self.watch, view_page=self.view_page, page_size=self.page_size,
            )
        self.board_model.set_aids(ids)
        if not ids:
            self.board.placeholder_text = (
                "You don't own anything yet — buy from Stocks, Crypto or Bonds."
                if self.owned_only else "No assets to show in this view."
            )
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

    @guard(context="chart range")
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
        step = max(1, span // 1440)                 # ~1440 pts: 1:1 (per-minute) up to the 1D view,
        series = eng.series(aid, start, t + 1, step)  # lightly downsampled beyond it (3D / 1W)
        xs = [tk for tk, _ in series]
        ys = [p for _, p in series]
        cur = w.price(aid)
        if not xs or xs[-1] != t:                   # pin the current minute as a live leading edge
            xs.append(t)
            ys.append(cur)
        if not ys:
            self._curve.setData([], [])
            return
        chg = (cur / ys[0] - 1) * 100 if ys[0] else 0.0
        color = GREEN if chg >= 0 else RED
        fill = QColor(color)
        fill.setAlpha(45)
        self._curve.setData(xs, ys, pen=pg.mkPen(color, width=1), fillLevel=min(ys), fillBrush=fill)
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

    def _refresh_positions(self) -> None:
        if self.positions_model is None:
            return
        self.positions_model.refresh()
        pf = self.trader.world.portfolio
        po = self.trader.world.price_of
        upnl = pf.unrealized_pnl(po)
        upnl_c = GREEN if upnl > 0 else (RED if upnl < 0 else DIM)
        n = len(pf.pending)
        resting = (f'   <span style="color:{THEME.accent}">⏳ {n} resting order'
                   f'{"s" if n != 1 else ""} (Ctrl+O)</span>') if n else ""
        self.pos_summary.setText(
            f'Positions ({self.positions_model.rowCount()})   '
            f'unrealized <span style="color:{upnl_c}">{signed_money(upnl)}</span>   '
            f'<span style="color:{DIM}">margin headroom {money(pf.maintenance_excess(po))}</span>'
            f'{resting}'
            f'<br><span style="color:{DIM}">run · peak {money(pf.peak_net_worth)} · '
            f'max drawdown {pf.max_drawdown * 100:.1f}% · '
            f'black swans survived {pf.swans_survived}</span>'
        )

    # ---- trading ---- #

    @guard(context="trade")
    def open_trade(self) -> None:
        aid = self.cursor_aid
        if not (aid and self.trader.world.has_asset(aid)):
            return
        self._timer.stop()                          # freeze the market while the dialog is open
        try:
            dlg = TradeDialog(self.trader, aid, self)
            accepted = dlg.exec()
        finally:
            self._play_clock = None                 # don't bank the paused time on resume
            self._timer.start()
        if accepted and dlg.fill:
            if dlg.fill[0] == "resting":            # a stop/limit was rested, not traded now
                self._on_rested(dlg.fill[1])
            else:
                self._on_filled(*dlg.fill)

    @guard(context="orders")
    def action_orders(self) -> None:
        self._timer.stop()                          # freeze the market while the book is open
        try:
            OrdersDialog(self.trader, self).exec()
        finally:
            self._play_clock = None                 # don't bank the paused time on resume
            self._timer.start()
        self._refresh_positions()                   # a cancel may have emptied the book
        self._refresh_board()

    def _on_rested(self, order) -> None:
        self._refresh_positions()
        text = (f"rested #{order.id}: {order.kind.value} {order.side.value} "
                f"{fmt_qty(order.quantity)} {order.asset_id.split(':', 1)[1]} "
                f"@ {money(order.trigger_price)}")
        self._log_line(text, AMBER)
        self.statusBar().showMessage(text, 6000)

    def _on_filled(self, verb: str, qty: float, sym: str, res) -> None:
        self._rebuild_board()                       # holdings changed — re-pin owned rows
        self._refresh_header()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_detail()
        self._refresh_positions()
        text, color = fill_entry(verb, qty, sym, res)
        self._log_line(text, color)                 # fills land in the activity log, beside the news
        self.statusBar().showMessage(text, 6000)

    def _notify_margin_call(self, closures) -> None:
        if self.playing:                            # a margin call is a stop-and-look moment
            self.toggle_play()
        QMessageBox.warning(self, "⚠  Margin Call", margin_call_message(closures))

    # ---- save / load / new world ---- #

    @guard(context="save")
    def action_save(self) -> None:
        name, ok = QInputDialog.getText(self, "Save game", "Slot name:", text=self.slot or "manual")
        name = name.strip()
        if ok and name:
            try:
                save_game(self.trader.world, slot_path(name, self.saves_dir), label=name)
                self.slot = name
                self._log_line(f"Saved to '{name}'.", GREEN_HI)
                self.statusBar().showMessage(f"Saved to '{name}'", 4000)
            except Exception as exc:
                self._log_line(f"Save failed: {exc}", RED)

    @guard(context="load")
    def action_load(self) -> None:
        self._timer.stop()
        try:
            dlg = LoadDialog(self.saves_dir, self)
            accepted = dlg.exec()
        finally:
            self._play_clock = None
            self._timer.start()
        if accepted and dlg.chosen:
            try:
                world = load_game(slot_path(dlg.chosen, self.saves_dir), self.trader.universe)
                self.trader.start_world(world)
                self.slot = dlg.chosen
                self._after_world_swap(f"Loaded '{dlg.chosen}'.")
            except Exception as exc:
                self._log_line(f"Load failed: {exc}", RED)

    @guard(context="new world")
    def action_new_world(self) -> None:
        self._timer.stop()
        try:
            dlg = NewWorldDialog(self)
            accepted = dlg.exec()
        finally:
            self._play_clock = None
            self._timer.start()
        if accepted and dlg.config:
            seed, profile, cash, fee = dlg.config
            world = World.new(self.trader.universe, world_seed=seed, profile=profile,
                              starting_cash=cash, fee_level=fee)
            self.trader.start_world(world)
            self.slot = None
            self._after_world_swap(f"New world · {profile} · seed {seed}")

    def _after_world_swap(self, message: str) -> None:
        """Reset the view to the default watchlist and repaint every panel for the swapped-in world
        (used by both load and new-world)."""
        self.movers = False
        self.view_source = None
        self.view_label = "watchlist"
        self.owned_only = False
        self.sort_by_change = False
        self.view_page = 0
        self.cursor_aid = None
        self.watch = default_watchlist(self.trader.world)
        self.view_btns["watchlist"].setChecked(True)
        self.sort_btn.setChecked(False)
        if self.playing:
            self.toggle_play()
        self.news.clear()
        self._rebuild_board()
        self._refresh_header()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_detail()
        self._refresh_positions()
        self._build_ticker()
        self._log_line(message, GREEN_HI)
        self.statusBar().showMessage(message, 5000)

    # ---- predictions / fees / command line / help ---- #

    @guard(context="predict")
    def open_predict(self) -> None:
        aid = self.cursor_aid
        if not (aid and self.trader.world.has_asset(aid)):
            return
        self._timer.stop()
        try:
            dlg = PredictDialog(self.trader, aid, self)
            dlg.exec()
        finally:
            self._play_clock = None
            self._timer.start()
        if dlg.bought:                              # a forecast was purchased (cash already deducted)
            self._refresh_header()
            self._log_line(dlg.bought, AMBER)

    @guard(context="fee")
    def set_fee(self, level: str) -> None:
        self.trader.world.config.fee_level = level
        self._log_line(f"Fees set to '{level}'.", GREEN_HI)
        self.statusBar().showMessage(f"Fees: {level}", 3000)

    @guard(context="accent picker")
    def action_pick_accent(self) -> None:
        """Pick a theme accent and apply it immediately (P&L colours stay green/red)."""
        chosen = QColorDialog.getColor(QColor(THEME.accent), self, "Choose accent colour")
        if not chosen.isValid():                     # dialog cancelled
            return
        hex_color = chosen.name()                    # "#rrggbb", lower-case
        set_accent_color(hex_color)                  # persist first: a restyle must not lose it
        self.set_accent(hex_color)
        self._log_line(f"Accent colour set to {hex_color}.", GREEN_HI)
        self.statusBar().showMessage(f"Accent: {hex_color}", 3000)

    @guard(context="accent reset")
    def action_reset_accent(self) -> None:
        """Forget any custom accent, reverting to the default phosphor green — immediately."""
        clear_accent_color()
        self.set_accent(None)
        self._log_line("Accent colour reset to phosphor green.", GREEN_HI)
        self.statusBar().showMessage("Accent: phosphor green (default)", 3000)

    def set_accent(self, hex_color: str | None) -> None:
        """Point the live THEME at `hex_color` (None = default) and repaint. Persistence is the
        caller's job — this is the display half, and it's what the tests drive."""
        THEME.set(hex_color)
        self._restyle_theme()

    def show_help(self) -> None:
        HelpDialog(self).exec()

    @guard(context="command line")
    def _run_command(self) -> None:
        line = self.command_line.text().strip()
        self.command_line.clear()
        if not line:
            return
        try:
            result = self.trader.execute(line)
        except Exception as exc:
            result = f"error: {exc}"
        result = re.sub(r"\x1b\[[0-9;]*m", "", result or "")     # strip any ANSI colour codes
        self._rebuild_board()                       # state may have changed (trade / loan / fees)
        self._refresh_header()
        self._refresh_chart()
        self._refresh_equity()
        self._refresh_detail()
        self._refresh_positions()
        self._build_ticker()
        for ln in reversed(result.split("\n")):     # newest-on-top list; keep reading order
            if ln.strip():
                self._log_line(ln, DIM)
        self._log_line(f"› {line}", GREEN_HI)

    # ---- persistence ---- #

    def _autosave(self) -> None:
        try:
            save_game(self.trader.world, autosave_path(), label=AUTOSAVE_SLOT)
        except Exception:
            pass                                # autosave is best-effort, exactly like the TUI

    # ---- session memory (P1) ---- #
    #
    # Install-level trivia only (geometry / view / sort / chart range / speed) — game-state knobs
    # like the fee level live on world.config and travel with the save instead. Restores treat the
    # settings file as untrusted input (it's user-editable JSON): every value is validated and a
    # bad one silently keeps the default, per the "never crash the UI over I/O" stance.

    def _restore_prefs_pre(self) -> None:
        """Speed + chart range — restored before _build_ui so the initial labels render right."""
        idx = get_setting("speed")
        if isinstance(idx, int) and 0 <= idx < len(SPEEDS):
            self.speed_idx = idx
        idx = get_setting("chart_range")
        if isinstance(idx, int) and 0 <= idx < len(CHART_RANGES):
            self.chart_range = idx

    def _restore_prefs_post(self) -> None:
        """Geometry + board view + sort — these need the widgets, so run right after _build_ui."""
        geo = get_setting("geometry")
        if isinstance(geo, str) and geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(geo.encode("ascii")))
            except Exception:
                pass                            # junk geometry -> keep the 1120×720 default
        if get_setting("sort_1d") is True:
            self.sort_by_change = True
            self.sort_btn.setChecked(True)
        view = get_setting("view")
        dispatch = {"owned": self.view_owned, "crypto": self.view_crypto,
                    "stocks": self.view_stocks, "bonds": self.view_bonds,
                    "watchlist": self.view_watch, "movers": self.view_movers}
        if view in dispatch and view != self.view_label:
            dispatch[view]()                    # checks the right button + rebuilds, sort applied
        elif self.sort_by_change:
            self._rebuild_board()               # default view, but the restored sort needs a pass

    def _save_prefs(self) -> None:
        """Persist the session trivia in one atomic write — best-effort, like autosave."""
        try:
            update_settings({
                "geometry": bytes(self.saveGeometry().toHex()).decode("ascii"),
                "view": self.view_label,
                "sort_1d": self.sort_by_change,
                "chart_range": self.chart_range,
                "speed": self.speed_idx,
            })
        except Exception:
            pass

    def closeEvent(self, event) -> None:        # noqa: N802 — Qt override name
        if self.autosave_enabled:
            self._autosave()
        self._save_prefs()
        super().closeEvent(event)


def run_gui() -> None:
    """Boot a world (resume last autosave or start fresh) and open the window — mirrors run_tui()."""
    setup_logging()                             # silent error log + global uncaught-exception hooks
    trader, resumed = boot()
    app = QApplication.instance() or QApplication(sys.argv)
    window = TraderGUI(trader, resumed=resumed)
    window.show()
    app.exec()
