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
    # only the fixed white-on-accent text colors may survive in dark:
    # the four control-bar gradient buttons (start/stop/copy/webui)
    # + checkbox indicator / list selection / table selection text
    # + server-path OK button + title-bar close-button hover
    # + themed message-box primary button
    assert dark.count("#ffffff") <= 10
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
        # The sheet lives at application level only; a window-level sheet
        # triggers a Qt quirk that reverts combo popup containers to the
        # light palette (see _apply_theme docstring).
        assert w.styleSheet() == ""
        # the application-level sheet follows the theme (window + dialogs)
        assert "#1e1e2e" in app.styleSheet()

        w._theme_action.trigger()
        assert w.theme == "light"
        assert not w._theme_action.isChecked()
        assert "#f0f2f5" in app.styleSheet()
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


def test_combo_popup_container_follows_theme(tmp_path, monkeypatch):
    """Regression: when a window-level stylesheet is present, Qt reverts the
    QComboBox popup container (QComboBoxPrivateContainer) to the default
    light palette — a white ring around the dark dropdown. The container
    interior must render in a theme (dark) color, not white."""
    app = _qapp()
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    from core.defaults import _FALLBACK_DEFAULTS
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS), theme="dark")
    try:
        w.show()
        app.processEvents()
        c = w.mode_combo
        c.showPopup()
        app.processEvents()
        try:
            cont = c.view().parent()
            img = cont.grab().toImage()
            px = img.pixelColor(3, 3)
            # not the default light palette (white) background
            assert not (px.red() > 200 and px.green() > 200 and px.blue() > 200), \
                f"combo popup container fell back to the light palette: #{px.name()}"
        finally:
            c.hidePopup()
    finally:
        w.close()
        app.setStyleSheet("")


def test_right_tabs_use_app_theme_with_dark_content(tmp_path, monkeypatch):
    """E15: the right-column tab widget (参数配置 / 日志输出 / 运行信息)
    carries no widget-level QSS — the app-level theme sheet styles its
    tab bar/pane (pre-E15 the bottom tab widget had a separate
    theme-aware sheet, now gone with the tab reorganisation). The
    log/info content keeps its always-dark inline QSS in both themes."""
    app = _qapp()
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    from core.defaults import _FALLBACK_DEFAULTS
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS), theme="dark")
    try:
        assert w.tab_widget.styleSheet() == ""
        # the log/info content stays always-dark under the dark theme
        assert "#121212" in w.log_output.styleSheet()
        assert "#121212" in w.info_display.styleSheet()
        # toggle to light: still no widget-level sheet, content still dark
        w._theme_action.trigger()
        assert w.theme == "light"
        assert w.tab_widget.styleSheet() == ""
        assert "#121212" in w.log_output.styleSheet()
    finally:
        w.close()
        app.setStyleSheet("")
