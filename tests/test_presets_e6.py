"""Tests for the E6 preset enhancements (config level + save dialog)."""
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog

import core.config as CC
from core.config import ConfigManager
from core.defaults import _FALLBACK_DEFAULTS
import ui.main_window as MW

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture
def presets_dir(tmp_path, monkeypatch):
    d = tmp_path / "presets"
    d.mkdir(parents=True)  # _ensure_dirs() is one-shot per process; create it ourselves
    monkeypatch.setattr(CC, "PRESETS_DIR", d)
    return d


def test_list_presets_prefers_json_created(presets_dir):
    f = presets_dir / "old.preset.json"
    f.write_text(json.dumps({
        "name": "old.preset", "version": 1,
        "created": "2020-01-02T03:04:05", "params": {},
    }), encoding="utf-8")
    # make the mtime clearly different from the JSON created field
    import os as _os
    _os.utime(f, (1_700_000_000, 1_700_000_000))
    presets = ConfigManager(dict(_FALLBACK_DEFAULTS)).list_presets()
    assert presets[0]["created"] == "2020-01-02T03:04:05"


def test_list_presets_falls_back_to_mtime(presets_dir):
    f = presets_dir / "legacy.json"
    f.write_text(json.dumps({"name": "legacy", "params": {}}), encoding="utf-8")
    import os as _os
    _os.utime(f, (1_700_000_000, 1_700_000_000))
    presets = ConfigManager(dict(_FALLBACK_DEFAULTS)).list_presets()
    assert presets[0]["created"].startswith("2023-11")  # 1.7e9 ≈ 2023-11-14 UTC-ish


def test_overwrite_keeps_created(presets_dir):
    cfg = ConfigManager(dict(_FALLBACK_DEFAULTS))
    assert cfg.save_preset("mine", {"port": 9999})
    first_created = cfg.list_presets()[0]["created"]
    time.sleep(0.01)
    assert cfg.save_preset("mine", {"port": 8888})  # overwrite
    assert cfg.list_presets()[0]["created"] == first_created


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


class _FakeSaveDialog(QDialog):
    """Accepts automatically; tests may flip the checkbox before accept."""
    include_paths = True

    def exec(self):
        for c in self.findChildren(QCheckBox):
            c.setChecked(_FakeSaveDialog.include_paths)
        return QDialog.DialogCode.Accepted


def _save_via_dialog(w, monkeypatch, include_paths, name="testpreset"):
    _FakeSaveDialog.include_paths = include_paths
    monkeypatch.setattr(MW, "QDialog", _FakeSaveDialog)
    # the fake dialog prefills its name field from the combo's current text,
    # so select/insert the target name first
    if w.preset_combo.findText(name) < 0:
        w.preset_combo.addItem(name)
    w.preset_combo.setCurrentIndex(w.preset_combo.findText(name))
    w._save_preset()  # monkeypatch restores MW.QDialog after the test


def test_save_dialog_includes_model_paths(window, monkeypatch):
    # C3: set values through the proper path (widget round-trip stays consistent)
    window._set_current_values({"model": "C:/fake/model.gguf", "port": 9999})
    _save_via_dialog(window, monkeypatch, include_paths=True, name="withpaths")
    data = json.loads((CC.PRESETS_DIR / "withpaths.json").read_text(encoding="utf-8"))
    assert data["params"].get("model") == "C:/fake/model.gguf"
    assert data["params"].get("port") == 9999


def test_save_dialog_without_paths_drops_model(window, monkeypatch):
    window._set_current_values({"model": "C:/fake/model.gguf", "port": 9999})
    _save_via_dialog(window, monkeypatch, include_paths=False, name="nopath")
    data = json.loads((CC.PRESETS_DIR / "nopath.json").read_text(encoding="utf-8"))
    assert "model" not in data["params"]
    assert "mmproj" not in data["params"]
    assert data["params"].get("port") == 9999  # non-path params still saved


def test_preset_created_hint_in_statusbar(window):
    cfg = ConfigManager(dict(_FALLBACK_DEFAULTS))
    cfg.save_preset("hintme", {"port": 7777})
    window._refresh_presets()
    # select the preset -> the status bar shows its creation time
    idx = window.preset_combo.findText("hintme")
    window.preset_combo.setCurrentIndex(idx)
    msg = window.statusBar().currentMessage()
    assert "hintme" in msg
    assert "创建" in msg
