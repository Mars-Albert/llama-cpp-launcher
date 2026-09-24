# -*- coding: utf-8 -*-
"""E15: right-column 3-tab layout (参数配置 / 日志输出 / 运行信息).

Regression for the 1080p report: the right column used to stack the
parameter area above a small bottom tab widget (日志输出 / 运行信息), so
on a 1080p screen (window ~940px tall) the log got only ~150-250px of
the column. E15 makes the whole right column one 3-tab widget, so every
tab owns the column's full height (~800px+).

Pinned here:
- the tab structure (3 tabs, order, content of each page) and the
  default tab (参数配置);
- the run-state indicator + runtime trailing the 参数配置 tab's control
  bar (E15 first moved them to the main status bar — reverted per user
  report, so the regression now pins the original spot);
- the ``right_tab`` ui pref: saved on state save, restored at startup,
  and the legacy pre-E15 ``bottom_tab`` value maps to +1 (0=日志输出→1,
  1=运行信息→2);
- Ctrl+F (``_show_log_search``) switches to the 日志输出 tab;
- the log tab owns the column's full height at a typical 1080p window
  size;
- E11 width self-lock defence, E15 variant: the outer tab widget's
  minimum width stays pinned to the fixed-content minimum when the
  quick grid re-wraps (if the grid's current column count leaked into
  the minimum, the window would self-lock wide and the re-wrap that
  raises the minimum height would never happen).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core.config as CC


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(CC, "SETTINGS_FILE", settings_file)
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr(CC, "PRESETS_DIR", presets_dir)
    yield settings_file


def _qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(temp_settings, prefs=None):
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    if prefs is not None:
        CC.save_ui_prefs(prefs)
    return MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))


def _settle(app, win, w, h):
    import time
    win.resize(w, h)
    for _ in range(12):
        app.processEvents()
        time.sleep(0.005)


def test_right_column_is_three_tabs(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        assert w.tab_widget.count() == 3
        # 参数配置 is the default tab; then the two former bottom tabs
        assert w.tab_widget.currentIndex() == 0
        assert w.tab_widget.tabText(0) == "⚙️ 参数配置"
        assert w.tab_widget.tabText(1) == "📄 日志输出"
        assert w.tab_widget.tabText(2) == "📊 运行信息"
        # the pre-E15 stacked blocks live in the 参数配置 page — the
        # parameter area and the command preview are separated by a
        # draggable vertical QSplitter (E15 follow-up, user request 2026-10)
        assert w.mode_combo.parent() is w.params_tab
        assert w.cmd_split.parent() is w.params_tab
        assert w.cmd_split.widget(0) is w.panel_scroll
        assert w.cmd_split.widget(1) is w.cmd_box
        # the preview + its caption live in the splitter's bottom box; the
        # extra-height stretch stays on the preview side (panel side = 0)
        assert w.cmd_label.parent() is w.cmd_box
        assert w.cmd_preview.parent() is w.cmd_box
        assert w.btn_start.parent() is w.params_tab
        assert w.btn_stop.parent() is w.params_tab
        # the log page carries the log editor + search bar + toolbar
        assert w.log_output.parent() is w.log_tab
        assert w.log_search_bar.parent() is w.log_tab
        assert w.btn_export_log.parent() is w.log_tab
        # 运行信息 is added directly as a page (parented to the tab
        # widget's internal stack)
        from PyQt6.QtWidgets import QStackedWidget
        assert isinstance(w.info_display.parent(), QStackedWidget)
        assert w.info_display.parent().parent() is w.tab_widget
    finally:
        w.close()


def test_run_state_labels_trail_control_bar(temp_settings):
    """⏸/▶ state + ⏱ runtime trail the 参数配置 tab's control bar (after
    the drift button) and do NOT live in the main status bar. E15 first
    moved them into the status bar — reverted per user report (the
    status-bar area rendered wrong on their machine), so the regression
    pins the original control-bar spot."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        # both labels are children of the 参数配置 page and trail the
        # control bar (right of the drift button)
        assert w.status_indicator.parent() is w.params_tab
        assert w.run_time_label.parent() is w.params_tab
        assert w.status_indicator not in w.statusBar().findChildren(object)
        assert w.run_time_label not in w.statusBar().findChildren(object)
        w.show()
        _settle(app, w, w.minimumWidth(), w.minimumHeight())
        assert w.drift_button.x() < w.status_indicator.x() < w.run_time_label.x()
        # the status bar itself carries only the transient message label
        msg = w.statusBar().findChild(type(w.status_indicator), "statusMsg")
        assert msg is not None
    finally:
        w.close()


