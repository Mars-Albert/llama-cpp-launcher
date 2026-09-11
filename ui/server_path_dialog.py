"""E1: server-path dialog — frameless themed card (E12 infrastructure).

The original was a plain native QDialog — the OS title bar (bright blue on
this Windows setup) clashed with the app theme, and the native focus ring
around the input looked even worse. The dialog now shares the E12
frameless chrome (``ui.frameless``): rounded card, drop shadow, icon +
title + close in the title bar. The card itself is a plain square-corner
rounded frame with a 1px theme border; all colours come from
``MainWindow._THEME_TEMPLATE`` (object names ``serverPath*``), so a live
light/dark switch restyles the dialog too.

Drag = title bar (``QWindow.startSystemMove`` — native feel, no rubber
banding); Esc = cancel, Enter = OK; the window is a fixed-size card, so
there is no resize border. QFileDialog for the 浏览 button stays native.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from core.i18n import t
from ui.frameless import FramelessDialog, app_icon


class ServerPathDialog(FramelessDialog):
    """Ask for the absolute path of llama-server. Empty = keep current.

    ``prefill``  — text to start in the edit (usually the explicit path
                   from settings, or the currently resolved one)
    ``resolved`` — what get_server_path() returned (shown in the hint
                   row; a bare "llama-server" gets a warning hint)
    """

    def __init__(self, parent, prefill: str, resolved: str,
                 theme: str = "dark"):
        super().__init__(
            parent,
            title=t("llama-server 路径"),
            icon=app_icon(),
            resizable=False,
            size=(600, 0),
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        lay = self.content_layout

        desc = QLabel(t(
            "输入 llama-server 可执行文件的完整路径；留空则保持当前设置不变。"))
        desc.setObjectName("serverPathDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setObjectName("serverPathEdit")
        self.edit.setPlaceholderText(t("例如: C:\\llama.cpp\\build\\bin\\llama-server.exe"))
        fixed_font = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPixelSize(13)
        self.edit.setFont(fixed_font)
        self.edit.setText(prefill)
        row.addWidget(self.edit, 1)

        browse = QPushButton(t("浏览…"))
        browse.setObjectName("serverPathBrowse")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)

        self.hint = QLabel()
        self._set_hint(resolved)
        lay.addWidget(self.hint)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        cancel = QPushButton(t("取消"))
        cancel.setObjectName("serverPathCancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        ok = QPushButton(t("确定"))
        ok.setObjectName("serverPathOk")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        footer.addWidget(ok)
        lay.addLayout(footer)

    # ------------------------------------------------------------- logic
    def path(self) -> str:
        return self.edit.text().strip()

    def _set_hint(self, resolved: str):
        warn = resolved == "llama-server" or not os.path.isfile(resolved)
        self.hint.setObjectName(
            "serverPathHintWarn" if warn else "serverPathHintOk")
        self.hint.setText(t("当前生效: {path}").format(path=resolved))
        if warn:
            self.edit.setPlaceholderText(
                t("未在 PATH 中找到 llama-server，请手动选择"))
        # Re-polish so the objectName (colour) change takes effect.
        style = self.hint.style()
        style.unpolish(self.hint)
        style.polish(self.hint)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("选择 llama-server 可执行文件"), "",
            "Executable (llama-server*) (*.exe llama-server);;All files (*)")
        if path:
            self.edit.setText(path)

    # -------------------------------------------------------- keyboard
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)  # base centers the frameless card
        self.edit.selectAll()
        self.edit.setFocus()
