"""Log level filter under load: high-volume stream with toggles mid-stream
(buffer pending at toggle time).

Invariants verified after a 20k-line run with random toggles:
  * the shared global window loses nothing beyond the cap (tail-ordered),
    and each per-level window keeps its own tail; nothing else is lost;
  * the visible document equals the expected view (no loss, no drift, no
    stale lines): the global window when all levels are on, or the visible
    levels' own history windows merged in stream order when a filter is
    active.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import heapq
import random
import re
import time

import pytest

from PyQt6.QtWidgets import QApplication

import core.config as CC
import ui.main_window as MW
from core.constants import LOG_MAX_BLOCK_COUNT

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture
def window(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    last_run = logs_dir / "last_run.log"
    monkeypatch.setattr(CC, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(CC, "LAST_RUN_LOG", last_run)
    monkeypatch.setattr(MW, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(MW, "LAST_RUN_LOG", last_run)
    app = _qapp()
    from core.defaults import _FALLBACK_DEFAULTS
    w = MW.MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    yield w
    w.close()


def _expected_visible(w):
    enabled = {lvl for lvl, b in w._log_level_boxes.items() if b.isChecked()}
    if w._log_filter_active():
        pools = [
            w._level_histories[lvl] for lvl in w._level_histories
            if w._log_level_visible(lvl, enabled)
        ]
        items = [rec for _seq, rec in heapq.merge(*pools)]
    else:
        items = list(w._log_records)
    return [re.sub(r"<[^>]+>", "", h) for _lvl, h in items]


def test_stress_toggles_mid_stream(window):
    app = _qapp()
    w = window
    rnd = random.Random(42)
    all_lines = []
    n = 20000
    toggles_at = {5000, 9000, 12000, 16000}
    for i in range(n):
        lvl = rnd.choice("DDDDIIIIWWEE")  # info-heavy like trace runs
        line = f"{(i % 1000) / 1000 + 1.0:.3f} {lvl} line-{i}"
        all_lines.append((lvl, line))
        w._append_log(line + "\n")
        if i in toggles_at:
            # toggle while buffer is pending (timer running)
            box = w._log_level_boxes[rnd.choice("DIWE")]
            box.setChecked(not box.isChecked())
            time.sleep(0.002)
        if i % 300 == 0:
            time.sleep(0.01)  # let the 100ms timer fire
            app.processEvents()
        if i % 3000 == 0:
            w._flush_log_buffer()
    w._flush_log_buffer()
    app.processEvents()
    # records: nothing lost beyond the cap
    assert len(w._log_records) <= LOG_MAX_BLOCK_COUNT
    tail_lines = [line for _, line in all_lines[-len(w._log_records):]]
    rec_lines = [re.sub(r"<[^>]+>", "", h) for _, h in w._log_records]
    assert tail_lines == rec_lines, (
        f"records lost or reordered: {len(tail_lines)} vs {len(rec_lines)}; "
        f"first mismatch at {next((i for i, (a, b) in enumerate(zip(tail_lines, rec_lines)) if a != b), 'len')}"
    )
    # per-level windows: capped, tail-ordered, nothing lost within the cap
    for lvl, dq in w._level_histories.items():
        assert len(dq) <= LOG_MAX_BLOCK_COUNT, lvl
        lvl_lines = [line for l, line in all_lines if l == lvl]
        tail = lvl_lines[-len(dq):]
        assert [re.sub(r"<[^>]+>", "", h) for _s, (_l, h) in dq] == tail, lvl
    # doc: exactly the expected view (global window or merged level windows)
    got = w.log_output.toPlainText().split("\n")
    exp = _expected_visible(w)
    assert len(got) == len(exp), f"doc {len(got)} != expected {len(exp)}"
    for i, (g, e) in enumerate(zip(got, exp)):
        assert g == e, f"block {i}: {g!r} != {e!r}"
    print("final filter:", {k: b.isChecked() for k, b in w._log_level_boxes.items()})
    print("records:", len(w._log_records), "doc blocks:", len(got))
