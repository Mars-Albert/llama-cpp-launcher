"""E9: startup restore of the last loaded preset (last_preset in settings).

The launcher remembers the preset the user last clicked 加载 for and restores
it on the next startup; if none was ever loaded (or the file is gone) startup
keeps the defaults.
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication, QMessageBox

import core.config as CC
from core.defaults import _FALLBACK_DEFAULTS
import ui.main_window as MW

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated presets dir + settings file; no real llama-server probe."""
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr(CC, "PRESETS_DIR", presets_dir)
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    # The startup worker would spawn a real llama-server probe; tests must be
    # hermetic and deterministic.
    monkeypatch.setattr(MW.MainWindow, "_check_server_info", lambda self: None)
    return presets_dir


def _write_preset(presets_dir, name, params, created="2026-01-01T12:00:00"):
    data = {
        "name": name,
        "version": 1,
        "created": created,
        "params": params,
    }
    (presets_dir / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_window(env):
    _qapp()  # keep a live reference; GC of the wrapper destroys the C++ app
    return MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))


def test_no_last_preset_keeps_defaults(env):
    w = _make_window(env)
    try:
        assert w.params["temp"] == _FALLBACK_DEFAULTS["temp"]
        assert w.params["top_p"] == _FALLBACK_DEFAULTS["top_p"]
        assert w.preset_combo.count() == 0
        assert CC.load_last_preset() == ""
    finally:
        w.close()


def test_last_preset_restored_on_startup(env):
    _write_preset(env, "mycfg", {"temp": 0.42, "top_p": 0.7})
    CC.save_last_preset("mycfg")
    w = _make_window(env)
    try:
        assert w.params["temp"] == 0.42
        assert w.params["top_p"] == 0.7
        # keys the preset doesn't set keep the defaults
        assert w.params["repeat_penalty"] == _FALLBACK_DEFAULTS["repeat_penalty"]
        # the combo shows the restored preset selected
        assert w.preset_combo.currentText() == "mycfg"
        # re-baselined: the restore is not an undoable step
        assert len(w.params_history) == 1
        assert w.params_history[0]["temp"] == 0.42
        assert w._last_saved["temp"] == 0.42
        assert w._pending_snapshot is False
        assert w.btn_undo.isEnabled() is False
        # protection set for the live --help defaults merge
        assert w._preset_protected_keys == {"temp", "top_p"}
    finally:
        w.close()


def test_restore_protects_explicit_values_from_live_merge(env):
    # temp stored equal to the fallback — the case that used to be silently
    # replaced by the live default
    _write_preset(env, "mycfg", {"temp": 0.8})
    CC.save_last_preset("mycfg")
    w = _make_window(env)
    try:
        live = dict(_FALLBACK_DEFAULTS)
        live["temp"] = 0.6    # the user's explicit preset choice must survive
        live["top_p"] = 0.9   # preset doesn't set top_p → live default applies
        w._on_startup_defaults(live, [])
        assert w.params["temp"] == 0.8
        assert w.params["top_p"] == 0.9
        # the live default still became the new baseline
        assert w.defaults["temp"] == 0.6
    finally:
        w.close()


def test_restore_clears_missing_model_paths(env, tmp_path):
    _write_preset(env, "mp", {
        "model": str(tmp_path / "nope.gguf"),
        "temp": 0.5,
    })
    CC.save_last_preset("mp")
    w = _make_window(env)
    try:
        assert w.params["temp"] == 0.5
        assert w.params["model"] == ""   # A9: machine-local path, not present
    finally:
        w.close()


def test_stale_last_preset_is_cleared_and_skipped(env):
    CC.save_last_preset("gone")   # preset file was deleted out from under us
    w = _make_window(env)
    try:
        assert w.params["temp"] == _FALLBACK_DEFAULTS["temp"]
        assert CC.load_last_preset() == ""   # stale pointer cleaned up
    finally:
        w.close()


def test_corrupt_preset_does_not_crash(env):
    (env / "bad.json").write_text("{not json", encoding="utf-8")
    CC.save_last_preset("bad")
    w = _make_window(env)          # startup must not raise
    try:
        assert w.params["temp"] == _FALLBACK_DEFAULTS["temp"]
        # manual load of the corrupt preset: no crash, params untouched
        w.preset_combo.setCurrentText("bad")
        w._load_preset()
        assert w.params["temp"] == _FALLBACK_DEFAULTS["temp"]
    finally:
        w.close()


def test_load_button_records_last_preset(env):
    _write_preset(env, "cfg1", {"temp": 0.33})
    w = _make_window(env)
    try:
        w._refresh_presets()
        w.preset_combo.setCurrentText("cfg1")
        w._load_preset()
        assert w.params["temp"] == 0.33
        assert CC.load_last_preset() == "cfg1"
    finally:
        w.close()


class _StubMsgBox:
    # Stub (not a subclass): the C++-bound static QMessageBox.question() does
    # not route through a Python exec() override, so faking the instance
    # would open a real modal dialog and hang the test.
    StandardButton = QMessageBox.StandardButton

    @staticmethod
    def question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes


def test_delete_last_preset_clears_pointer(env, monkeypatch):
    _write_preset(env, "cfg1", {"temp": 0.33})
    CC.save_last_preset("cfg1")
    w = _make_window(env)
    try:
        w._refresh_presets()
        w.preset_combo.setCurrentText("cfg1")
        monkeypatch.setattr(MW, "QMessageBox", _StubMsgBox)
        w._delete_preset()
        assert CC.load_last_preset() == ""
        assert w.preset_combo.count() == 0
    finally:
        w.close()


def test_preset_stored_keys_and_migration(env):
    _write_preset(env, "m", {
        "checkpoint_every_n_tokens": 100,   # renamed upstream
        "ctx_size_draft": 4096,             # dropped upstream
        "temp": 0.5,
    })
    cfg = CC.ConfigManager(defaults=dict(_FALLBACK_DEFAULTS))
    assert cfg.preset_stored_keys("m") == {"checkpoint_min_step", "temp"}
    assert cfg.preset_stored_keys("missing") is None
    (env / "bad.json").write_text("{not json", encoding="utf-8")
    assert cfg.preset_stored_keys("bad") is None


def test_last_preset_settings_roundtrip(env):
    assert CC.load_last_preset() == ""
    CC.save_last_preset("abc")
    assert CC.load_last_preset() == "abc"
    CC.save_last_preset("")
    assert CC.load_last_preset() == ""
