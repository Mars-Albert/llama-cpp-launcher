"""Tests for the E3 log panel features: level filter, search, full run log.

The ``gguf/``-style offscreen approach: these need Qt, so they run under
QT_QPA_PLATFORM=offscreen (set in conftest or CI).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

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
    # header + 3 complete lines (an unterminated line would stay in _log_tail)
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
