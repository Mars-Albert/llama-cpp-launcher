"""E1 follow-up: the themed frameless server-path dialog (ui/server_path_dialog.py).

Renders the dialog offscreen and pins its structure and behaviour:
prefill, the effective-path hint (ok vs warn), the empty placeholder,
accept/reject via the custom buttons, and construction under both themes.

Note: the QApplication is created by the module-scoped ``app`` fixture,
the same pattern the other UI test files use — the pinned PyQt6 build
crashes when a test body constructs QApplication through an extra Python
frame, so keep it in the fixture.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import core.i18n as I
from ui.server_path_dialog import ServerPathDialog


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def _by_name(dlg, name):
    return next(w for w in dlg.findChildren(object) if w.objectName() == name)


def test_dialog_structure_and_prefill(app, tmp_path):
    from PyQt6.QtCore import Qt
    fake = tmp_path / "llama-server.exe"
    fake.write_bytes(b"x")
    dlg = ServerPathDialog(None, str(fake), str(fake), "dark")
    try:
        # E12: shared frameless card chrome + server-path-specific parts
        assert dlg.objectName() == "framelessDialog"
        assert dlg.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert dlg.windowTitle() == I.t("llama-server 路径")
        assert dlg.path() == str(fake)
        for name in ("framelessCard", "titleBarTitle", "titleBarCloseBtn",
                     "serverPathDesc", "serverPathEdit", "serverPathBrowse",
                     "serverPathOk", "serverPathCancel"):
            _by_name(dlg, name)
        # path() strips whitespace
        le = _by_name(dlg, "serverPathEdit")
        le.setText("  " + str(fake) + "  ")
        assert dlg.path() == str(fake)
        # effective-path hint is the "ok" variant and shows the path
        hint = next(w for w in dlg.findChildren(object) if w.objectName().startswith("serverPathHint"))
        assert hint.objectName() == "serverPathHintOk"
        assert str(fake) in hint.text()
    finally:
        dlg.deleteLater()


def test_dialog_warns_when_nothing_found(app):
    dlg = ServerPathDialog(None, "", "llama-server", "light")
    try:
        hint = next(w for w in dlg.findChildren(object) if w.objectName().startswith("serverPathHint"))
        assert hint.objectName() == "serverPathHintWarn"
        le = _by_name(dlg, "serverPathEdit")
        assert le.placeholderText() == I.t("未在 PATH 中找到 llama-server，请手动选择")
        assert le.text() == ""
    finally:
        dlg.deleteLater()


def test_buttons_accept_reject(app):
    from PyQt6.QtWidgets import QDialog
    dlg = ServerPathDialog(None, "C:/x/llama-server.exe", "C:/x/llama-server.exe", "dark")
    try:
        ok = _by_name(dlg, "serverPathOk")
        assert ok.isDefault()
        ok.clicked.emit()
        assert dlg.result() == QDialog.DialogCode.Accepted
        assert dlg.path() == "C:/x/llama-server.exe"

        dlg2 = ServerPathDialog(None, "", "llama-server", "dark")
        _by_name(dlg2, "serverPathCancel").clicked.emit()
        assert dlg2.result() == QDialog.DialogCode.Rejected
        dlg3 = ServerPathDialog(None, "", "llama-server", "dark")
        _by_name(dlg3, "titleBarCloseBtn").clicked.emit()
        assert dlg3.result() == QDialog.DialogCode.Rejected
        dlg2.deleteLater()
        dlg3.deleteLater()
    finally:
        dlg.deleteLater()


def test_dialog_constructs_under_both_themes(app):
    for theme in ("dark", "light"):
        dlg = ServerPathDialog(None, "C:/x/llama-server.exe", "C:/x/llama-server.exe", theme)
        assert dlg.width() == 600
        assert dlg.height() > 100
        dlg.deleteLater()


def test_en_language_translates_dialog(app):
    original = I.get_language()
    try:
        I.set_language("en")
        dlg = ServerPathDialog(None, "", "llama-server", "dark")
        try:
            assert dlg.windowTitle() == "llama-server path"
            assert _by_name(dlg, "titleBarTitle").text() == "llama-server path"
        finally:
            dlg.deleteLater()
    finally:
        I.set_language(original)
