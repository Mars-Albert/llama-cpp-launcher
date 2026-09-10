# -*- coding: utf-8 -*-
"""E11: small-window layout — no compressed/overlapping controls.

Regression for: "在窗体尺寸比较小时，控件会被压缩并重叠". Before the fix the
window's setMinimumSize (1100x700) was *below* the content's layout minimum
(1201x861 on the dev host), so at the smallest allowed window size the
parameter rows were squashed to a few pixels and controls were drawn on top
of each other.

The fix (see ui/main_window.py / ui/basic_panel.py, plan E11, option A):
- the basic parameter panel carries a hard minimum height equal to its
  natural height, and the window minimum follows it — the window can never
  be resized into a state that squashes the rows. The parameter area
  therefore has no vertical scrollbar at all (per user decision: rows keep
  full height, the window simply cannot shrink below the content);
- the window minimum height is computed as the sum of the right column's
  children minimums (+ menu/status bars, central margins): the plain
  minimumSizeHint() under-reports the scroll area's explicit minimum, and
  the stretchy log-tab area would otherwise absorb the deficit by squashing
  the panel;
- when the quick-toggles grid re-wraps to more rows (the window was
  narrowed), MainWindow reacts on the panel viewport's resize event (before
  the panel's own layout pass) and re-syncs the hard minimums in the same
  pass — the window grows if the current height no longer fits, so an extra
  grid row never "borrows" height from the 模型设置 group; the grid's row
  count drives an *explicit* minimum height on its host widget (arithmetic,
  always live — Qt's layout-minimum caches lag one event-loop pass behind a
  re-wrap), and the panel's minimum is summed item-by-item from the
  groups' minimumSizeHint() for the same reason;
- the panel still lives in a QScrollArea for the horizontal direction only
  (vertical bar AlwaysOff): very narrow windows scroll the fixed rows
  sideways instead of clipping them;
- the quick-toggles grid re-wraps (BasicPanel._quick_cols, capped at ≥2
  columns) and the column count is chosen by the grid's *natural* width
  (every label shown in full, not the shrunken-label minimum); each
  column's minimum width is pinned to its widest slot's natural width so
  no label can be clipped at any window width — if even 2 natural-width
  columns exceed the viewport the grid scrolls horizontally instead;
- the scrollable content carries a hard minimum width (fixed groups only),
  so fixed rows scroll horizontally instead of clipping.

This test renders the real window offscreen at the minimum size (plus a few
typical sizes, both modes) and asserts that no two *visible* widgets overlap.
Visibility is computed against scroll-area viewports: content that is
scrolled out of view is clipped by Qt and must not be counted.
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


def _window(temp_settings):
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    return MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))


def _visible_rect(win, w, client):
    """Global rect of w, clipped by the window and every ancestor
    scroll-area viewport (scrolled-out content is not visible)."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QAbstractScrollArea

    r = QRect(w.mapTo(win, w.rect().topLeft()), w.rect().size())
    r = r.intersected(client)
    p = w.parentWidget()
    while p is not None:
        if isinstance(p, QAbstractScrollArea):
            vp = p.viewport()
            r = r.intersected(QRect(
                vp.mapTo(win, vp.rect().topLeft()), vp.rect().size()))
        p = p.parentWidget()
    return r


def _overlaps(win):
    """Pairs of visible leaf widgets (labels, buttons, inputs, ...) whose
    visible rects overlap by >= 4x4 px. Sibling widgets in a healthy layout
    are separated by layout spacing, so 0 is expected."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QWidget

    client = QRect(0, 0, win.width(), win.height())

    def is_leaf(w):
        return not any(c.isVisible() and c.rect().width() > 0
                       and c.rect().height() > 0
                       for c in w.findChildren(QWidget))

    leaves = []
    for w in win.findChildren(QWidget):
        if not w.isVisible() or w.rect().width() <= 0 or w.rect().height() <= 0:
            continue
        if not is_leaf(w):
            continue
        vr = _visible_rect(win, w, client)
        if not vr.isNull():
            leaves.append((w, vr))

    bad = []
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            a, ra = leaves[i]
            b, rb = leaves[j]
            inter = ra.intersected(rb)
            if (inter.width() >= 4 and inter.height() >= 4
                    and a not in b.children() and b not in a.children()):
                bad.append((a, b, inter))
    return bad


def _settle(app, win, w, h):
    import time
    win.resize(w, h)
    for _ in range(12):
        app.processEvents()
        time.sleep(0.005)


def _quick_label_clips(win):
    """Quick-toggle slots whose label text cannot be fully displayed (the
    slot/label is narrower than its natural sizeHint). The column count
    and the per-column natural-width minimums must keep this empty at
    every legal window width (E11)."""
    bad = []
    for p, w, lbl in win.basic_panel._quick_items:
        target = w if lbl is None else lbl  # check: text is inside the box
        if target.width() < target.sizeHint().width() - 2:
            bad.append((p.key, target.width(), target.sizeHint().width()))
    return bad


def test_window_minimum_covers_content_minimum(temp_settings):
    """The window must never be resizable smaller than what the content
    actually needs — that mismatch is exactly what caused the overlap."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        _settle(app, w, w.minimumWidth(), w.minimumHeight())
        hint = w.minimumSizeHint()
        assert w.minimumWidth() >= hint.width() - 2
        assert w.minimumHeight() >= hint.height() - 2
        # the static floors are still respected
        from core.constants import MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
        assert w.minimumWidth() >= MIN_WINDOW_WIDTH
        assert w.minimumHeight() >= MIN_WINDOW_HEIGHT
    finally:
        w.close()


