# -*- coding: utf-8 -*-
"""Regression test: the basic-mode browse buttons fit their text.

The button width used to be a hardcoded 80px, sized for the Chinese label
"📂 浏览". The English "📂 Browse" is wider — the emoji paints from a
fallback font whose glyphs are wider than the advance the primary font's
metrics report — so the last letter clipped in English mode.
_fit_browse_btn() now sizes the button to the translated text; this test
pins, for both languages, that the label fits inside the button's content
box (QSS padding 2×14 + border 2×1).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication

import core.i18n as I
from ui.basic_panel import BasicPanel


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def _content_width(btn):
    """Text width at the QSS pixel size (12px, see _THEME_TEMPLATE)."""
    f = QFont(btn.font())
    f.setPixelSize(12)
    return QFontMetrics(f).horizontalAdvance(btn.text())


def test_browse_buttons_fit_their_text(app):
    for lang in ("zh", "en"):
        I.set_language(lang)
        panel = BasicPanel()
        try:
            panel.retranslate_ui()
            app.processEvents()
            for name, btn in (
                ("model", panel._btn_browse_model),
                ("mmproj", panel._btn_browse_mmproj),
            ):
                # QSS padding (2×14) + border (2×1)
                need = _content_width(btn) + 30
                assert btn.width() >= need, (
                    f"{lang}/{name}: '{btn.text()}' needs {need}px, "
                    f"button is {btn.width()}px"
                )
        finally:
            I.set_language("zh")
            panel.deleteLater()
            app.processEvents()
