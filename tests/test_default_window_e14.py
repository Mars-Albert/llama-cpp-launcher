# -*- coding: utf-8 -*-
"""E14: first-launch window size + splitter ratio.

Regression: the app always opened at exactly its *content minimum* size —
a pre-show resize()/restoreGeometry() is silently discarded once the E11
content minimums are applied during construction — so on a 1080p+ screen
both splitter sides looked cramped (and a saved window size was never
actually restored either). First launch now opens at the fixed comfortable
default (WINDOW_WIDTH × WINDOW_HEIGHT, clamped to the screen's available
area) with a 400px left panel, re-applied in showEvent once the window is
visible. Saved geometry persists as plain [x, y, w, h] client-geometry
numbers and is applied with setGeometry in showEvent (the QByteArray
restoreGeometry form was discarded pre-show and is unreliable offscreen).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core.config as CC


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(CC, "SETTINGS_FILE", settings_file)
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr(CC, "PRESETS_DIR", presets_dir)
    yield settings_file


def _qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window():
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    return MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))


class _FakeScreen:
    def __init__(self, w, h):
        from PyQt6.QtCore import QRect
        self.r = QRect(0, 0, w, h)

    def availableGeometry(self):
        return self.r


def _fake_primary(monkeypatch, w, h):
    from PyQt6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "primaryScreen",
                        staticmethod(lambda: _FakeScreen(w, h)))


def test_default_window_size(monkeypatch):
    _fake_primary(monkeypatch, 1920, 1032)
    from ui.main_window import MainWindow
    from core.constants import WINDOW_WIDTH, WINDOW_HEIGHT
    assert MainWindow._default_window_size() == (WINDOW_WIDTH, WINDOW_HEIGHT)


def test_default_window_size_small_screen_clamped(monkeypatch):
    _fake_primary(monkeypatch, 1366, 728)
    from ui.main_window import MainWindow
    # the window must fit the screen
    assert MainWindow._default_window_size() == (1366, 728)


def test_default_splitter_sizes():
    from ui.main_window import MainWindow
    from core.constants import CARD_CONTENT_INSET
    width = 1600
    content = width - 2 * CARD_CONTENT_INSET
    left, right = MainWindow._default_splitter_sizes(width)
    assert left == 400
    assert left + right == content
    # clamps stay inside the left panel's 180-500 limits and the right
    # side never drops below 100 at any legal width
    for w in (900, 1053, 1360, 1600, 1920, 2560):
        l, r = MainWindow._default_splitter_sizes(w)
        assert 180 <= l <= 500
        assert r >= 100


def test_first_launch_opens_at_default_size_not_minimum(
        temp_settings, monkeypatch):
    """The first launch must open at the default size with the 400px left
    panel, not at the content minimum — that was the cramped 'both sides
    squeezed' look."""
    app = _qapp()
    _fake_primary(monkeypatch, 1920, 1032)
    from core.constants import WINDOW_WIDTH
    w = _window()
    try:
        w.show()
        import time
        for _ in range(25):
            app.processEvents()
            time.sleep(0.01)
        assert w.width() == WINDOW_WIDTH
        assert w.splitter.sizes()[0] == 400
    finally:
        w.close()


def test_saved_numeric_geometry_roundtrip(temp_settings, monkeypatch):
    """A saved [x, y, w, h] geometry (and its absolute left-panel width)
    must actually be restored on the next launch — before E14 the restore
    was silently discarded and every launch opened at the content minimum.
    The saved height may still be clamped up by the content minimum
    (font/DPI dependent), so only the width and the splitter are asserted.
    """
    app = _qapp()
    _fake_primary(monkeypatch, 1920, 1032)
    CC.save_ui_prefs({"geometry": [100, 80, 1500, 950],
                      "splitter": [420, 1060], "mode": 0})
    w = _window()
    try:
        w.show()
        import time
        for _ in range(25):
            app.processEvents()
            time.sleep(0.01)
        assert w.width() == 1500
        assert w.splitter.sizes()[0] == 420
    finally:
        w.close()
