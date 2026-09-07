"""Tests for the E4 GGUF Inspector 'open any file' feature (offscreen Qt)."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication

# reuse the in-memory fake GGUF builder from the stdlib test suite
sys.path.insert(0, os.path.dirname(__file__))
from test_gguf import build_fake_gguf

import ui.gguf_inspector as gi
from ui.gguf_inspector import GGUFInspectorDialog

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _make_gguf(tmp_path, name, metadata=None):
    p = tmp_path / name
    p.write_bytes(build_fake_gguf(metadata=metadata))
    return str(p)


def _wait_parsed(d, timeout_s=15):
    app = _qapp()
    deadline = time.time() + timeout_s
    while d._info is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert d._info is not None, "parse did not finish in time"


@pytest.fixture
def app():
    return _qapp()


def test_open_button_adds_file_to_selector(app, tmp_path):
    a = _make_gguf(tmp_path, "a.gguf", {"general.name": "ModelA"})
    b = _make_gguf(tmp_path, "b.gguf", {"general.name": "ModelB"})

    d = GGUFInspectorDialog(a)
    try:
        _wait_parsed(d)
        assert d._btn_open is not None
        assert d._model_selector.count() == 1
        assert "a.gguf" in d.windowTitle()

        # E4: add the second file through the same path the button uses
        d._add_file_option(b)
        app.processEvents()
        _wait_parsed(d)
        assert d._model_selector.count() == 2
        assert d._model_selector.currentIndex() == 1
        assert "b.gguf" in d.windowTitle()
        assert d._info is not None
    finally:
        d.close()


def test_open_dedupes_existing_file(app, tmp_path):
    a = _make_gguf(tmp_path, "a.gguf")
    d = GGUFInspectorDialog(a)
    try:
        _wait_parsed(d)
        # adding the same file again must not duplicate the entry
        d._add_file_option(a)
        app.processEvents()
        assert d._model_selector.count() == 1
        assert d._model_selector.currentIndex() == 0
    finally:
        d.close()


def test_open_file_dialog_feeds_selector(app, tmp_path, monkeypatch):
    a = _make_gguf(tmp_path, "a.gguf")
    b = _make_gguf(tmp_path, "b.gguf")
    d = GGUFInspectorDialog(a)
    try:
        _wait_parsed(d)
        monkeypatch.setattr(gi.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *args, **kwargs: (b, "GGUF Files (*.gguf)")))
        d._open_file_dialog()
        app.processEvents()
        _wait_parsed(d)
        assert d._model_selector.count() == 2
        assert "b.gguf" in d.windowTitle()
    finally:
        d.close()


def test_open_dialog_cancel_is_noop(app, tmp_path, monkeypatch):
    a = _make_gguf(tmp_path, "a.gguf")
    d = GGUFInspectorDialog(a)
    try:
        _wait_parsed(d)
        monkeypatch.setattr(gi.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *args, **kwargs: ("", "")))
        d._open_file_dialog()
        app.processEvents()
        assert d._model_selector.count() == 1
    finally:
        d.close()
