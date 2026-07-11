"""Trader PRO desktop GUI (PySide6) — a third front-end over the same core as the CLI and TUI.

Kept deliberately import-light: `trader_pro.gui.model` holds the pure, Qt-free helpers (pacing
math, the header string, and — in later slices — the board/chart data), so it can be imported
and unit-tested without PySide6 installed. `trader_pro.gui.app` holds the Qt widgets and is the
only module that imports PySide6.
"""
