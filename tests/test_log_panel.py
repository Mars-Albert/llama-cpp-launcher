"""Tests for the E3 log panel features: level filter, search, full run log.

The ``gguf/``-style offscreen approach: these need Qt, so they run under
QT_QPA_PLATFORM=offscreen (set in conftest or CI).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QMainWindow

import core.config as CC
import ui.main_window as MW
from core.i18n import t

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture
def window(tmp_path, monkeypatch):
    """A MainWindow with the run-log files redirected to tmp_path."""
    logs_dir = tmp_path / "logs"
    last_run = logs_dir / "last_run.log"
    monkeypatch.setattr(CC, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(CC, "LAST_RUN_LOG", last_run)
    monkeypatch.setattr(MW, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(MW, "LAST_RUN_LOG", last_run)
    app = _qapp()  # keep a live reference; GC of the wrapper destroys the C++ app
    from core.defaults import _FALLBACK_DEFAULTS
    w = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    yield w
    w.close()


def _pump(app, ms=50):
    for _ in range(ms // 5):
        app.processEvents()
        time.sleep(0.005)


def test_level_filter_hides_and_restores(window):
    app = _qapp()
    w = window
    w._append_log("1.000 D debug line\n2.000 I info line\n3.000 W warn line\n4.000 E error line\n")
    w._flush_log_buffer()
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "debug line" in doc and "info line" in doc and "warn line" in doc

    # hide debug -> rebuild drops D lines only
    w._log_level_boxes["D"].setChecked(False)
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "debug line" not in doc
    assert "info line" in doc and "warn line" in doc and "error line" in doc

    # hide warnings too
    w._log_level_boxes["W"].setChecked(False)
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "warn line" not in doc and "info line" in doc

    # restore all -> fast path, everything back
    w._log_level_boxes["D"].setChecked(True)
    w._log_level_boxes["W"].setChecked(True)
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "debug line" in doc and "warn line" in doc and "info line" in doc


def test_all_filters_off_hides_banner_and_lines(window):
    """Unchecking every level yields an empty view — banners included."""
    app = _qapp()
    w = window
    w._log_banner("<span>banner text</span>")
    w._append_log("1.000 I info line\n")
    w._flush_log_buffer()
    _pump(app)
    assert "banner text" in w.log_output.toPlainText()

    for b in w._log_level_boxes.values():
        b.setChecked(False)
    _pump(app)
    assert w.log_output.toPlainText().strip() == ""

    # re-enabling one level brings the level lines back, but prefix-less
    # records (banners) stay hidden outside the unfiltered view
    w._log_level_boxes["I"].setChecked(True)
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "info line" in doc and "banner text" not in doc

    # all on again -> unfiltered view, banner and lines both visible
    for b in w._log_level_boxes.values():
        b.setChecked(True)
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "banner text" in doc and "info line" in doc


def test_prefix_less_noise_hidden_under_single_filter(window):
    """Server lines without a level prefix (blank lines, raw model I/O
    dumps) must not pollute a single-level filtered view, but remain in
    the unfiltered (all-on) view."""
    app = _qapp()
    w = window
    # prefix-less content: a blank line and a raw dump line full of commas
    w._append_log("1.000 I info line\n\n{\"a\": 1, \"b\": 2, \"c\": 3}\n")
    w._flush_log_buffer()
    _pump(app)
    doc = w.log_output.toPlainText()
    assert 'info line' in doc and '"a": 1, "b": 2' in doc

    # filter to info only -> the dump line and blank padding disappear
    for lvl, keep in (("D", False), ("W", False), ("E", False)):
        w._log_level_boxes[lvl].setChecked(keep)
    _pump(app)
    doc = w.log_output.toPlainText()
    assert 'info line' in doc
    assert '"a": 1' not in doc


def test_level_filter_fatal_follows_error(window):
    app = _qapp()
    w = window
    w._append_log("1.000 I info line\n2.000 F fatal line\n")
    w._flush_log_buffer()
    _pump(app)
    assert w._log_level_visible("F", {"I"}) is False
    assert w._log_level_visible("F", {"I", "E"}) is True
    # F lines are kept while all levels are on
    assert "fatal line" in w.log_output.toPlainText()


def test_flushes_do_not_glue_lines(window):
    """Each log line is its own block: lines from consecutive flushes must
    never be glued together, and the document block count is capped."""
    app = _qapp()
    w = window
    w._append_log("1.000 I line one\n2.000 I line two\n")
    w._flush_log_buffer()
    w._append_log("3.000 I line three\n4.000 I line four\n")
    w._flush_log_buffer()
    _pump(app)
    assert w.log_output.document().blockCount() == 4
    assert w.log_output.toPlainText() == (
        "1.000 I line one\n2.000 I line two\n3.000 I line three\n4.000 I line four"
    )


def test_log_document_block_cap(window):
    """Per-line blocks let setMaximumBlockCount actually trim the document."""
    app = _qapp()
    w = window
    cap = 5000
    for i in range(0, 5200, 200):
        w._append_log("\n".join(f"1.000 I l{i + j}" for j in range(200)) + "\n")
        w._flush_log_buffer()
    _pump(app)
    assert w.log_output.document().blockCount() == cap


def test_filter_keeps_new_lines_until_toggled(window):
    """Lines appended while a filter is active are filtered on next flush."""
    app = _qapp()
    w = window
    w._append_log("1.000 D old debug\n")
    w._flush_log_buffer()
    w._log_level_boxes["D"].setChecked(False)
    w._append_log("2.000 D new debug\n3.000 I new info\n")
    w._flush_log_buffer()
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "new debug" not in doc and "old debug" not in doc
    assert "new info" in doc


def test_toggle_during_output_pending_buffer(window):
    """Lines still buffered (100 ms flush pending) at toggle time must not be
    lost: the rebuild merges the buffer, and the pending timer then no-ops."""
    app = _qapp()
    w = window
    w._append_log("1.000 I info-1\n2.000 D debug-1\n")
    assert w._log_html and w._log_flush_timer.isActive()
    w._log_level_boxes["D"].setChecked(False)  # toggle mid-stream
    w._append_log("3.000 D debug-2\n4.000 I info-2\n")
    _pump(app, 150)  # >100 ms so the pending batch flush can land
    doc = w.log_output.toPlainText()
    assert "info-1" in doc and "info-2" in doc
    assert "debug-1" not in doc and "debug-2" not in doc
    w._log_level_boxes["D"].setChecked(True)
    _pump(app, 150)
    doc = w.log_output.toPlainText()
    assert all(s in doc for s in ("info-1", "debug-1", "debug-2", "info-2"))


def test_filter_doc_stays_in_sync_with_records(window):
    """While a filter is active, lines a level's window evicted must also
    leave the document (per-level front drop) — otherwise they linger and
    vanish all at once at the next toggle, which reads as “toggling loses
    lines”. After every settle the doc must be exactly: the shared global
    window (all-on) or the visible levels' own history windows merged in
    stream order (narrow filter)."""
    app = _qapp()
    w = window
    cap = 5000
    import heapq
    import re

    def norm(s):
        return re.sub(r"\s+", " ", s)

    def expected_visible(enabled):
        if w._log_filter_active():
            pools = [
                w._level_histories[lvl] for lvl in w._level_histories
                if w._log_level_visible(lvl, enabled)
            ]
            return [rec for _seq, rec in heapq.merge(*pools)]
        return list(w._log_records)

    def sync(tag):
        enabled = {lvl for lvl, b in w._log_level_boxes.items() if b.isChecked()}
        expected = [
            re.sub(r"<[^>]+>", "", h) for lvl, h in expected_visible(enabled)
        ]
        got = w.log_output.toPlainText().split("\n")
        assert len(got) == len(expected), f"[{tag}] doc {len(got)} != expected {len(expected)}"
        for g, e in zip(got, expected):
            assert norm(g) == norm(e), f"[{tag}] {g!r} != {e!r}"

    for i in range(0, cap + 1000, 500):
        w._append_log("\n".join(f"1.000 {'DIWE'[(i + j) % 4]} a{i + j}" for j in range(500)) + "\n")
        w._flush_log_buffer()
    w._log_level_boxes["I"].setChecked(False)
    w._log_level_boxes["D"].setChecked(False)
    sync("right after narrow filter")
    for k in range(3):
        w._append_log("\n".join(f"1.000 {'DIWE'[((cap + 1000 + k * 500) + j) % 4]} b{k}-{j}" for j in range(500)) + "\n")
        w._flush_log_buffer()
        sync(f"after stream {k}")
    # back to all on: every in-window line reappears, nothing stale remains
    w._log_level_boxes["I"].setChecked(True)
    w._log_level_boxes["D"].setChecked(True)
    sync("back to all on")
    assert len(w._log_records) == cap


def test_narrow_filter_not_starved_by_hidden_flood(window):
    """A flood of hidden levels (-lv 5 debug, prompt dumps) must not evict
    the visible level's lines out of its own window: with I-only on, every
    info line fed stays visible. (Old behaviour: the shared 5000-line window
    was eaten by the flood and the view shrank to a single print_timing line.)"""
    app = _qapp()
    w = window
    w._log_level_boxes["D"].setChecked(False)
    w._log_level_boxes["W"].setChecked(False)
    w._log_level_boxes["E"].setChecked(False)
    n_i = 0
    for i in range(12000):
        if i % 300 == 0:
            w._append_log(f"4.03.{i:06d} I slot print_timing: id  0 | task {i} | tg =  52.49 t/s\n")
            n_i += 1
        elif i % 7 == 0:
            w._append_log('{"prompt dump", "a": 1}\n')
        else:
            w._append_log(f"4.03.{i:06d} D srv  slot   0 debug detail\n")
        if i % 1000 == 999:
            w._flush_log_buffer()
    w._flush_log_buffer()
    _pump(app)
    doc = [l for l in w.log_output.toPlainText().split("\n") if l.strip()]
    assert len(doc) == n_i, f"I-only view starved: {len(doc)} of {n_i} info lines"
    # all-on still shows the shared 5000-line window
    for b in w._log_level_boxes.values():
        b.setChecked(True)
    _pump(app)
    assert len(w.log_output.toPlainText().split("\n")) == 5000


def test_whitespace_alignment_preserved(window):
    """appendHtml applies HTML whitespace rules (runs of spaces collapse);
    the pre span must keep llama.cpp's column alignment visible and in the
    exported/searchable text."""
    app = _qapp()
    w = window
    line = "1.000 I srv  slot   0 cmd (12 ms)  x"
    w._append_log(line + "\n")
    w._flush_log_buffer()
    _pump(app)
    assert line in w.log_output.toPlainText()
    # search with the original spacing works
    w._show_log_search()
    w.log_search_edit.setText("srv  slot   0")
    w._log_search_find(True)
    assert w.log_search_label.text() != t("未找到")


def test_cross_stream_lines_not_glued(window):
    """A half-line pending on one stream must not glue onto a line arriving
    from the other stream (that used to swallow a whole line)."""
    app = _qapp()
    w = window
    w._append_log("1.000 I stdout part", "out")   # no newline: pending on out
    w._append_log("2.000 W stderr line\n", "err")  # complete line on err
    w._append_log("stdout rest\n", "out")          # completes the out line
    w._flush_log_buffer()
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "2.000 W stderr line" in doc
    assert "1.000 I stdout part2.000 W stderr line" not in doc  # old glue bug
    assert "1.000 I stdout partstdout rest" in doc  # same-stream split rejoined


def test_flush_log_tail_empties_both_streams(window):
    app = _qapp()
    w = window
    w._append_log("1.000 I no newline out", "out")
    w._append_log("2.000 E no newline err", "err")
    w._flush_log_tail()  # process exit: both pending tails surface
    _pump(app)
    doc = w.log_output.toPlainText()
    assert "1.000 I no newline out" in doc
    assert "2.000 E no newline err" in doc
    assert w._log_tails == {"out": "", "err": ""}


def test_search_finds_counts_and_not_found(window):
    app = _qapp()
    w = window
    w._append_log("1.000 I hello world\n2.000 I hello again\n3.000 I nothing here\n")
    w._flush_log_buffer()
    _pump(app)

    w._show_log_search()
    # isHidden(): the fixture window is never shown(), so isVisible()
    # would stay False no matter what
    assert not w.log_search_bar.isHidden()
    assert w.tab_widget.currentIndex() == 0

    w.log_search_edit.setText("hello")
    w._log_search_find(True)
    _pump(app)
    assert w.log_search_label.text() == t("{n} 处匹配", n=2)
    # the found match is selected in the editor
    assert w.log_output.textCursor().selectedText() == "hello"

    # backward search (Shift+Enter path) wraps from the end and finds a match
    w.log_search_edit.setText("hello")
    w._log_search_find(False)
    _pump(app)
    assert w.log_output.textCursor().selectedText() == "hello"

    w.log_search_edit.setText("zzz-not-there")
    w._log_search_find(True)
    assert w.log_search_label.text() == t("未找到")

    w._hide_log_search()
    assert w.log_search_bar.isHidden()


def test_search_nav_buttons_keep_glyph_room(window):
    """The theme's generic QPushButton padding is 5px 14px — 28px of
    horizontal padding on a 26px-wide button leaves zero content width, so
    Qt renders the ▲/▼/✕ text as nothing (the "empty boxes" report). The
    #logSearchBtn rule must zero the padding, and the buttons must keep
    their objectName so the rule keeps applying."""
    import re
    qss = MW.MainWindow._get_stylesheet("light")
    m = re.search(r"QPushButton#logSearchBtn\s*{([^}]*)}", qss)
    assert m, "theme QSS lost the #logSearchBtn rule"
    assert re.search(r"padding\s*:\s*0", m.group(1)), "padding must be zeroed"
    for b in (window.btn_log_search_prev, window.btn_log_search_next,
              window.btn_log_search_close):
        assert b.objectName() == "logSearchBtn"
        # 26px box minus 2px border must still fit the single glyph
        assert b.width() - 2 >= b.fontMetrics().horizontalAdvance(b.text())


def test_search_key_events_shift_enter_backwards(window):
    """Real key events through the window's eventFilter: Shift+Enter must
    search backwards and be consumed, other keys must pass through — and
    none of them may raise (regression: PyQt5-style event.Key / event.Type
    access raised AttributeError on the first keypress under PyQt6)."""
    app = _qapp()
    w = window
    w._append_log("1.000 I hello one\n2.000 I middle\n3.000 I hello two\n")
    w._flush_log_buffer()
    _pump(app)
    w._show_log_search()
    w.log_search_edit.setText("hello")

    def sel_block():
        cur = w.log_output.textCursor()
        return w.log_output.document().findBlock(cur.selectionEnd()).blockNumber()

    # position the cursor on the second match (block 2)
    w._log_search_find(True)
    w._log_search_find(True)
    assert sel_block() == 2

    # Shift+Enter: real key event -> backwards search, consumed by the filter
    key = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier
    )
    assert w.eventFilter(w.log_search_edit, key) is True
    assert sel_block() == 0  # back to the first match
    assert w.log_search_label.text() == t("{n} 处匹配", n=2)

    # plain Enter and a character key pass through without raising
    assert w.eventFilter(
        w.log_search_edit,
        QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
        ),
    ) is False
    assert w.eventFilter(
        w.log_search_edit,
        QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier
        ),
    ) is False


def test_run_log_captures_command_and_lines(window, tmp_path):
    app = _qapp()
    w = window
    last_run = tmp_path / "logs" / "last_run.log"
    assert not last_run.exists()

    w._open_run_log("llama-server --model x.gguf")
    w._append_log("1.000 I line one\n2.000 D line two\n3.000 W line three\n")
    w._flush_log_buffer()
    _pump(app)
    w._close_run_log()

    assert last_run.exists()
    content = last_run.read_text(encoding="utf-8")
    assert "llama-server --model x.gguf" in content
    assert "line one" in content and "line two" in content and "line three" in content
    # header + 3 complete lines (an unterminated line would stay in _log_tails)
    assert content.count("\n") == 4


def test_run_log_write_failure_is_swallowed(window, monkeypatch):
    """A disk error must not propagate into the UI."""
    w = window
    w._open_run_log("cmd")
    assert w._run_log_file is not None
    monkeypatch.setattr(w._run_log_file, "write", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    # must not raise
    w._run_log_write("1.000 I boom")
    assert w._run_log_failed is True
    assert w._run_log_file is None
    w._run_log_write("1.000 I after failure")  # no-op, no raise


def test_export_view_only_without_full_log(window, tmp_path, monkeypatch):
    app = _qapp()
    w = window
    out = tmp_path / "export_view.txt"
    monkeypatch.setattr(
        MW.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "Text Files (*.txt)")),
    )
    w._append_log("1.000 I export me please\n")
    w._flush_log_buffer()
    _pump(app)
    w._export_log()
    assert out.exists()
    assert "export me please" in out.read_text(encoding="utf-8")


def test_export_full_copies_run_log(window, tmp_path, monkeypatch):
    app = _qapp()
    w = window
    last_run = tmp_path / "logs" / "last_run.log"
    w._open_run_log("cmd")
    w._append_log("1.000 I a\n2.000 I b\n3.000 I c\n4.000 I d\n5.000 I e\n")
    w._flush_log_buffer()
    w._close_run_log()
    # make the visible area smaller than the full file (document keeps 6 blocks
    # incl. empty; force the view to look shorter by clearing the display)
    w.log_output.clear()
    assert w._count_log_lines(last_run) > w.log_output.document().blockCount()

    out = tmp_path / "export_full.txt"
    monkeypatch.setattr(
        MW.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "Text Files (*.txt)")),
    )
    monkeypatch.setattr(w, "_ask_export_scope", lambda full_lines, view_lines: "full")
    w._export_log()
    assert out.exists()
    assert "1.000 I a" in out.read_text(encoding="utf-8")
