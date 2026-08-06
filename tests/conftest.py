"""Shared fixtures for the whole suite.

Since P1 (session memory), the GUI *reads* ``settings.json`` at boot and *writes* it at close —
so every test, and especially the subprocess-driven GUI tests (which inherit our environment),
must see a private, empty settings dir rather than the developer's real one. The env var is the
override hook ``trader_pro.gui.settings.settings_path()`` resolves at call time.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_PRO_SETTINGS_DIR", str(tmp_path / "settings"))
