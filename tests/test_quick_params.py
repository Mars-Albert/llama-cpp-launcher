# -*- coding: utf-8 -*-
"""E10: configurable quick toggles (快捷开关).

Covers the pool/sanitize logic, the schema-driven BasicPanel rebuild,
value flow through get_values()/set_values(), the customize dialog, and
settings persistence. UI parts run under QT_QPA_PLATFORM=offscreen
(same pattern as test_param_help_ui.py / test_ui_prefs.py).
"""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import core.config as CC

from core.i18n import get_language, set_language
from core.params_schema import PARAMS_BY_KEY
from ui.basic_panel import BasicPanel
from ui.quick_params import (
    QUICK_DEFAULT_KEYS, quick_eligible, quick_pool_keys,
    quick_short_label, sanitize_quick_keys,
)
from ui.quick_params_dialog import QuickParamsDialog


# ---------------------------------------------------------------------------
# Pool / sanitize (pure logic)
# ---------------------------------------------------------------------------

def test_pool_contains_default_five():
    pool = quick_pool_keys()
    assert set(QUICK_DEFAULT_KEYS) <= pool


def test_pool_excludes_basic_owned_keys():
    pool = quick_pool_keys()
    for k in ("model", "mmproj", "n_gpu_layers", "ctx_size",
              "temp", "top_p", "top_k", "min_p", "repeat_penalty",
              "host", "port", "parallel", "webui", "verbose"):
        assert k not in pool, k


def test_pool_only_single_line_kinds():
    for p in quick_eligible():
        assert p.widget in ("check", "combo", "combo_index", "spin",
                            "dspin", "combo_edit")
        if p.widget == "combo_edit":
            assert p.items is not None
    pool = quick_pool_keys()
    assert "chat_template" not in pool   # dynamic items
    assert "load_mode" in pool           # static items
    assert "jinja" in pool
    assert "threads" in pool


def test_sanitize_keeps_order_drops_invalid_and_dupes():
    assert sanitize_quick_keys(
        ["flash_attn", "bogus", "flash_attn", "jinja"]) == ["flash_attn", "jinja"]


def test_sanitize_empty_or_all_invalid_returns_default():
    assert sanitize_quick_keys([]) == list(QUICK_DEFAULT_KEYS)
    assert sanitize_quick_keys(["nope", ("x",), None]) == list(QUICK_DEFAULT_KEYS)
    assert sanitize_quick_keys(None) == list(QUICK_DEFAULT_KEYS)


def test_short_label_strips_flag_suffix():
    p = PARAMS_BY_KEY["flash_attn"]
    assert quick_short_label(p) == "Flash Attention"
    assert "(" not in quick_short_label(PARAMS_BY_KEY["draft_max"])


def test_quick_label_text_translates_cjk_labels(lang):
    """_EN keys are the FULL schema labels (incl. the `(--flag):` suffix),
    so quick_label_text must translate before stripping — stripping first
    missed every lookup and leaked Chinese into English mode (the ⚡
    quick-toggles group and the 自定义快捷开关 dialog)."""
    from ui.quick_params import quick_label_text
    p = PARAMS_BY_KEY["image_min_tokens"]
    set_language("zh")
    assert quick_label_text(p) == "图像最小Token"
    set_language("en")
    assert quick_label_text(p) == "Image Min Tokens"
    # no CJK anywhere in the pool in English mode
    cjk = re.compile(r"[\u4e00-\u9fff]")
    for p in quick_eligible():
        assert not cjk.search(quick_label_text(p)), p.key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture()
def lang():
    prev = get_language()
    yield
    set_language(prev)


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(CC, "SETTINGS_FILE", settings_file)
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr(CC, "PRESETS_DIR", presets_dir)
    yield settings_file


# ---------------------------------------------------------------------------
# BasicPanel: rebuild + value flow
# ---------------------------------------------------------------------------

def test_default_quick_keys(app, lang):
    p = BasicPanel()
    assert p.get_quick_params() == list(QUICK_DEFAULT_KEYS)
    vals = p.get_values()
    for k in QUICK_DEFAULT_KEYS:
        assert k in vals
    # the static basic-panel keys are untouched
    for k in ("model", "mmproj", "n_gpu_layers", "ctx_size", "temp",
              "top_p", "top_k", "min_p", "repeat_penalty", "host", "port",
              "parallel", "webui", "verbose"):
        assert k in vals


