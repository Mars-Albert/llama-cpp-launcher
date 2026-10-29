"""Tests for the explicit-output mode (2026-10): the global mode-bar switch
plus the per-row toggles in the advanced panel.

Covers: toggle coverage (exactly the explicit-eligible UI rows, one each),
the global switch hiding/showing the toggles and gating the builder, the
checked state surviving a mode off/on cycle, command building in basic
mode still honoring explicit output, settings persistence round-trip, the
restore path (incl. stale-key sanitization), and retranslation of the new
strings. Offscreen throughout.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication

import core.config as CC
from core.defaults import _FALLBACK_DEFAULTS
from core.params_schema import UI_PARAMS
from ui.command_builder import EXPLICIT_ELIGIBLE_KEYS, explicit_eligible
import ui.main_window as MW

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture
def window(tmp_path, monkeypatch):
    d = tmp_path / "presets"
    d.mkdir(parents=True)
    monkeypatch.setattr(CC, "PRESETS_DIR", d)
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    app = _qapp()  # keep a live reference
    w = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    yield w
    w.close()


def _explicit_btn(window, key):
    return window.advanced_panel._explicit_btns[key]


def test_every_eligible_row_has_exactly_one_toggle(window):
    expected = {p.key for p in UI_PARAMS
                if p.wattr is not None and explicit_eligible(p)}
    assert expected == set(EXPLICIT_ELIGIBLE_KEYS)
    assert set(window.advanced_panel._explicit_btns) == expected


def test_toggles_hidden_and_no_effect_while_mode_off(window):
    assert not window.btn_explicit_mode.isChecked()
    for btn in window.advanced_panel._explicit_btns.values():
        assert btn.isHidden()
    # a hidden toggle still records its state, but the builder must not
    # explicitly emit while the global mode is off
    _explicit_btn(window, "port").setChecked(True)
    assert "port" in window._explicit_params
    assert "--port" not in window._build_args_from_params()


def test_mode_on_shows_toggles_and_writes_default_values(window):
    # The test window is never shown, so assert the widgets' own hidden
    # state (isHidden), not the effective isVisible().
    window.btn_explicit_mode.setChecked(True)
    assert window._explicit_mode
    for btn in window.advanced_panel._explicit_btns.values():
        assert not btn.isHidden()
    _explicit_btn(window, "port").setChecked(True)
    args = window._build_args_from_params()
    assert "--port" in args and "9931" in args
    # unchecking stops the explicit emission
    _explicit_btn(window, "port").setChecked(False)
    assert "--port" not in window._build_args_from_params()


def test_mode_off_hides_but_keeps_checked_state(window):
    window.btn_explicit_mode.setChecked(True)
    _explicit_btn(window, "port").setChecked(True)
    window.btn_explicit_mode.setChecked(False)
    assert _explicit_btn(window, "port").isChecked()
    assert _explicit_btn(window, "port").isHidden()
    assert "--port" not in window._build_args_from_params()
    window.btn_explicit_mode.setChecked(True)
    assert not _explicit_btn(window, "port").isHidden()
    assert "--port" in window._build_args_from_params()


def test_basic_mode_command_still_honors_explicit(window):
    window.btn_explicit_mode.setChecked(True)
    _explicit_btn(window, "port").setChecked(True)
    window.mode_combo.setCurrentIndex(0)  # switch to basic mode
    assert "--port" in window._build_args_from_params()


def test_persistence_roundtrip(window):
    window.btn_explicit_mode.setChecked(True)
    _explicit_btn(window, "port").setChecked(True)
    window._save_ui_state()
    prefs = CC.load_ui_prefs()
    assert prefs["explicit_mode"] is True
    assert prefs["explicit_params"] == ["port"]


def test_restore_from_settings(window):
    # Save an explicit-output state, then open a second window against
    # the same settings file: the global mode and the checked rows come
    # back.
    window.btn_explicit_mode.setChecked(True)
    _explicit_btn(window, "port").setChecked(True)
    window._save_ui_state()
    w2 = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        assert w2.btn_explicit_mode.isChecked()
        assert w2.advanced_panel._explicit_btns["port"].isChecked()
        assert not w2.advanced_panel._explicit_btns["port"].isHidden()
        assert "--port" in w2._build_args_from_params()
    finally:
        w2.close()


def test_restore_sanitizes_stale_keys(window):
    CC.save_ui_pref("explicit_mode", True)
    CC.save_ui_pref("explicit_params", ["port", "no_such_key"])
    w2 = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        assert w2._explicit_mode is True
        assert w2._explicit_params == {"port"}
    finally:
        w2.close()


def test_retranslate_explicit_strings(window):
    from core.i18n import get_language, set_language
    orig = get_language()
    try:
        set_language("en")
        window.retranslate_ui()
        assert _explicit_btn(window, "port").text() == "Explicit"
        assert "Explicit Output" in window.btn_explicit_mode.text()
        set_language("zh")
        window.retranslate_ui()
        assert _explicit_btn(window, "port").text() == "显式"
        assert "显式输出" in window.btn_explicit_mode.text()
    finally:
        set_language(orig)