def test_right_tab_persisted_and_restored(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.tab_widget.setCurrentIndex(2)
        w._save_ui_state()
        prefs = CC.load_ui_prefs()
        assert prefs["right_tab"] == 2
        assert "bottom_tab" not in prefs
    finally:
        w.close()

    w2 = _window(temp_settings, prefs={"right_tab": 1})
    try:
        assert w2.tab_widget.currentIndex() == 1
    finally:
        w2.close()

    # legacy pre-E15 bottom_tab maps to +1 (0=日志输出→1, 1=运行信息→2)
    w3 = _window(temp_settings, prefs={"bottom_tab": 1})
    try:
        assert w3.tab_widget.currentIndex() == 2
    finally:
        w3.close()


def test_cmd_split_persisted_and_restored(temp_settings):
    """The draggable parameter/preview split (E15 follow-up) persists as
    ui.cmd_split and is restored on the next launch (showEvent retry).
    Also pins the stretch behaviour: extra column height flows to the
    preview side (the panel keeps its natural height)."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        for _ in range(15):
            app.processEvents()
        # extra height (250px over the minimum) must land on the preview
        # side — the panel side stays at its natural height
        w.resize(w.minimumWidth(), w.minimumHeight() + 250)
        for _ in range(12):
            app.processEvents()
        default = list(w.cmd_split.sizes())
        assert default[1] > 200  # the preview absorbed the extra
        # user drag: panel side +100 / preview side -100 (both sides stay
        # above their own minimums — dragging the preview side below its
        # floor, or the panel below its E11 natural minimum, clamps)
        w.cmd_split.setSizes([default[0] + 100, default[1] - 100])
        for _ in range(8):
            app.processEvents()
        w._save_ui_state()
        prefs = CC.load_ui_prefs()
        assert len(prefs["cmd_split"]) == 2
        assert prefs["cmd_split"][1] < default[1]  # the shrunken preview side
        saved = list(prefs["cmd_split"])
        saved_geo = [0, 0, w.width(), w.height()]
    finally:
        w.close()

    # relaunch at the SAME window size (saved geometry) so the saved split
    # total fits the splitter's total exactly (a smaller window would
    # correctly clamp each side to its own minimum, like the main splitter)
    w2 = _window(temp_settings, prefs={"cmd_split": saved,
                                       "geometry": saved_geo})
    try:
        w2.show()
        for _ in range(30):
            app.processEvents()
        assert getattr(w2, "_pending_cmd_split", None) is None  # retry consumed it
        sizes = w2.cmd_split.sizes()
        assert abs(sizes[1] - saved[1]) <= 20  # the preview side restored
    finally:
        w2.close()


def test_show_log_search_switches_to_log_tab(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.tab_widget.setCurrentIndex(0)
        w._show_log_search()
        assert w.tab_widget.currentIndex() == 1
        assert not w.log_search_bar.isHidden()
    finally:
        w.close()


def test_log_tab_gets_full_column_height(temp_settings):
    """The whole point of E15: at a typical 1080p window size the 日志
    output tab owns the column's full height (pre-E15 it was the
    ~150-250px leftover below the stacked parameter area)."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        _settle(app, w, 1360, 860)
        w.tab_widget.setCurrentIndex(1)
        _settle(app, w, 1360, 860)
        # the log editor fills the tab page (page margins are 0)
        assert w.log_output.height() >= 600, (
            f"log editor only {w.log_output.height()}px tall at 1360x860")
    finally:
        w.close()


def test_tab_min_width_excludes_quick_grid_columns(temp_settings):
    """E11 width self-lock defence, E15 variant: when the quick-toggles
    grid re-wraps (1 row → 2 rows) the window minimum HEIGHT must follow
    (E11 option A) while the outer tab widget's minimum WIDTH must stay
    pinned to the fixed-content minimum — if the grid's current column
    count leaked into it, the window would self-lock wide and the
    re-wrap would never happen."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        bp = w.basic_panel
        seven = ("mmproj_offload", "flash_attn", "spec_type", "draft_max",
                 "cache_type_k", "cache_type_v", "fit")
        _settle(app, w, 1360, w.minimumHeight())
        bp.set_quick_params(list(seven))
        _settle(app, w, 1360, w.minimumHeight())
        rows_wide = bp._quick_rows_used
        min_w_wide = w.tab_widget.minimumWidth()
        min_h_wide = w.minimumHeight()
        # narrow the window: the grid may re-wrap and the window minimum
        # height follows it (E11 option A)
        _settle(app, w, w.minimumWidth(), w.height())
        assert bp._quick_rows_used >= max(2, rows_wide)
        assert w.minimumHeight() >= min_h_wide
        # the tab minimum width must NOT have followed the column count
        assert w.tab_widget.minimumWidth() == min_w_wide, (
            f"width self-lock: tab min width {min_w_wide} -> "
            f"{w.tab_widget.minimumWidth()} after the quick grid re-wrap")
    finally:
        w.close()
