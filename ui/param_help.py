# -*- coding: utf-8 -*-
"""Lightweight floating help card for one parameter (the "?" buttons).

Shown by the small "?" buttons next to parameter labels in the basic and
advanced panels. It is a non-modal Qt.Popup: it closes automatically when
the user clicks anywhere outside it (or presses Esc).

Content = schema facts (label/flag via p.label, default value, range) +
the explanation from core.params_help. The default is taken from the
live-parsed llama-server --help defaults when available, so the card
always matches the actual server version.
"""
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from core.config import load_theme
from core.i18n import t
from core.params_help import help_text, has_help
from core.params_schema import PARAMS_BY_KEY

_CARD_WIDTH = 420      # max card width (incl. margins)
_BODY_MAX_HEIGHT = 300  # body area height before the card gets a scrollbar
_MARGIN = 12           # card inner margin

# Card colors per theme. Mirrors MainWindow._THEME_PALETTES so the popup
# stays in sync with the app theme: the app QSS only cascades text color,
# the card's own background/border must be set explicitly per theme (the
# widget palette is always the default light one, which broke dark mode).
_THEME_COLORS = {
    "light": {"bg": "#f0f2f5", "border": "#9ca3af", "muted": "#6b7280"},
    "dark": {"bg": "#1e1e2e", "border": "#45475a", "muted": "#7f849c"},
}


def _fmt_default(val) -> str:
    """Render a default value for the meta line."""
    if isinstance(val, bool):
        return t("开启") if val else t("关闭")
    if val is None or val == "" or val == [] or val == {}:
        return t("未设置")
    return str(val)


class ParamHelpPopup(QFrame):
    """One parameter's help card, positioned next to its "?" button."""

    def __init__(self, param_key: str, anchor: QWidget,
                 defaults: dict | None = None):
        super().__init__(anchor)
        self.setObjectName("ParamHelpPopup")
        self.setWindowFlags(Qt.WindowType.Popup)
        self._c = _THEME_COLORS["dark" if load_theme() == "dark" else "light"]
        self._build(param_key, defaults or {})
        self._style()

    # -- content ---------------------------------------------------------
    def _build(self, param_key: str, defaults: dict):
        p = PARAMS_BY_KEY[param_key]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(6)

        # Title: the schema label already carries the CLI flag,
        # e.g. 温度 (--temp)
        title = QLabel(t(p.label))
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Meta line: default value + range (when the widget has one)
        meta = _fmt_default(defaults.get(p.key, p.default))
        parts = [t("默认: {val}", val=meta)]
        if p.widget in ("spin", "dspin") and p.min is not None and p.max is not None:
            lo = f"{p.min:g}" if p.step else str(p.min)
            hi = f"{p.max:g}" if p.step else str(p.max)
            parts.append(t("范围: {r}", r=f"{lo} – {hi}"))
        meta_lbl = QLabel(" · ".join(parts))
        meta_lbl.setStyleSheet(
            f"color: {self._c['muted']}; font-size: 12px;")
        layout.addWidget(meta_lbl)

        # Explanation body (scrolls when long)
        body = QLabel(t(help_text(param_key)))
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Minimum)
        # A comfortable minimum card width; the label grows up to the
        # card max before wrapping harder or scrolling.
        body.setMinimumWidth(280)
        body.setMaximumWidth(_CARD_WIDTH - 2 * _MARGIN)
        ideal_h = body.sizeHint().height()
        if ideal_h > _BODY_MAX_HEIGHT:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setFixedHeight(_BODY_MAX_HEIGHT)
            scroll.setWidget(body)
            layout.addWidget(scroll)
        else:
            layout.addWidget(body)

    def _style(self):
        self.setStyleSheet(
            "#ParamHelpPopup {"
            f"  background: {self._c['bg']};"
            f"  border: 1px solid {self._c['border']};"
            "  border-radius: 8px;"
            "}"
        )

    # -- positioning -----------------------------------------------------
    def show_at(self, anchor: QWidget):
        """Show the card next to the anchor, clamped to the screen."""
        self.adjustSize()
        scr = QApplication.screenAt(anchor.mapToGlobal(QPoint(0, 0))) \
            or QApplication.primaryScreen()
        avail = scr.availableGeometry()
        a_left = anchor.mapToGlobal(anchor.rect().topLeft())
        a_right = anchor.mapToGlobal(anchor.rect().topRight())
        w, h = self.width(), self.height()

        # Prefer the right side of the anchor; flip to the left near the
        # right screen edge.
        x = a_right.x() + 8
        if x + w > avail.right() - 4:
            x = a_left.x() - w - 8
        x = max(avail.left() + 4, min(x, avail.right() - w - 4))

        y = a_left.y() + 2
        if y + h > avail.bottom() - 4:
            y = max(avail.top() + 4, avail.bottom() - h - 4)

        self.move(int(x), int(y))
        self.show()


def make_help_button(param_key: str, get_defaults,
                     parent: QWidget | None = None) -> QToolButton:
    """Small '?' button; clicking shows the help card next to it.

    get_defaults: zero-arg callable returning the live defaults dict
    (usually ``lambda: self._defaults`` on the panel).
    """
    btn = QToolButton(parent)
    btn.setText("?")
    btn.setToolTip(t("查看参数说明"))
    btn.setFixedSize(16, 16)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        "QToolButton { border: none; padding: 0; font-size: 11px;"
        " font-weight: 700; color: #6b7280; border-radius: 8px; }"
        " QToolButton:hover { color: #2563eb;"
        " background: rgba(37, 99, 235, 0.10); }"
    )
    btn.clicked.connect(lambda checked=False, b=btn:
                        show_param_help(param_key, b, get_defaults()))
    return btn


def show_param_help(param_key: str, anchor: QWidget,
                    defaults: dict | None = None):
    """Show the help card for param_key next to anchor; no-op without text."""
    if not has_help(param_key):
        return
    ParamHelpPopup(param_key, anchor, defaults=defaults).show_at(anchor)
