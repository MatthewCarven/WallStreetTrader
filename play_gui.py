#!/usr/bin/env python3
"""Launch the Trader PRO desktop GUI:  python play_gui.py

Requires PySide6 (+ pyqtgraph for charts):  pip install PySide6 pyqtgraph
The core game, CLI and TUI don't need them — this is an optional third front-end.
"""


def main() -> None:
    try:
        from trader_pro.gui.app import run_gui
    except ImportError as exc:
        print(
            "\n  Trader PRO's GUI needs PySide6 (and pyqtgraph for charts).\n"
            "     Install them with:\n"
            "         pip install PySide6 pyqtgraph\n"
            f"\n     (import failed: {exc})\n"
        )
        return
    run_gui()


if __name__ == "__main__":
    main()
