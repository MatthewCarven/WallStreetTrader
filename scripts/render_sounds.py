"""Render Trader PRO's sound effects from PySynthRack patches — the P5 build-time pipeline.

    python scripts/render_sounds.py                      # every patch in sounds/patches/
    python scripts/render_sounds.py sounds/patches/fill_a_sine.json
    python scripts/render_sounds.py --out trader_pro/sounds   # ship them into the package
    python scripts/render_sounds.py --analyse sounds/candidates/*.wav   # numbers only

PySynthRack is a **build-time tool here, never a runtime dependency**. Each patch is rendered by
its headless CLI (``python -m pysynthrack --cli --patch … --seconds …``) into a raw WAV via the
patch's ``disk_writer`` sink, and the game plays the finished file with Qt. Nothing in this script
is imported by ``trader_pro``.

The split of responsibilities is deliberate:

* **Character lives in the patch.** Waveform, pitch, envelope, filter — the things that make a
  fill sound different from a margin call — are PySynthRack's job, and editable in its UI.
* **Loudness and length are enforced here, identically for every sound.** Trailing silence is
  trimmed, a short fade-out guarantees the trim can't click, and the peak is normalised to
  :data:`TARGET_DBFS`. "All of them quiet" is therefore a number, checked by ``--analyse``, and not
  a hope. Retune one constant and every sound follows.

A patch's ``disk_writer`` ``path`` is overwritten at render time, so the committed patches carry a
placeholder and never a developer's absolute path. Patches must not contain a ``speaker_output``
— the render would then play out loud on whoever runs it — and this script refuses ones that do.

Requires: PySynthRack's own venv (it needs numpy/scipy/sounddevice; the game does not). Point
``PYSYNTHRACK_PYTHON`` at its interpreter, or leave the default sibling-checkout path.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "sounds" / "patches"
DEFAULT_OUT = ROOT / "sounds" / "candidates"

DEFAULT_PSR_PYTHON = (ROOT.parent.parent / "Python Synthesiser 2" / "Python Synthesizer"
                      / ".venv" / "Scripts" / "python.exe")

TARGET_DBFS = -18.0      # peak level every finished sound is normalised to — the "quiet" number
SILENCE_DBFS = -60.0     # below this counts as silence when trimming
TAIL_MS = 25             # silence kept after the last audible sample
FADE_MS = 4              # fade-out applied before the cut, so a trim can never click
RENDER_SECS = 0.6        # long enough for any chirp; the rest is trimmed


def psr_python() -> Path:
    p = Path(os.environ.get("PYSYNTHRACK_PYTHON") or DEFAULT_PSR_PYTHON)
    if not p.exists():
        sys.exit(f"PySynthRack interpreter not found: {p}\n"
                 f"Set PYSYNTHRACK_PYTHON to its .venv/Scripts/python.exe")
    return p


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def render_raw(patch_path: Path, raw_wav: Path, seconds: float = RENDER_SECS) -> None:
    """Run one patch through PySynthRack's headless CLI, writing ``raw_wav``."""
    data = json.loads(patch_path.read_text(encoding="utf-8"))
    writers = [m for m in data["modules"] if m["type"] == "disk_writer"]
    if len(writers) != 1:
        raise SystemExit(f"{patch_path.name}: need exactly one disk_writer, found {len(writers)}")
    if any(m["type"] == "speaker_output" for m in data["modules"]):
        raise SystemExit(f"{patch_path.name}: has a speaker_output — the render would play out loud")
    writers[0]["params"]["path"] = str(raw_wav)
    writers[0]["params"]["armed"] = True

    with tempfile.TemporaryDirectory() as tmp:
        tmp_patch = Path(tmp) / patch_path.name
        tmp_patch.write_text(json.dumps(data), encoding="utf-8")
        proc = subprocess.run(
            [str(psr_python()), "-m", "pysynthrack", "--cli", "--patch", str(tmp_patch),
             "--seconds", str(seconds), "--backend", "numpy"],
            capture_output=True, text=True, cwd=str(tmp),
        )
    if proc.returncode != 0 or not raw_wav.exists():
        raise SystemExit(f"{patch_path.name}: render failed (exit {proc.returncode})\n"
                         f"{proc.stdout}\n{proc.stderr}")


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return sr, x


