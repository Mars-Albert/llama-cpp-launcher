"""Tests for E7: version info in the About dialog + clickable drift notice."""
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
def window(tmp_path, monkeypatch):
    d = tmp_path / "presets"
    d.mkdir(parents=True)
    monkeypatch.setattr(CC, "PRESETS_DIR", d)
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    app = _qapp()  # keep a live reference
    w = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    yield w
    w.close()


def test_version_result_stored_and_shown(window):
    window._on_version_result("0.4.0", "abc1234", "llama-server version 0.4.0 (build 10825)")
    assert window._server_version_line == "llama-server version 0.4.0 (build 10825)"
    assert "v0.4.0" in window.version_label.text()
    assert window.drift_button.isHidden() is True  # defaults == fallback: no drift


def test_drift_button_hidden_when_matching(window):
    window.defaults = dict(_FALLBACK_DEFAULTS)
    window._validate_params()
    assert window.drift_button.isHidden() is True
    assert window._drift_missing == [] and window._drift_changed == []


class _FakeMsgBox:
    """Records ThemedMessageBox calls — the real box (E12) would open a
    modal dialog and hang the offscreen test. Plain class: the main
    window only calls the API methods below."""
    instances = []

    def __init__(self, parent=None, *a, **kw):
        self._text = ""
        self._detailed = ""
        self._title = ""
        _FakeMsgBox.instances.append(self)

    def setWindowTitle(self, title):
        self._title = title

    def setIcon(self, icon):
        pass

    def setText(self, text):
        self._text = text

    def setDetailedText(self, text):
        self._detailed = text

    def setStandardButtons(self, buttons):
        pass

    def exec(self):
        return QMessageBox.StandardButton.Ok

    def deleteLater(self):
        pass

    def text(self):
        return self._text

    def detailedText(self):
        return self._detailed


def test_drift_button_shown_and_dialog_lists_all(window, monkeypatch):
    defaults = dict(_FALLBACK_DEFAULTS)
    del defaults["temp"]            # missing key
    defaults["top_p"] = 0.99        # changed key
    defaults["repeat_penalty"] = 1.9  # changed key
    window.defaults = defaults
    window._validate_params()

    assert window.drift_button.isHidden() is False
    assert "temp" in window._drift_missing
    keys = {k for k, _, _ in window._drift_changed}
    assert {"top_p", "repeat_penalty"} <= keys

    _FakeMsgBox.instances.clear()
    monkeypatch.setattr(MW, "ThemedMessageBox", _FakeMsgBox)
    window._show_drift_dialog()
    assert len(_FakeMsgBox.instances) == 1
    box = _FakeMsgBox.instances[0]
    assert "temp" in box.detailedText()
    assert "top_p" in box.detailedText()
    assert "repeat_penalty" in box.detailedText()


def test_about_dialog_includes_version(window, monkeypatch):
    window._on_version_result("0.4.0", "abc1234", "llama-server version 0.4.0 (build 10825)")
    _FakeMsgBox.instances.clear()
    monkeypatch.setattr(MW, "ThemedMessageBox", _FakeMsgBox)
    window._show_about()
    box = _FakeMsgBox.instances[-1]
    assert "0.4.0" in box.text()