def test_rebuild_and_value_flow(app, lang):
    p = BasicPanel()
    p.set_quick_params(["jinja", "threads", "flash_attn"])
    assert p.get_quick_params() == ["jinja", "threads", "flash_attn"]
    vals = p.get_values()
    assert {"jinja", "threads", "flash_attn"} <= set(vals)
    # dropped keys are no longer reported by the panel (their values stay in
    # MainWindow.params, untouched)
    for k in ("reasoning", "split_mode", "spec_type", "draft_max"):
        assert k not in vals
    # write/read round-trip through the set_values contract
    p.set_values({"jinja": False, "threads": 8, "flash_attn": "on"})
    v = p.get_values()
    assert v["jinja"] is False
    assert v["threads"] == 8
    assert v["flash_attn"] == "on"


def test_rebuild_then_fill_from_full_params_dict(app, lang):
    """MainWindow applies the full params dict after a rebuild — new slots
    must pick up their values (combo_index reads an int)."""
    p = BasicPanel()
    p.set_quick_params(["log_verbosity", "mirostat"])
    p.set_values({"log_verbosity": 5, "mirostat": 1})
    v = p.get_values()
    assert v["log_verbosity"] == 5
    assert v["mirostat"] == 1


def test_set_values_corrupt_value_skipped_not_fatal(app, lang):
    p = BasicPanel()
    p.set_quick_params(["threads", "jinja"])
    p.set_values({"threads": "not-a-number"})  # per-key fallback path
    assert -1 <= p.get_values()["threads"] <= 256
    p.set_values({"threads": 12})
    assert p.get_values()["threads"] == 12


def test_set_quick_params_sanitizes(app, lang):
    p = BasicPanel()
    p.set_quick_params(["bogus", "flash_attn"])
    assert p.get_quick_params() == ["flash_attn"]
    p.set_quick_params(["bogus"])  # all invalid -> default set
    assert p.get_quick_params() == list(QUICK_DEFAULT_KEYS)


def test_set_quick_params_noop_on_same_list(app, lang):
    p = BasicPanel()
    before = len(p._quick_items)
    p.set_quick_params(list(QUICK_DEFAULT_KEYS))
    assert len(p._quick_items) == before  # not rebuilt


def test_retranslate_english(app, lang):
    set_language("en")
    p = BasicPanel()
    p.set_quick_params(["flash_attn", "jinja"])
    p.retranslate_ui()
    labels = [lbl.text() for _p, _w, lbl in p._quick_items if lbl is not None]
    assert "Flash Attention" in labels
    assert p._toggles_group.title() == "⚡ Toggles"
    # the check slot carries its own text
    check = [w for _p, w, lbl in p._quick_items
             if lbl is None and w.text()]
    assert any("Jinja" in c.text() for c in check)


def test_show_with_wrapping_survives_layout_pass(app, lang):
    """The real layout pass (show + processEvents) must not crash — the
    pinned PyQt6 6.11 build kills the process in any Python QLayout
    subclass, so the slots use a plain QGridLayout instead."""
    p = BasicPanel()
    p.set_quick_params(["flash_attn", "reasoning", "split_mode", "spec_type",
                        "jinja", "threads", "log_verbosity", "mirostat"])
    p.resize(500, 400)
    p.show()
    app.processEvents()
    assert p._quick_cols() >= 1
    assert len(p._quick_boxes) == 8
    p.close()


def test_menu_structure_settings_help(app, lang):
    """Menu reorg (E10): 文件 / 设置 / 帮助. Quick-toggles customization, the
    language switch and the theme toggle all live in 设置; 帮助 keeps 关于."""
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    win = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        # E12: the menu bar moved into the menu-widget slot (title bar
        # above it); win.menuBar() now returns a detached default bar.
        titles = [a.text() for a in win._menubar.actions()]
        assert titles == ["文件", "设置", "帮助"]
        assert win.settings_menu.actions()[0] is win._quick_params_action
        assert win.settings_menu.actions()[0].text() == "自定义快捷开关…"
        assert win._action_zh in win.settings_menu.actions()
        assert win._action_en in win.settings_menu.actions()
        assert win._theme_action in win.settings_menu.actions()
        assert win._theme_action not in win.help_menu.actions()
        assert len(win.help_menu.actions()) == 1
        assert win.help_menu.actions()[0].text() == "关于"
        # no gear button left in the panel
        assert not hasattr(win.basic_panel, "_btn_quick_customize")
    finally:
        win.close()


