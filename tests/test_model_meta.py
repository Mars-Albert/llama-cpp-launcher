"""Tests for the GGUF quick-metadata row in the model-info group (the
empty space left of the GGUF button): arch · max ctx, parsed off the
main thread, amber warning when the user-set context exceeds the
model's limit."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette

import core.config as CC
from core.defaults import _FALLBACK_DEFAULTS
from core.i18n import t
from gguf.parser import _quick_cache
import ui.main_window as MW
from tests.test_gguf import build_fake_gguf

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture
def window(tmp_path, monkeypatch):
    _quick_cache.clear()
    d = tmp_path / "presets"
    d.mkdir(parents=True)
    monkeypatch.setattr(CC, "PRESETS_DIR", d)
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    app = _qapp()  # keep a live reference
    w = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    yield w
    w.close()


def _wait_meta_done(window, timeout_s=5.0):
    """Spin the event loop until the meta row leaves the 'parsing' state."""
    pending = t("正在解析...")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if window.model_meta_label.text() != pending:
            return
        _qapp().processEvents()
        time.sleep(0.01)
    pytest.fail("model-meta row stuck in the parsing state")


def _write_model(tmp_path, name="model.gguf", metadata=None):
    p = tmp_path / name
    with open(p, "wb") as f:
        f.write(build_fake_gguf(metadata=metadata or {}))
    return p


def test_meta_row_shows_arch_ctx(window, tmp_path):
    p = _write_model(tmp_path, metadata={
        "general.architecture": "qwen3",
        "general.name": "Qwen3-4B",
        "qwen3.context_length": 40960,
    })
    window._on_model_selected(str(p))  # sets the combo, then _update_model_info
    _wait_meta_done(window)
    text = window.model_meta_label.text()
    assert "qwen3" in text
    assert "40,960" in text
    # idle color (gray, same as the scan-status row), not the amber warning
    assert window.model_meta_label.palette().color(QPalette.ColorRole.Text).name() == "#565f89"


def test_meta_row_ctx_exceeds_model_limit_warns(window, tmp_path):
    p = _write_model(tmp_path, metadata={
        "general.architecture": "llama",
        "llama.context_length": 4096,
    })
    # real user flow: raise ctx in the spinbox, then pick the model — the
    # preview timer syncs widget state into self.params, so the values set
    # this way are the ones _render_model_meta sees
    window.basic_panel.ctx_spin.setValue(8192)
    window._on_model_selected(str(p))
    _wait_meta_done(window)
    expected = t("⚠ 当前设置的上下文 {ctx} 超过模型上限 {max}（启动后会被截断）",
                 ctx="8,192", max="4,096")
    assert expected in window.model_meta_label.toolTip()
    color = window.model_meta_label.palette().color(QPalette.ColorRole.Text).name()
    assert color == "#d97706"  # amber warning
    # dropping back to a legal ctx restores the idle color
    window.basic_panel.ctx_spin.setValue(4096)
    _wait_meta_done(window)
    assert window.model_meta_label.palette().color(QPalette.ColorRole.Text).name() == "#565f89"
    assert window.model_meta_label.toolTip() == window.model_meta_label.text()


def test_meta_row_missing_model_shows_dash(window):
    window._update_model_meta("")
    assert window.model_meta_label.text() == "—"
    window._update_model_meta("/nonexistent/definitely-not.gguf")
    assert window.model_meta_label.text() == "—"


def test_meta_row_stale_parse_dropped(window, tmp_path):
    """Switching models while a parse is in flight must not let the stale
    result win: the seq guard drops it and the second model's info shows."""
    pa = _write_model(tmp_path, "a.gguf",
                      metadata={"general.architecture": "archaaa",
                                "archaaa.context_length": 1024})
    pb = _write_model(tmp_path, "b.gguf",
                      metadata={"general.architecture": "archbbb",
                                "archbbb.context_length": 2048})
    window._update_model_meta(str(pa))
    window._update_model_meta(str(pb))  # immediately supersede
    _wait_meta_done(window)
    text = window.model_meta_label.text()
    assert "archbbb" in text
    assert "archaaa" not in text
