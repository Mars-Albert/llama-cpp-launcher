# -*- coding: utf-8 -*-
"""Offscreen UI tests for the '?' parameter help buttons + floating card.

Runs under QT_QPA_PLATFORM=offscreen (same pattern as test_log_panel.py).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication, QLabel

from core.i18n import get_language, set_language, t
from core.params_help import HELP_TEXTS, has_help
from core.params_schema import PARAMS_BY_KEY, UI_PARAMS
from ui.advanced_panel import AdvancedPanel
from ui.basic_panel import BasicPanel
from ui.param_help import show_param_help


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture()
def lang():
    prev = get_language()
    yield
    set_language(prev)


def _open_cards(app):
    # Only VISIBLE cards count: a previously closed card lingers in
    # topLevelWidgets() (and its order there is not creation order).
    return [w for w in app.topLevelWidgets()
            if w.objectName() == "ParamHelpPopup" and w.isVisible()]


def _open_card(app, btn):
    btn.show()
    btn.clicked.emit()
    cards = _open_cards(app)
    assert cards, "help card did not open"
    return cards[-1]


def _card_text(card):
    return "\n".join(lbl.text() for lbl in card.findChildren(QLabel))


def test_advanced_panel_help_button_count(app):
    panel = AdvancedPanel(defaults={})
    expected = sum(1 for p in UI_PARAMS if has_help(p.key))
    # +1: the composite ngl row (helper spin row) also carries the
    # n_gpu_layers explanation.
    assert len(panel._help_btns) == expected + 1


def test_basic_panel_help_button_count(app):
    panel = BasicPanel(defaults={})
    # model, mmproj, ngl, ctx, temp, top_p, top_k, min_p, repeat_penalty,
    # host, port, parallel, webui, verbose, flash_attn, reasoning,
    # split_mode, spec_type, draft_max
    assert len(panel._help_btns) == 19


def test_help_card_content_and_i18n(app, lang):
    panel = BasicPanel(defaults={"temp": 0.9})
    btn = panel._help_btns[0]  # first row = model

    card = _open_card(app, btn)
    text = _card_text(card)
    assert t("模型 (--model)") in text
    card.close()

    set_language("en")
    panel.retranslate_ui()
    assert btn.toolTip() == "View parameter description"
    card = _open_card(app, btn)
    text = _card_text(card)
    assert "Model (--model)" in text
    card.close()


def test_help_card_shows_default_value(app, lang):
    panel = BasicPanel(defaults={"temp": 0.9})
    # Button order: model, mmproj, ngl, ctx, temp -> index 4.
    temp_btn = panel._help_btns[4]
    card = _open_card(app, temp_btn)
    text = _card_text(card)
    assert t("温度 (--temp):") in text
    assert t("默认: {val}", val="0.9") in text
    assert t("范围: {r}", r="0 – 2") in text
    card.close()


def test_show_param_help_noop_without_text(app):
    panel = BasicPanel(defaults={})
    n0 = len(_open_cards(app))
    show_param_help("nonexistent_param", panel)
    n1 = len(_open_cards(app))
    assert n0 == n1


def test_help_covers_all_params(app):
    # Full corpus: every schema parameter has an explanation.
    missing = [k for k in PARAMS_BY_KEY if not has_help(k)]
    assert not missing, f"params missing help: {missing}"


def test_help_card_follows_dark_theme(app, monkeypatch):
    """Regression: the card used to force the palette window color (always
    light), so dark mode showed light text on a light card. It must use the
    current theme's card colors (mirroring MainWindow._THEME_PALETTES)."""
    from PyQt6.QtWidgets import QToolButton
    from core.defaults import _FALLBACK_DEFAULTS
    from ui import main_window as mw

    monkeypatch.setattr("ui.param_help.load_theme", lambda: "dark")
    prev_qss = app.styleSheet()
    app.setStyleSheet(mw.MainWindow._get_stylesheet("dark"))
    panel = BasicPanel(defaults=_FALLBACK_DEFAULTS)
    try:
        before = {id(w) for w in _open_cards(app)}
        btn = next(b for b in panel.findChildren(QToolButton)
                   if b.text() == "?")
        btn.click()
        app.processEvents()
        new = [w for w in _open_cards(app) if id(w) not in before]
        assert new, "no visible help card in dark theme"
        assert "#1e1e2e" in new[0].styleSheet()  # dark card background
    finally:
        app.setStyleSheet(prev_qss)
        panel.close()
