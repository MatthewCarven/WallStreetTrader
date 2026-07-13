#!/usr/bin/env python3
"""Build a standalone Trader PRO desktop app (.exe) with PyInstaller.

    python scripts/build_exe.py

Produces ``dist/TraderPro.exe`` - a single-file, windowed build of the PySide6 desktop GUI with the
seed universe bundled in. At runtime the frozen app reads its bundled seeds from PyInstaller's temp
dir and writes ``saves/`` and ``logs/`` **next to the .exe** (see ``trader_pro/_paths.py``), so it's
a portable app: drop ``TraderPro.exe`` in a folder and your saves live beside it.

Requirements:
    pip install pyinstaller PySide6 pyqtgraph

Notes:
* First launch of a one-file build self-extracts and can take a few seconds; the .exe is large
  (~150 MB) because it packs the Python runtime + Qt.
* Drop a ``trader_pro.ico`` in the repo root to give the .exe an icon (optional).
* If a rare Qt/pyqtgraph submodule is missed, add ``--hidden-import <module>`` below and rebuild.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "TraderPro"
ENTRY = ROOT / "play_gui.py"
SEEDS = ROOT / "data" / "seeds"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller isn't installed.  Run:  pip install pyinstaller", file=sys.stderr)
        return 1
    if not list(SEEDS.glob("*.json")):
        print(f"No seed files in {SEEDS} - build them first:  python scripts/build_seed.py",
              file=sys.stderr)
        return 1

    # Bundle the seed universe so the frozen app finds it at resource_dir()/data/seeds.
    add_data = f"{SEEDS}{os.pathsep}data/seeds"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",              # one distributable .exe
        "--windowed",             # GUI app - no console window
        "--name", APP_NAME,
        "--add-data", add_data,
    ]
    icon = ROOT / "trader_pro.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(ENTRY))

    print("Building the Trader PRO desktop app - this can take a few minutes.\n$", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode == 0:
        exe = ROOT / "dist" / (APP_NAME + (".exe" if os.name == "nt" else ""))
        print(f"\nBuilt: {exe}\n    (saves & logs are written next to the .exe at runtime)")
    else:
        print("\nPyInstaller build failed - see the output above.", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
