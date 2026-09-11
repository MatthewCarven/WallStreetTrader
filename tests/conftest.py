"""Shared fixtures for the whole suite.

Since P1 (session memory), the GUI *reads* ``settings.json`` at boot and *writes* it at close —
so every test, and especially the subprocess-driven GUI tests (which inherit our environment),
must see a private, empty settings dir rather than the developer's real one. The env var is the
override hook ``trader_pro.settings.settings_path()`` resolves at call time.

Since P5 (sound), a fill or a margin call *plays a WAV* — so the suite also sets
``TRADER_PRO_MUTE``, which turns every real player into a ``NullPlayer`` at construction. The
preference logic and the cue plumbing stay fully testable (install a recording player); only the
speakers are off. A green run is a silent run.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_PRO_SETTINGS_DIR", str(tmp_path / "settings"))
    monkeypatch.setenv("TRADER_PRO_MUTE", "1")
