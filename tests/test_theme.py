"""Tests for the E5 light/dark theme (offscreen Qt where needed)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication

import core.config as CC
from ui.main_window import MainWindow

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def test_stylesheets_resolve_all_tokens():
    for theme in ("light", "dark"):
        qss = MainWindow._get_stylesheet(theme)
        assert "@@" not in qss, f"unresolved token in {theme} theme"
        assert "QMainWindow" in qss and "QTabBar::tab" in qss
    light, dark = MainWindow._get_stylesheet("light"), MainWindow._get_stylesheet("dark")
    # light keeps the original palette
    assert "#f0f2f5" in light and "#ffffff" in light and "#d0d4dc" in light
    # dark uses the new palette and none of the light-only backgrounds
    assert "#1e1e2e" in dark and "#181825" in dark and "#313244" in dark
    assert "#f0f2f5" not in dark and "#d0d4dc" not in dark and "#e8ecf0" not in dark
    # only the fixed white-on-accent text colors may survive in dark
    assert dark.count("#ffffff") <= 6
    # identical structure (same selectors in the same order)
    import re
    selectors = re.findall(r"([A-Za-z][\w:.\-# ]*?)\s*\{", light)
    assert selectors == re.findall(r"([A-Za-z][\w:.\-# ]*?)\s*\{", dark)


def test_theme_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    assert CC.load_theme() == "light"  # default
    CC.save_theme("dark")
    assert CC.load_theme() == "dark"
    CC.save_theme("light")
    assert CC.load_theme() == "light"
    CC.save_theme("weird-value")
    assert CC.load_theme() == "light"  # anything but "dark" is light


def test_mainwindow_theme_and_toggle(tmp_path, monkeypatch):
    app = _qapp()
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    from core.defaults import _FALLBACK_DEFAULTS

    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS), theme="dark")
    try:
        assert w.theme == "dark"
        assert w._theme_action.isChecked()
        assert "#1e1e2e" in w.styleSheet()
        # the application-level sheet follows the theme too (for dialogs)
        assert "#1e1e2e" in app.styleSheet()

        w._theme_action.trigger()
        assert w.theme == "light"
        assert not w._theme_action.isChecked()
        assert "#f0f2f5" in w.styleSheet()
        assert CC.load_theme() == "light"  # persisted

        w._theme_action.trigger()
        assert w.theme == "dark"
        assert CC.load_theme() == "dark"
    finally:
        w.close()
        # restore the app sheet so other tests are unaffected
        app.setStyleSheet("")


def test_theme_default_from_settings(tmp_path, monkeypatch):
    app = _qapp()
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    CC.save_theme("dark")
    from core.defaults import _FALLBACK_DEFAULTS
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        assert w.theme == "dark"
        assert w._theme_action.isChecked()
    finally:
        w.close()
        app.setStyleSheet("")


def test_bottom_tabs_qss_follows_theme(tmp_path, monkeypatch):
    """E5 follow-up: the bottom log/info tab widget carries its own (inline)
    QSS; it must be theme-aware, not a hardcoded light sheet."""
    app = _qapp()
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    from core.defaults import _FALLBACK_DEFAULTS
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS), theme="dark")
    try:
        # dark: catppuccin crust/mantle/accent, no light leftovers
        assert "#11111b" in w.tab_widget.styleSheet()
        assert "#ffffff" not in w.tab_widget.styleSheet()
        # toggle to light: the pre-E5 sheet, verbatim
        w._theme_action.trigger()
        assert "#ffffff" in w.tab_widget.styleSheet()
        assert "#11111b" not in w.tab_widget.styleSheet()
    finally:
        w.close()
        app.setStyleSheet("")