def test_menu_customize_quick_toggles(app, lang, temp_settings):
    """设置 → 自定义快捷开关… opens the dialog; OK updates the panel,
    persists ui.quick_params immediately, and backfills widget values."""
    from PyQt6.QtCore import Qt
    from unittest.mock import patch
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    from ui.quick_params_dialog import QuickParamsDialog
    win = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        captured = {}

        def fake_exec(self_dlg):
            # the window reads result_keys() inside exec(), so the test's
            # selection change must happen here, before returning Accepted
            captured["dlg"] = self_dlg
            win.params["jinja"] = True  # known value to backfill
            self_dlg._tree_items["jinja"].setCheckState(0, Qt.CheckState.Checked)
            return 1  # QDialog.DialogCode.Accepted

        with patch.object(QuickParamsDialog, "exec", fake_exec):
            win._quick_params_action.trigger()
        dlg = captured["dlg"]
        assert win.basic_panel.get_quick_params()[-1] == "jinja"
        assert CC.load_ui_prefs()["quick_params"] == win.basic_panel.get_quick_params()
        # backfill: the fresh jinja slot shows the params value (True)
        for p, w, _ in win.basic_panel._quick_items:
            if p.key == "jinja":
                assert w.isChecked() is True
    finally:
        win.close()


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

def _sel_row(dlg, key):
    from PyQt6.QtCore import Qt
    for i in range(dlg._sel.count()):
        if dlg._sel.item(i).data(Qt.ItemDataRole.UserRole) == key:
            return i
    return -1


def test_dialog_add_remove_and_order(app, lang):
    from PyQt6.QtCore import Qt
    d = QuickParamsDialog(None, list(QUICK_DEFAULT_KEYS))
    assert d.result_keys() == list(QUICK_DEFAULT_KEYS)

    # uncheck a default (fires _on_tree_changed)
    d._tree_items["reasoning"].setCheckState(0, Qt.CheckState.Unchecked)
    assert "reasoning" not in d.result_keys()

    # add a new one -> appended at the end
    d._tree_items["jinja"].setCheckState(0, Qt.CheckState.Checked)
    keys = d.result_keys()
    assert keys[-1] == "jinja"

    # move it up one slot via the left-pane button (it was at the end)
    d._sel.setCurrentRow(_sel_row(d, "jinja"))
    d._move_up()
    keys = d.result_keys()
    assert keys.index("jinja") == 3  # was 4 (last)

    # remove the current selection
    d._remove_sel()
    assert "jinja" not in d.result_keys()

    # unchecking removes from the tree too (both panes stay in sync)
    d._sel.setCurrentRow(_sel_row(d, "flash_attn"))
    d._remove_sel()
    assert d._tree_items["flash_attn"].checkState(0) == Qt.CheckState.Unchecked


def test_dialog_reset_default(app, lang):
    from PyQt6.QtCore import Qt
    d = QuickParamsDialog(None, ["jinja"])
    d._reset_default()
    assert d.result_keys() == list(QUICK_DEFAULT_KEYS)
    for k in QUICK_DEFAULT_KEYS:
        assert d._tree_items[k].checkState(0) == Qt.CheckState.Checked


def test_dialog_ok_disabled_when_empty(app, lang):
    from PyQt6.QtCore import Qt
    d = QuickParamsDialog(None, ["flash_attn"])
    assert d._ok.isEnabled()
    d._tree_items["flash_attn"].setCheckState(0, Qt.CheckState.Unchecked)
    assert not d._ok.isEnabled()


def test_dialog_search_filter(app, lang):
    d = QuickParamsDialog(None, list(QUICK_DEFAULT_KEYS))
    d._search.setText("flash")
    assert not d._tree_items["flash_attn"].isHidden()
    assert d._tree_items["split_mode"].isHidden()
    # a tab with no matches at all is hidden (agent tab has 2 params,
    # neither mentions "flash")
    agent_top = [it for it in d._top_items.values()
                 if it.text(0) in ("Agent/工具", "Agent/Tools")][0]
    assert agent_top.isHidden()
    # clearing restores everything
    d._search.setText("")
    assert not d._tree_items["split_mode"].isHidden()
    assert not agent_top.isHidden()


def test_dialog_labels_follow_language(app, lang):
    """Tree + left-pane labels render in the active language (regression:
    the stripped-label lookup leaked Chinese into the English dialog)."""
    set_language("en")
    d = QuickParamsDialog(None, ["image_min_tokens", "flash_attn"])
    assert d._tree_items["image_min_tokens"].text(0) == "Image Min Tokens"
    cjk = re.compile(r"[\u4e00-\u9fff]")
    for i in range(d._tree.topLevelItemCount()):
        top = d._tree.topLevelItem(i)
        for j in range(top.childCount()):
            assert not cjk.search(top.child(j).text(0)), top.child(j).text(0)
    for i in range(d._sel.count()):
        assert not cjk.search(d._sel.item(i).text())