def write_wav(path: Path, sr: int, y: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1.0, 1.0) * 32767).astype("<i2").tobytes())


def finish(raw_wav: Path, out_wav: Path) -> None:
    """Trim to the audible region, fade the tail, normalise the peak. Same for every sound."""
    sr, x = read_wav(raw_wav)
    loud = np.where(np.abs(x) > 10 ** (SILENCE_DBFS / 20))[0]
    if not len(loud):
        raise SystemExit(f"{raw_wav.name}: rendered silence — did the trigger fire?")
    end = min(len(x), loud[-1] + int(sr * TAIL_MS / 1000))
    y = x[loud[0]:end].copy()
    fade = min(len(y), int(sr * FADE_MS / 1000))
    y[-fade:] *= np.linspace(1.0, 0.0, fade)
    y *= (10 ** (TARGET_DBFS / 20)) / np.max(np.abs(y))
    write_wav(out_wav, sr, y)


# --------------------------------------------------------------------------- #
# Analyse — the half of "quiet" that needs no ears
# --------------------------------------------------------------------------- #

def analyse(path: Path) -> dict:
    sr, x = read_wav(path)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    loud = np.where(np.abs(x) > 10 ** (SILENCE_DBFS / 20))[0]
    pitch = None
    if len(loud) > 256:
        seg = x[loud[0]:loud[-1] + 1]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        pitch = float(np.fft.rfftfreq(len(seg), 1 / sr)[np.argmax(spec[1:]) + 1])
    return {
        "file": path.name,
        "seconds": len(x) / sr,
        "peak_dbfs": 20 * math.log10(peak) if peak > 0 else -math.inf,
        "dc": float(np.mean(x)) if len(x) else 0.0,
        "max_jump": float(np.max(np.abs(np.diff(x)))) if len(x) > 1 else 0.0,
        "audible_ms": (loud[-1] - loud[0]) / sr * 1000 if len(loud) else 0.0,
        "pitch_hz": pitch,
    }


def print_report(rows: list[dict]) -> None:
    print(f"{'file':22s} {'len':>6s} {'audible':>8s} {'peak':>10s} {'DC':>9s} {'jump':>6s} {'pitch':>7s}")
    for r in rows:
        pitch = f"{r['pitch_hz']:.0f}" if r["pitch_hz"] else "-"
        print(f"{r['file']:22s} {r['seconds']*1000:5.0f}ms {r['audible_ms']:6.0f}ms "
              f"{r['peak_dbfs']:7.1f} dBFS {r['dc']:+9.5f} {r['max_jump']:6.3f} {pitch:>7s}")


# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("patches", nargs="*", type=Path, help="patch JSON files (default: all)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where finished WAVs go")
    ap.add_argument("--analyse", action="store_true", help="only report on the given WAVs")
    args = ap.parse_args(argv)

    if args.analyse:
        print_report([analyse(p) for p in args.patches])
        return 0

    patches = args.patches or sorted(PATCH_DIR.glob("*.json"))
    if not patches:
        print("no patches found", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for patch in patches:
            raw = Path(tmp) / f"{patch.stem}.raw.wav"
            out = args.out / f"{patch.stem}.wav"
            render_raw(patch, raw)
            finish(raw, out)
            rows.append(analyse(out))
    print_report(rows)
    bad = [r for r in rows if abs(r["peak_dbfs"] - TARGET_DBFS) > 0.1]
    if bad:
        print("!! peak off target:", ", ".join(r["file"] for r in bad), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