def test_no_overlapping_controls_at_small_sizes(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        sizes = [
            (w.minimumWidth(), w.minimumHeight()),   # smallest possible
            (1100, 700),                              # the old (broken) min
            (1360, 860),                              # default size
        ]
        for mode in (0, 1):  # basic / advanced
            w.mode_combo.setCurrentIndex(mode)
            for sw, sh in sizes:
                _settle(app, w, sw, sh)
                bad = _overlaps(w)
                assert not bad, (
                    f"mode={mode} size={sw}x{sh}: overlapping controls: "
                    + "; ".join(f"{type(a).__name__} x {type(b).__name__} "
                                f"({inter.width()}x{inter.height()})"
                                for a, b, inter in bad[:5]))
    finally:
        w.close()


def test_panel_never_vertically_squashed(temp_settings):
    """E11 design (user decision: no vertical scrollbar on the parameter
    area): the basic panel carries a hard minimum height equal to its
    natural height and the window minimum follows it — so at every legal
    window size the panel keeps its full height and no vertical scrollbar
    is ever needed."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        for size in ((w.minimumWidth(), w.minimumHeight()), (1100, 700), (1360, 860)):
            _settle(app, w, *size)
            ps = w.panel_scroll
            panel = w.basic_panel
            # rows are never squashed: the panel keeps its full natural height
            assert panel.height() >= panel.layout().minimumSize().height() - 2, (
                f"size={size}: panel squashed to {panel.height()}px "
                f"(needs {panel.layout().minimumSize().height()}px)")
            # the panel fits the viewport — no vertical scrollbar, no clipping
            assert not ps.verticalScrollBar().isVisible()
            assert ps.viewport().height() >= panel.height() - 2
            # quick-toggle labels are never clipped by their column
            assert not _quick_label_clips(w), (
                f"size={size}: clipped quick-toggle labels: "
                f"{[(k, wd, hint) for k, wd, hint in _quick_label_clips(w)]}")
        # the quick-toggles grid never wraps below 2 columns
        assert w.basic_panel._quick_cols() >= 2
    finally:
        w.close()


def test_quick_grid_rewrap_never_squashes_groups(temp_settings):
    """E11 option A regression (user screenshot): with 7 quick toggles the
    grid wraps 1 -> 2 rows when the window is narrowed; the extra row must
    not 'borrow' height from the 模型设置 group. The window minimum must
    follow the re-wrap (and the window grow) so every group keeps its full
    height at every width."""
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
        cols_wide = bp._quick_cols_used
        assert cols_wide >= 2
        # every label is fully visible (not just the controls)
        assert not _quick_label_clips(w), (
            f"wide: clipped quick-toggle labels: {_quick_label_clips(w)}")
        # narrow the window horizontally: the grid may re-wrap (fewer
        # columns, more rows) and the window minimum follows it
        _settle(app, w, w.minimumWidth(), w.height())
        assert bp._quick_rows_used >= 2
        assert not _quick_label_clips(w), (
            f"narrow: clipped quick-toggle labels: {_quick_label_clips(w)}")
        for group in (bp._model_group, bp._sampling_group,
                      bp._server_group, bp._toggles_group):
            need = group.minimumSizeHint().height()
            assert group.height() >= need - 2, (
                f"group '{group.title()}' squashed to {group.height()}px "
                f"(needs {need}px)")
        assert not w.panel_scroll.verticalScrollBar().isVisible()
        assert not _overlaps(w)
    finally:
        w.close()


def test_quick_labels_survive_retranslate(temp_settings):
    """E11 (round 3): a language switch changes the labels' natural
    widths; the per-column minimums must be refreshed so no label is
    clipped in either language (and groups stay unsquashed)."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        seven = ("mmproj_offload", "flash_attn", "spec_type", "draft_max",
                 "cache_type_k", "cache_type_v", "fit")
        w.basic_panel.set_quick_params(list(seven))
        _settle(app, w, 1180, w.minimumHeight())
        from core import i18n
        for lang in ("en", "zh", "en", "zh"):
            i18n.set_language(lang)
            w.retranslate_ui()
            _settle(app, w, 1180, w.minimumHeight())
            assert not _quick_label_clips(w), (
                f"lang={lang}: clipped quick-toggle labels: "
                f"{_quick_label_clips(w)}")
            for group in (w.basic_panel._model_group,
                          w.basic_panel._sampling_group,
                          w.basic_panel._server_group,
                          w.basic_panel._toggles_group):
                assert group.height() >= group.minimumSizeHint().height() - 2
    finally:
        w.close()
