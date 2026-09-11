"""E12: themed replacement for QMessageBox.

QMessageBox uses the native frame (bright blue title bar on this
Windows setup) and clashes with the app theme, so every message box is
now a frameless themed card (``ui.frameless.FramelessDialog``) with a
compact icon + text + button layout that mirrors QMessageBox semantics:

- ``ThemedMessageBox.warning/critical/information(parent, title, text)``
  return the clicked ``QMessageBox.StandardButton`` (always Ok).
- ``ThemedMessageBox.question(parent, title, text, Yes | No)`` returns
  the clicked StandardButton; Esc activates the reject-role button, so
  it returns No — same as QMessageBox.
- ``ThemedMessageBox(parent)`` + ``setIcon/setText/setDetailedText/
  setStandardButtons/addButton(...)/clickedButton()`` covers the
  custom boxes (about, parameter drift, export scope).

Only the StandardButtons the app actually uses (Ok / Cancel / Yes / No)
are mapped; ``addButton`` accepts arbitrary roles (ActionRole etc.) and
``clickedButton()`` returns the actual button, exactly like the native
box. Chrome/button styling lives in ``MainWindow._THEME_TEMPLATE``
(object names ``msgBox*``).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QTextEdit,
    QVBoxLayout,
)

from core.i18n import t
from ui.frameless import FramelessDialog, app_icon


class ThemedMessageBox(FramelessDialog):
    """Frameless themed message box with QMessageBox-compatible API."""

    _GLYPHS = {
        QMessageBox.Icon.Information: "\u2139",   # ℹ
        QMessageBox.Icon.Warning: "\u26A0",       # ⚠
        QMessageBox.Icon.Critical: "\u2716",      # ✖
        QMessageBox.Icon.Question: "?",
    }
    _GLYPH_NAMES = {
        QMessageBox.Icon.Information: "msgBoxIconInfo",
        QMessageBox.Icon.Warning: "msgBoxIconWarn",
        QMessageBox.Icon.Critical: "msgBoxIconCritical",
        QMessageBox.Icon.Question: "msgBoxIconQuestion",
    }

    # (StandardButton, label KEY, role) in Windows order. The text is
    # resolved lazily — this module is imported before main.py applies
    # the persisted language, so a class-body t() would freeze the
    # startup language.
    _STD_BUTTONS = (
        (QMessageBox.StandardButton.Ok, "确定",
         QMessageBox.ButtonRole.AcceptRole),
        (QMessageBox.StandardButton.Cancel, "取消",
         QMessageBox.ButtonRole.RejectRole),
        (QMessageBox.StandardButton.Yes, "是",
         QMessageBox.ButtonRole.AcceptRole),
        (QMessageBox.StandardButton.No, "否",
         QMessageBox.ButtonRole.RejectRole),
    )

    def __init__(self, parent, icon=QMessageBox.Icon.NoIcon,
                 title: str = "", text: str = ""):
        super().__init__(
            parent,
            title=title or t("提示"),
            icon=app_icon(),
            resizable=False,
            size=(480, 0),
        )
        self._clicked_btn = None
        self._roles = {}          # button -> role
        self._std_for = {}        # button -> StandardButton

        row = QHBoxLayout()
        row.setSpacing(14)
        icon_lbl = QLabel()
        icon_lbl.setObjectName(self._GLYPH_NAMES.get(icon, "msgBoxIconInfo"))
        icon_lbl.setFixedWidth(30)
        row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        self._icon_lbl = icon_lbl
        self._icon = icon

        col = QVBoxLayout()
        col.setSpacing(8)
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(420)
        self._text_lbl = QLabel(text)
        self._text_lbl.setObjectName("msgBoxText")
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setTextFormat(Qt.TextFormat.AutoText)
        scroll.setWidget(self._text_lbl)
        col.addWidget(scroll)

        self._detail = QTextEdit()
        self._detail.setObjectName("msgBoxDetail")
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(220)
        self._detail.setVisible(False)
        col.addWidget(self._detail)
        row.addLayout(col, 1)
        self.content_layout.addLayout(row)

        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(8)
        self._btn_row.addStretch(1)
        self.content_layout.addLayout(self._btn_row)

        self._update_icon()

    # -------------------------------------------------------------- API
    def setIcon(self, icon):
        self._icon = icon
        self._update_icon()

    def _update_icon(self):
        glyph = self._GLYPHS.get(self._icon)
        self._icon_lbl.setText(glyph or "")
        name = self._GLYPH_NAMES.get(self._icon, "msgBoxIconInfo")
        if self._icon_lbl.objectName() != name:
            self._icon_lbl.setObjectName(name)
            style = self._icon_lbl.style()
            style.unpolish(self._icon_lbl)
            style.polish(self._icon_lbl)

    def setText(self, text: str):
        self._text_lbl.setText(text)

    def setDetailedText(self, text: str):
        self._detail.setPlainText(text)
        self._detail.setVisible(bool(text))

    def setStandardButtons(self, buttons):
        for std, key, role in self._STD_BUTTONS:
            if int(buttons) & int(std):
                self.addButton(t(key), role, std=std)

    def addButton(self, text: str, role, std=None):
        btn = QPushButton(text)
        accept = role == QMessageBox.ButtonRole.AcceptRole
        btn.setObjectName("msgBoxBtnAccept" if accept else "msgBoxBtn")
        btn.clicked.connect(lambda _=False, b=btn: self._on_button(b))
        self._btn_row.addWidget(btn)
        self._roles[btn] = role
        if std is not None:
            self._std_for[btn] = std
        if accept:
            btn.setDefault(True)
            btn.setFocus()
        return btn

    def clickedButton(self):
        return self._clicked_btn

    def _clicked_std(self):
        if self._clicked_btn is not None:
            std = self._std_for.get(self._clicked_btn)
            if std is not None:
                return std
        return QMessageBox.StandardButton.Ok

    def _on_button(self, btn):
        self._clicked_btn = btn
        role = self._roles.get(btn)
        if role == QMessageBox.ButtonRole.AcceptRole:
            self.accept()
        elif role == QMessageBox.ButtonRole.RejectRole:
            self.reject()
        else:  # ActionRole — just close, the caller uses clickedButton()
            self.done(0)

    def accept(self):
        # Enter / default button with no explicit click: report the
        # accept-role button so static helpers return the right code.
        if self._clicked_btn is None:
            for btn, role in self._roles.items():
                if role == QMessageBox.ButtonRole.AcceptRole:
                    self._clicked_btn = btn
        super().accept()

    def reject(self):
        # Esc: report the reject-role button (No / Cancel).
        if self._clicked_btn is None:
            for btn, role in self._roles.items():
                if role == QMessageBox.ButtonRole.RejectRole:
                    self._clicked_btn = btn
        super().reject()

    # -------------------------------------------------------- statics
    @classmethod
    def _run(cls, parent, icon, title, text, standard=None):
        box = cls(parent, icon=icon, title=title, text=text)
        if standard is not None:
            box.setStandardButtons(standard)
        box.exec()
        result = box._clicked_std()
        box.deleteLater()
        return result

    @classmethod
    def warning(cls, parent, title: str, text: str):
        return cls._run(parent, QMessageBox.Icon.Warning, title, text,
                        QMessageBox.StandardButton.Ok)

    @classmethod
    def critical(cls, parent, title: str, text: str):
        return cls._run(parent, QMessageBox.Icon.Critical, title, text,
                        QMessageBox.StandardButton.Ok)

    @classmethod
    def information(cls, parent, title: str, text: str):
        return cls._run(parent, QMessageBox.Icon.Information, title, text,
                        QMessageBox.StandardButton.Ok)

    @classmethod
    def question(cls, parent, title: str, text: str,
                 standard_buttons=QMessageBox.StandardButton.Yes
                 | QMessageBox.StandardButton.No):
        return cls._run(parent, QMessageBox.Icon.Question, title, text,
                        standard_buttons)