def test_dialog_type_column_compact(app, lang):
    """The 类型/Type column keeps its natural width (short values:
    Toggle/Combo/Integer/Decimal) and the 参数 column absorbs the rest —
    QHeaderView's stretchLastSection (true by default) used to let the
    type column swallow all the spare width."""
    for mode in ("zh", "en"):
        set_language(mode)
        d = QuickParamsDialog(None, ["flash_attn"])
        d.resize(760, 520)
        d.show()
        app.processEvents()
        h = d._tree.header()
        assert not h.stretchLastSection()
        assert h.sectionSize(1) <= 160, "type column must stay compact"
        assert h.sectionSize(0) + h.sectionSize(1) >= d._tree.width() - 16
        if mode == "en":
            assert d._tree.headerItem().text(1) == "Type"
        d.close()
        d.deleteLater()


def test_dialog_nav_buttons_glyph_only_no_elision(app, lang):
    """The ▲/▼/✕ buttons are glyph-only 26×24 (log-search nav style):
    the full text (e.g. '▲ Move up') does not fit the row — text buttons
    elided in both languages (en '▲ ...up'). The single glyph must keep
    full room, the label lives in the tooltip, and the theme's
    #logSearchBtn rule must zero the QToolButton padding that would
    otherwise swallow the glyph. 恢复默认 shares the row (one action row
    instead of two half-empty rows) and must not be squeezed below its
    natural width (the pane is sized for en '🔄 Reset Default', 210px)."""
    import re
    from PyQt6.QtWidgets import QToolButton
    from ui import main_window as MW
    qss = MW.MainWindow._get_stylesheet("light")
    m = re.search(r"QToolButton#logSearchBtn[^{}]*\{([^}]*)\}", qss)
    assert m, "theme QSS lost the QToolButton #logSearchBtn rule"
    assert re.search(r"padding\s*:\s*0", m.group(1)), "padding must be zeroed"
    for mode in ("zh", "en"):
        set_language(mode)
        d = QuickParamsDialog(None, ["flash_attn"])
        d.resize(760, 520)
        d.show()
        app.processEvents()
        nav = [b for b in d.findChildren(QToolButton)
               if b.objectName() == "logSearchBtn"]
        assert len(nav) == 3
        for b in nav:
            assert b.width() == 26
            # 26px box minus 2px border must still fit the single glyph
            assert b.width() - 2 >= b.fontMetrics().horizontalAdvance(b.text())
            assert b.toolTip()
            # 恢复默认 shares the row (one action row, not two)
            assert b.parentWidget() is d._btn_default.parentWidget()
        assert d._btn_default.width() >= d._btn_default.sizeHint().width()
        # the pane hugs the row in both languages — no dead gap right of
        # 恢复默认 (3×26 glyphs + 3 gaps + default button + ≤16px headroom)
        pane = d._btn_default.parentWidget()
        used = 3 * 26 + 3 * 6 + d._btn_default.sizeHint().width()
        assert pane.width() - used <= 16
        d.close()
        d.deleteLater()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_save_ui_pref_roundtrip(temp_settings):
    CC.save_ui_prefs({"mode": 0, "adv_tab": 2})
    CC.save_ui_pref("quick_params", ["jinja", "flash_attn"])
    prefs = CC.load_ui_prefs()
    assert prefs["mode"] == 0          # untouched
    assert prefs["adv_tab"] == 2
    assert prefs["quick_params"] == ["jinja", "flash_attn"]


def test_save_ui_pref_creates_ui_dict(temp_settings):
    CC.save_ui_pref("quick_params", [])
    assert CC.load_ui_prefs() == {"quick_params": []}


def test_restore_window_quick_params(app, lang, temp_settings):
    """MainWindow restores ui.quick_params at startup (invalid keys are
    sanitized inside BasicPanel)."""
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    CC.save_ui_prefs({"quick_params": ["jinja", "bogus_key", "threads"]})
    win = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        assert win.basic_panel.get_quick_params() == ["jinja", "threads"]
    finally:
        win.close()


def test_save_window_ui_state_includes_quick_params(app, lang, temp_settings):
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    win = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        win.basic_panel.set_quick_params(["jinja", "draft_max"])
        win._save_ui_state()
        assert CC.load_ui_prefs()["quick_params"] == ["jinja", "draft_max"]
    finally:
        win.close()
