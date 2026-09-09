# -*- coding: utf-8 -*-
"""App window icon (title bar) resolution.

The PyInstaller spec `icon=` only writes the EXE's PE resource
(file-explorer / shortcut / taskbar-fallback); Qt's window title-bar icon
is applied at runtime via QApplication.setWindowIcon. These tests pin the
path resolution (frozen vs dev) and that the bundled ico actually loads.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def test_icon_path_dev():
    import main as main_mod
    p = main_mod._app_icon_path()
    expected = os.path.join(
        os.path.dirname(os.path.abspath(main_mod.__file__)), "assets", "icon.ico"
    )
    assert p == expected
    assert os.path.exists(p)


def test_icon_path_frozen(tmp_path, monkeypatch):
    import main as main_mod
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert main_mod._app_icon_path() == str(tmp_path / "assets" / "icon.ico")


def test_apply_app_icon_sets_window_icon(app):
    import main as main_mod
    main_mod._apply_app_icon(app)
    assert not app.windowIcon().isNull()
    # the ico is multi-size (16-256px), so the small title-bar size exists
    from PyQt6.QtGui import QIcon
    sizes = app.windowIcon().availableSizes(QIcon.Mode.Normal, QIcon.State.Off)
    assert any(s.width() <= 32 for s in sizes)


def test_spec_bundles_icon_dat_file():
    # guard against regressing the datas entry: without it, the frozen
    # icon path never exists and the title bar falls back to the Qt logo
    spec = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "llama_cpp_launcher.spec")
    text = open(spec, encoding="utf-8").read()
    assert "('assets/icon.ico', 'assets')" in text
