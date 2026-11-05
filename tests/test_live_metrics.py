# -*- coding: utf-8 -*-
"""实时指标行：纯函数 + worker 状态机 + 分组指标带渲染 + MainWindow 接线。

llama.cpp b11976 端点契约（详见 memory live-metrics-row-v2.md）：/slots
计数器按任务重置（new < old = 任务边界，重新起算）；/metrics 只取累计
counter（decode gauge 只在任务结束时入桶，不作速度源）；METRICS/
SLOT_GET 在 decode 让出期间被处理，生成中轮询不阻塞。
"""
import io
import json
import os
import time
import urllib.error
import urllib.request

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.live_stats import diff_slots, parse_metrics, probe_metrics


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def _qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _slot(id=0, decoded=0, processed=0, n_prompt=0, n_cached=0, n_ctx=4096,
          active=False, task=None):
    s = {
        "id": id,
        "n_prompt_tokens": n_prompt,
        "n_prompt_tokens_processed": processed,
        "n_prompt_tokens_cache": n_cached,
        "n_ctx": n_ctx,
        "is_processing": active,
        "next_token": [{"n_decoded": decoded}],
    }
    if task is not None:
        s["id_task"] = task
    return s


# ---------------------------------------------------------------------------
# diff_slots
# ---------------------------------------------------------------------------

def test_diff_slots_first_poll_is_baseline_only():
    res, prev = diff_slots(None, [_slot(decoded=100, processed=500)], 0.0)
    assert res["prefill_tps"] is None
    assert res["decode_tps"] is None
    assert res["active"] is False
    assert res["ctx_frac"] == pytest.approx(600 / 4096)  # processed 500 + cached 0 + decoded 100
    assert prev["slots"][0]["decoded"] == 100


def test_diff_slots_decode_delta():
    _, prev = diff_slots(None, [_slot(decoded=100, processed=500)], 0.0)
    res, _ = diff_slots(prev, [_slot(decoded=105, processed=500)], 1.0)
    assert res["decode_tps"] == pytest.approx(5.0)
    assert res["prefill_tps"] is None  # 本窗口没有 prompt 活动


def test_diff_slots_prefill_delta():
    _, prev = diff_slots(None, [_slot(processed=500)], 0.0)
    res, _ = diff_slots(prev, [_slot(processed=620)], 1.0)
    assert res["prefill_tps"] == pytest.approx(120.0)
    assert res["decode_tps"] is None


def test_diff_slots_task_boundary_resets_baseline():
    _, prev = diff_slots(None, [_slot(decoded=100, processed=500)], 0.0)
    # 计数器在服务端重置（新任务）→ 不取负，只重新起算基线
    res, prev2 = diff_slots(prev, [_slot(decoded=3, processed=10)], 1.0)
    assert res["decode_tps"] is None
    assert res["prefill_tps"] is None
    # 下一窗对新基线差分
    res2, _ = diff_slots(prev2, [_slot(decoded=4, processed=10)], 2.0)
    assert res2["decode_tps"] == pytest.approx(1.0)


def test_diff_slots_sums_multiple_slots():
    _, prev = diff_slots(None, [_slot(id=0, decoded=10),
                                _slot(id=1, decoded=20)], 0.0)
    res, _ = diff_slots(prev, [_slot(id=0, decoded=13),
                               _slot(id=1, decoded=25)], 1.0)
    assert res["decode_tps"] == pytest.approx(8.0)  # 3 + 5，跨 slot 求和


def test_diff_slots_ctx_keeps_the_occupancy_when_the_slot_goes_idle():
    """回归（报告的 bug）：“不活动时 context 怎么还是 0？”

    任务结束那一刻 `server_slot::release()` → `reset()` 就 `stats = {}`（普通 slot
    的 prompt **不**清，只有 child/stateless/tts 才 `prompt_clear()`）：于是
    `n_prompt_tokens_processed` / `_cache` / `n_decoded` 全归零，而
    `n_prompt_tokens` 仍是整段对话的长度（`ptask = task ? task : task_prev` →
    这几个字段任务后依旧发布）。只按任务账本算 ⇒ 一空闲就显示 0%，而 KV 里
    几万 token 还占着（prompt cache 复用的整个意义）—— 上一版为修“投机解码
    双计”换成纯任务账本，把这个暴露出来了。现在取两本账的较大值。
    """
    gen = 15364
    busy = _slot(processed=25825, n_cached=4096, decoded=gen, n_ctx=200000,
                 active=True)
    busy["n_prompt_tokens"] = 25825 + 4096 + gen
    _, prev = diff_slots(None, [busy], 0.0)

    # 任务结束后那一帧（重放 llama.cpp 的 reset()：stats 归零、prompt 保留）
    idle = _slot(processed=0, n_cached=0, decoded=0, n_ctx=200000, active=False)
    idle["n_prompt_tokens"] = 25825 + 4096 + gen
    res, _ = diff_slots(prev, [idle], 1.0)
    assert res["ctx_used"] == 45285
    assert res["ctx_frac"] == pytest.approx(45285 / 200000)
    assert res["active"] is False      # 阶段也归空（两格标签回灰）
    # 空实为空（模型刚加载、一个请求都没跑过 / `prompt_clear()` 之后）仍是 0
    res2, _ = diff_slots(None, [_slot(n_ctx=200000)], 0.0)
    assert res2["ctx_used"] == 0
    assert res2["ctx_frac"] == pytest.approx(0.0)


def test_diff_slots_publishes_the_phase():
    """阶段（prefill / decode）跟着 /slots 一起发布 —— 指标带给格标签染色提示用。"""
    def _res(slot):
        return diff_slots(None, [slot], 0.0)[0]

    pre = _res(_slot(active=True, processed=1000, n_prompt=2000))
    assert pre["prefilling"] is True and pre["decoding"] is False
    dec = _res(_slot(active=True, processed=2000, n_prompt=2000, decoded=57))
    assert dec["decoding"] is True and dec["prefilling"] is False
    idle = _res(_slot(active=False, processed=2000, n_prompt=2000, decoded=57))
    assert idle["prefilling"] is False and idle["decoding"] is False


def test_diff_slots_phase_ignores_the_speculative_prompt_growth():
    """阶段不能拿 `processed < n_prompt_tokens` 判：投机解码会把生成 token 追进那段
    历史（同一个坑见 ctx 那两条测试），使该式在生成期间也成立 → 阶段会永远卡在
    prefill。用 `n_decoded` 才干净。
    """
    slot = _slot(active=True, processed=25825, n_cached=4096, decoded=15364,
                 n_ctx=200000)
    slot["n_prompt_tokens"] = 25825 + 4096 + 15364   # 历史长度远超已处理：仍在生成
    res = diff_slots(None, [slot], 0.0)[0]
    assert res["decoding"] is True
    assert res["prefilling"] is False


def test_diff_slots_ctx_uses_busiest_slot():
    _, prev = diff_slots(None, [], 0.0)
    res, _ = diff_slots(
        prev,
        [_slot(id=0, n_prompt=100, processed=100, n_ctx=4096),
         _slot(id=1, n_prompt=2000, processed=1600, n_cached=400, decoded=500,
               n_ctx=4096)],
        1.0)
    # 与 llama.cpp 自带 WebUI 同一套账：processed + cached + decoded（不是
    # n_prompt_tokens + decoded，理由见下一个测试）
    assert res["ctx_frac"] == pytest.approx(2500 / 4096)
    assert res["ctx_used"] == 2500
    assert res["ctx_total"] == 4096


def test_diff_slots_ctx_is_not_double_counted_while_spec_decoding():
    """回归（报告的 bug）：开投机解码（`--spec-type draft-mtp`）时上下文条偏大，
    下一个请求 prefill 一开始又“变准”。

    投机解码每验收到一批 token 就把它们追进到 slot 的 prompt 历史（llama.cpp
    server-context.cpp：“add accepted tokens to the prompt”），于是
    `n_prompt_tokens` 把生成部分也算进去了；旧算法 `n_prompt + decoded` 就把同一批
    token 数了两遍（偏差 = 已生成的全部 token）。prompt 侧计数器不受污染 —— 它们就
    是 WebUI 用的 `prompt_n` / `cache_n`。
    """
    slot0 = _slot(processed=25825, n_cached=4096, decoded=0, n_ctx=200000)
    slot0["n_prompt_tokens"] = 29921          # 历史长度 = prompt + cached（未生成）
    _, prev = diff_slots(None, [slot0], 0.0)

    gen = 15364
    slot1 = _slot(processed=25825, n_cached=4096, decoded=gen, n_ctx=200000)
    # 生成过程中历史长度跟着 n_decoded 一起长（草稿 + 被接受的 token）
    slot1["n_prompt_tokens"] = 29921 + gen
    res, _ = diff_slots(prev, [slot1], 1.0)

    assert res["ctx_used"] == 25825 + 4096 + gen          # WebUI 的数
    assert res["ctx_frac"] == pytest.approx(45285 / 200000)
    # 旧算法会多报整整一叠生成 token（45285 → 60649，+34%）
    assert res["ctx_used"] != slot1["n_prompt_tokens"] + gen


def test_diff_slots_ctx_falls_back_without_prompt_counters():
    """老服务端不发布 `n_prompt_tokens_processed` / `_cache`：退回旧算法，
    否则新算法会永远算出 0。"""
    legacy = {"id": 0, "n_ctx": 4096, "is_processing": True,
              "n_prompt_tokens": 1200, "next_token": [{"n_decoded": 300}]}
    res, _ = diff_slots(None, [legacy], 0.0)
    assert res["ctx_used"] == 1500
    assert res["ctx_frac"] == pytest.approx(1500 / 4096)


def test_diff_slots_task_cache_hit_deduped_by_id_task():
    res, prev = diff_slots(
        None, [_slot(n_prompt=100, n_cached=50, active=True, task=1)], 0.0)
    assert res["task_cache_hit"] == pytest.approx(0.5)
    assert res["task_cache_tokens"] == 100
    # 同任务继续 → 不上报（worker 侧携带上一窗口的值）
    res2, prev2 = diff_slots(
        prev, [_slot(n_prompt=100, n_cached=50, active=True, task=1)], 1.0)
    assert res2["task_cache_hit"] is None
    # 新任务 → 按新比率上报
    res3, _ = diff_slots(
        prev2, [_slot(n_prompt=80, n_cached=0, active=True, task=2)], 2.0)
    assert res3["task_cache_hit"] == pytest.approx(0.0)


def test_diff_slots_ignores_malformed_entries():
    res, prev = diff_slots(None, [None, "x", {}], 0.0)
    assert res["active"] is False
    assert res["ctx_frac"] is None
    # 缺 next_token 的 slot 也不炸
    res, _ = diff_slots(prev, [{"id": 0, "n_ctx": 0}], 1.0)
    assert res["decode_tps"] is None


# ---------------------------------------------------------------------------
# parse_metrics
# ---------------------------------------------------------------------------

_SAMPLE_METRICS = """# HELP llamacpp:prompt_tokens_total prompt tokens
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 123.0
llamacpp:prompt_tokens_cached_total 45.0
llamacpp:tokens_predicted_total 678.0
llamacpp:prompt_tokens_seconds 12.5
llamacpp:predicted_tokens_seconds 0
llamacpp:prompt_tokens_total_seconds 9.5
"""


def test_parse_metrics_extracts_counters_only():
    out = parse_metrics(_SAMPLE_METRICS)
    assert out == {"prompt": 123.0, "prompt_cached": 45.0,
                   "predicted": 678.0}  # gauge/_seconds 行不混入


def test_parse_metrics_tolerates_missing_and_nan():
    assert parse_metrics("llamacpp:tokens_predicted_total 5.0") == {
        "predicted": 5.0}
    assert parse_metrics("llamacpp:prompt_tokens_total NaN\n") == {}
    assert parse_metrics("unrelated body") == {}


def test_parse_metrics_labeled_line_takes_value_after_braces():
    out = parse_metrics('llamacpp:prompt_tokens_total{slot="0"} 7.0')
    assert out == {"prompt": 7.0}


# ---------------------------------------------------------------------------
# probe_metrics（urlopen 打桩）
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self, _n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_probe_metrics_available(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=None: _FakeResp("llamacpp:up 1"))
    assert probe_metrics("127.0.0.1", 1) == "available"


def test_probe_metrics_404_is_unsupported(monkeypatch):
    def _raise(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    assert probe_metrics("127.0.0.1", 1) == "unsupported"


def test_probe_metrics_no_metrics_body_is_unsupported(monkeypatch):
    def _raise(url, timeout=None):
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            io.BytesIO(b'{"error":"the server does not support metrics"}'))
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    assert probe_metrics("127.0.0.1", 1) == "unsupported"


def test_probe_metrics_connection_refused_is_error(monkeypatch):
    def _raise(url, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    assert probe_metrics("127.0.0.1", 1) == "error"


# ---------------------------------------------------------------------------
# LiveStatsWorker（打桩端点，跑真实线程）
# ---------------------------------------------------------------------------

def test_worker_reports_unsupported_metrics(monkeypatch):
    from ui import live_stats
    app = _qapp()
    worker = live_stats.LiveStatsWorker("127.0.0.1", 9931)
    states = []
    worker.metrics_state.connect(states.append)
    monkeypatch.setattr(live_stats, "fetch_url", lambda *a, **k: ("[]", None))
    monkeypatch.setattr(live_stats, "probe_metrics",
                        lambda *a, **k: "unsupported")
    monkeypatch.setattr(live_stats, "LIVE_STATS_SLOTS_SECONDS", 0.02)
    worker.start()
    deadline = time.time() + 3
    while time.time() < deadline and not states:
        app.processEvents()
        time.sleep(0.01)
    worker.request_stop()
    worker.wait(2000)
    assert states[0] == "unsupported"


def test_worker_emits_slot_stats_and_merges_metrics(monkeypatch):
    from ui import live_stats
    app = _qapp()
    calls = {"i": 0}

    def fake_fetch(host, port, path, timeout=1.0):
        if path == "/slots":
            calls["i"] += 1
            # 后来 decode 多 5 个 token
            return json.dumps(
                [_slot(decoded=100 if calls["i"] == 1 else 105)]), None
        if path == "/metrics":
            return _SAMPLE_METRICS, None
        return None, "error"

    monkeypatch.setattr(live_stats, "fetch_url", fake_fetch)
    monkeypatch.setattr(live_stats, "probe_metrics",
                        lambda *a, **k: "available")
    worker = live_stats.LiveStatsWorker("127.0.0.1", 9931)
    stats = []
    worker.stats_ready.connect(stats.append)
    monkeypatch.setattr(live_stats, "LIVE_STATS_SLOTS_SECONDS", 0.02)
    worker.start()
    deadline = time.time() + 3
    while time.time() < deadline and not (
            len(stats) >= 2 and stats[-1].get("decode_tps")):
        app.processEvents()
        time.sleep(0.01)
    worker.request_stop()
    worker.wait(2000)
    assert len(stats) >= 2
    assert stats[0]["decode_tps"] is None  # 首窗只起基线
    second = stats[-1]
    assert second["decode_tps"] is not None and second["decode_tps"] > 0
    assert second["prompt_total"] == 123.0  # 累计 counter 已合并
    assert second["prompt_cached_total"] == 45.0


# ---------------------------------------------------------------------------
# i18n：经变量传入 t() 的键表（AST 扫描看不见，显式钉住 —— _TAB_TITLES
# 同款先例）
# ---------------------------------------------------------------------------

def test_live_metrics_key_tables_translated():
    import core.i18n as I
    from ui.live_metrics import LiveMetricsBar
    # 格标签与 tooltip 的全名都是经变量喂给 t() 的（AST 扫不到；组标题
    # 「实时 / 累计」后来删除，不再有这一项）
    missing = [s for s in LiveMetricsBar._LABELS.values()
               if s not in I._EN]
    missing += [s for s in LiveMetricsBar._FULL_NAMES.values()
                if s not in I._EN]
    # 每一格都得有全名：tooltip 第一行没有兜底，漏一格就是 KeyError
    missing += [k for k in LiveMetricsBar._ALL_KEYS
                if k not in LiveMetricsBar._FULL_NAMES]
    assert not missing, f"live-metrics i18n keys missing from _EN: {missing}"


# ---------------------------------------------------------------------------
# LiveMetricsBar（offscreen）
#
# 2026-11 重设计：● 状态点 + 「实时」3 格 + 一条分隔线 + 「累计」4 格，
# 5 段等权弹性空隙把两组推到条带两端；未运行 / unix socket 折叠为单行提示。
# 旧的 7 个符号图标 + 6 条竖分隔线 + 七个 "—" 灰显格全部取消。
# ---------------------------------------------------------------------------

def _bar():
    from ui.live_metrics import LiveMetricsBar
    return LiveMetricsBar()


def _pt(label):
    """QLabel 的 plainText（QLabel 无此方法）：去 HTML 标签并还原实体。"""
    import re
    s = re.sub(r"<[^>]+>", "", label.text())
    return s.replace("&nbsp;", "\u00a0").replace("&mdash;", "—")


def _val(bar, key):
    """一个指标数值的可见文本：定宽左填充折叠成普通空格，便于直接断言。

    ctx 的"数值"是计量条里画的那串（后来的定案），`_CtxMeter.text()` 就是它。
    """
    return _pt(bar._tiles[key][1]).replace("\u00a0", " ").strip()


def _cap(bar, key):
    return _pt(bar._tiles[key][0].property("cap"))


def _tip(bar, key):
    """tooltip 挂在格上（整格可悬停），不在数值标签里。"""
    return bar._tiles[key][0].toolTip()


_STATS = {
    "prefill_tps": 85.3, "decode_tps": 12.4,
    "ctx_frac": 0.423, "ctx_used": 1733, "ctx_total": 4096,
    "active": True,
    # 这一帧在算输入（阶段格的默认值）；需要另一阶段时用
    # `_live(bar, prefilling=False, decoding=True)` 覆盖
    "prefilling": True, "decoding": False,
    "task_cache_hit": 0.5, "task_cache_tokens": 100,
    "prompt_total": 1000, "prompt_cached_total": 500,
    "predicted_total": 800,
}


def _live(bar, **over):
    """运行态 + 两端都可应答 + 一帧完整数据。"""
    bar.set_running(True)
    bar.set_slots_state("available")
    bar.set_metrics_state("available")
    bar.update({**_STATS, **over})
    return bar


def test_fmt_tokens_rolls_tiers_before_1000():
    """`_fmt_tokens` 的输出宽度有上限（后来的要求：“数字多一些就显示不全了”）。

    旧版先选档再除：999_999 → "1000.0K"（7 字）把列宽撑穿 → 数字被裁。现在舍入后
    ≥ 1000 就进上一档（顺便也不再说"1000.0K"这种没人想读的话）。
    """
    from ui.live_metrics import _WIDEST, _fmt_tokens
    assert _fmt_tokens(0) == "0"
    assert _fmt_tokens(999) == "999"
    assert _fmt_tokens(1_234) == "1.2K"
    assert _fmt_tokens(999_999) == "1.0M"
    assert _fmt_tokens(999_999_999) == "1.0G"
    assert _fmt_tokens(999_999_999_999) == "1.0T"
    assert _fmt_tokens(9_995_000_000_000_000) == "9995T"   # 最高档封顶（≥ 1e15）
    widest = len(_WIDEST["total_in"])
    # 扫每条分支的边界（不是只测样本）：累计 counter 能到的量级里宽度恒 ≤ strut
    for v in (0, 1, 999, 1_000, 9_999, 99_995, 100_000, 999_999, 1_000_000,
              9_995_000, 10_000_000, 999_999_999, 1_000_000_000,
              999_999_999_999, 1_000_000_000_000, 9_995_000_000_000_000):
        text = _fmt_tokens(v)
        assert len(text) <= widest, (v, text)


def test_value_columns_have_headroom_for_wide_numbers():
    """读数框装得下**格式化函数自己能吐出的最宽文本**，还留有余量。

    后来（要求：“输入 缓存 输出 这个框子有点短啊，数字多一些就显示不全了”）。
    不手写样本（写样本的人与写格式化的人不是同一个人时，样本永远是“对的那个”），
    而是把各档边界值交给 `_fmt_tokens` / `_fmt_speed`，再用同一个排版引擎量宽：
    数值标签的 sizeHint 必须 ≤ 列宽（列宽由 strut 钉），并且最大的那个还要留得出
    一个数字位的空隙（strut 前面垫的那个 "0"）。
    """
    from ui.live_metrics import _fmt_speed, _fmt_tokens
    app = _qapp()
    bar = _live(_bar())
    bar.resize(bar.sizeHint().width(), 34)
    bar.show()
    for _ in range(6):
        app.processEvents()
    samples = {
        "total_in": [_fmt_tokens(v) for v in
                     (0, 999, 1_234, 999_999, 1_000_000, 999_999_999,
                      999_999_999_999, 9_995_000_000_000_000)],
        "total_out": [_fmt_tokens(v) for v in (9_999, 999_999, 999_999_999)],
        "prefill": [_fmt_speed(v) for v in (0, 9.7, 999.9, 9_999, 12_345)],
        "decode": [_fmt_speed(v) for v in (999.9, 9_999, 99_999)],
        "hit_rate": ["0.0", "16.7", "100.0"],
    }
    try:
        for key, texts in samples.items():
            value = bar._tiles[key][1]
            column = value.parentWidget()
            widest_hint = 0
            for text in texts:
                value.setText(bar._value_html(key, text))
                hint = value.sizeHint().width()
                widest_hint = max(widest_hint, hint)
                assert hint <= column.width(), (key, text, hint,
                                                column.width())
            # 余量：最大的那个样本右侧还能放得下一个数字（strut 多垫的 "0"）
            assert column.width() - widest_hint >= 4, (
                key, column.width(), widest_hint)
            # 列宽与当前文本无关（strut 钉宽）：换回破折号宽度不变
            value.setText(bar._value_html(key, None))
            assert column.width() >= widest_hint, key
    finally:
        bar.close()


def test_metrics_tooltip_uses_the_real_navigation_path():
    """“怎么开启 --metrics”用**准确的导航语言**（要求：“这个表述不正确，用准确的
    导航语言来说 请在“服务”→“xxx” 用这种语言说”）。

    旧写法“在服务页勾选「Prometheus 指标」”三处都不准：没有“服务页”这个说法（它是
    高级面板里的「服务」标签页）、标签叫「Prometheus指标 (--metrics)」、而且必须先切
    到高级模式才看得到。现在路径是「高级模式」→「服务」→「Prometheus指标
    (--metrics)」，**三个名字全部从 schema / TAB_TITLES 取**（不手写 → 不会漂移）。
    """
    from core.i18n import get_language, set_language
    from core.params_schema import PARAMS_BY_KEY, TAB_TITLES
    from ui.live_metrics import _metrics_nav
    _qapp()
    back = get_language()
    bar = _bar()
    bar.set_running(True)
    bar.set_metrics_state("unsupported")
    nav = _metrics_nav()
    tip = _tip(bar, "total_in")
    assert "→" in tip and nav in tip, tip
    tab = dict(TAB_TITLES)[PARAMS_BY_KEY["metrics"].tab]
    label = PARAMS_BY_KEY["metrics"].label.rstrip(":")
    assert tab in nav and label in nav, nav
    assert "服务页" not in tip and "Prometheus 指标" not in tip, tip
    # 未启动时**不再**写这段引导（要求：“tooltip 里不要刻意地写”）：没启动
    # 时行动点还不是“勾选项”，而是“先把服务跑起来”；启动后累计格自己会说
    bar.set_running(False)
    assert nav not in _tip(bar, "total_in"), _tip(bar, "total_in")
    # 英文模式：三个名字各自跟着翻译走（不是中文夹英文）
    set_language("en")
    try:
        bar.set_running(True)          # 停服会重置端点状态 → 重新报一次
        bar.set_metrics_state("unsupported")   # 重画才会用新语言重组 tooltip
        tip_en = _tip(bar, "total_in")
        assert "Server" in tip_en, tip_en
        assert "Prometheus Metrics (--metrics)" in tip_en, tip_en
        assert "勾选" not in tip_en and "服务" not in tip_en, tip_en
    finally:
        set_language(back)


def test_bar_structure_grouped_strip():
    from PyQt6.QtWidgets import QWidget
    _qapp()
    bar = _bar()
    # 条带透明无边框 + **只有数值带框**（后来的定案）：#metricCell 是透明容器，
    # #metricValueBox 才是读数窗；ctx 连框都不要，数值画在计量条里面
    # 组标题「实时 / 累计」于后来删除（要求：“live 和 session 这两个 label
    # 不需要，光占地方"）→ 断言它们**不存在**，别悄悄长回来。
    assert bar.objectName() == "liveMetricsBar"
    assert len(bar.findChildren(QWidget, "metricCell")) == 7
    # 六个数字各一个读数框；ctx 不框（数值写在条里），所以是 6 不是 7
    assert len(bar.findChildren(QWidget, "metricValue")) == 6
    assert len(bar.findChildren(QWidget, "metricValueBox")) == 6
    ctx_cell = bar._tiles["ctx"][0]
    assert ctx_cell.findChildren(QWidget, "metricValueBox") == []
    assert ctx_cell.findChildren(QWidget, "metricValue") == []
    # ctx 的「数值」与「计量条」是同一个部件（没有第二个数字部件在条外面）
    assert bar._tiles["ctx"][1] is bar._tiles["ctx"][2]
    assert bar.findChildren(QWidget, "metricCaption") == []
    assert len(bar.findChildren(QWidget, "metricMiniBar")) == 1
    # 组内竖分隔线全部删除（旧版 5 条：1px 线 + 7px 间距贴着下一个字）
    assert bar.findChildren(QWidget, "metricSep") == []
    # 旧的两组之间那条 1px 竖线（#metricGroupSep）删除：芯片自己就把每个指标框
    # 住了，竖线夹在芯片之间像一根没对齐的杂线（后来的定案）
    assert bar.findChildren(QWidget, "metricGroupSep") == []
    assert bar.minimumHeight() == 34
    # 符号图标取消：数值里不再出现 ≫/▸/◔/Σ/⊙（它们在 Consolas 里逐个回退
    # 到不同字体/字号/基线，是"不协调"的主要来源）
    for key in bar._ALL_KEYS:
        for sym in ("\u226b", "\u25b8", "\u25d4", "\u03a3", "\u2299"):
            assert sym not in bar._tiles[key][1].text()


def test_bar_cell_labels_survive_language_switch():
    from core.i18n import get_language, set_language
    _qapp()
    bar = _bar()
    from PyQt6.QtWidgets import QWidget
    try:
        set_language("zh")
        bar.retranslate_ui()
        # 右组标签缩短（全称在 tooltip）
        assert _cap(bar, "total_in") == "输入"
        assert _cap(bar, "cached_in") == "缓存"
        assert _cap(bar, "hit_rate") == "命中"
        set_language("en")
        bar.retranslate_ui()
        assert _cap(bar, "total_in") == "In"
        assert _cap(bar, "hit_rate") == "Hit"
        # 语言切换不引入组标题（后来删除）
        assert bar.findChildren(QWidget, "metricCaption") == []
    finally:
        set_language("zh")
        bar.retranslate_ui()


def test_bar_minimum_holds_the_numbers_not_just_the_labels():
    """条带的最小宽度必须容得下七个数字 —— 数字被切掉等于这行没有意义。

    旧口径（"这一行绝不能成为窗口最小宽度的约束"）把最小宽度只算到标签：窗口
    停在最小尺寸时 QLayout 就把七个数值列从 88px 压到 30px，**数字直接看不见**。
    2026-11 改版反过来定：数值列的最小宽度 = strut（该指标最宽取值）宽度，
    条带最小宽度 = 数值 + 计量条 + 固定间距，`MainWindow._sync_panel_min` 把它算进
    窗口最小宽度 → 这一行现在**就是**窗口宽度的约束之一（合一行 = 按钮 + 条带，
    实测 ~890px 内容宽，窗口最小宽度 ~1108px；另一侧的取舍见
    test_metrics_row_floor_keeps_values_visible）。

    钉住：① 最小宽度 ≥ 七个数值列之和 + 上下文计量条；② 条带自己不写死
    setMinimumWidth（宽度由内容量出来，Qt 钉的 minimumSize 不算）；③ 地板与模式
    无关（服务启停不改变窗口最小宽度）；④ 地板与运行状态无关（后来删掉
    提示态之后条带只有一种排版；旧版还得在提示态把 hidden 部件临时显形量一次 ——
    hidden 的 QWidget 一律报无效 sizeHint，不量就只能等服务启动才涨，而 Qt 那层
    布局最小保护又已被写死的 setMinimumSize 关掉）。
    """
    from ui.live_metrics import _BAR_W
    _qapp()
    bar = _bar()
    # ctx 没有数值列（数字在条里），它那份宽度就是下面单独加的 _BAR_W
    columns = [bar._tiles[k][1].parentWidget() for k in bar._ALL_KEYS
               if k != "ctx"]
    _live(bar)
    value_floor = sum(c.minimumSizeHint().width() for c in columns)
    floor = bar.min_content_width()
    assert value_floor > 0
    assert floor >= value_floor + _BAR_W, (floor, value_floor)
    # 条带自己不钉宽度：只允许 Qt 在 activate() 之后钉出来的布局最小值
    assert bar.minimumWidth() <= bar.layout().minimumSize().width() + 1, (
        bar.minimumWidth(), bar.layout().minimumSize().width())
    # ④ 未运行也是同一副七格（后来的定案）→ 地板从构造起就是它，且与运行状态无关
    bar.set_running(False)
    idle_floor = bar.min_content_width()
    assert idle_floor >= value_floor + _BAR_W, (idle_floor, value_floor)
    # ③ 服务启停不改变地板（也就不改变窗口最小宽度）
    _live(bar)
    assert bar.min_content_width() == idle_floor, (
        bar.min_content_width(), idle_floor)


def test_readout_controls_share_one_height():
    """数值读数框与上下文计量条**等高**（后来的要求：“这些框看起来比文字矮，
    视觉不统一，起码跟进度条一样高吧，视觉上整体优化下”）。

    上一版框高是 QSS 竖向 padding + 标签行高撑出来的（Consolas 11px ≈ 13px），
    比计量条矮一截，一排里高高低低。现在两者都读代码里的 `_FIELD_H`。

    钉住：① 六个读数框 + 计量条高度都 == `_FIELD_H`（同一个常量，不是各自 padding
    碰巧算出同一个数）；② 框比字高（否则就回到了“框比文字矮”）；③ 数字在框里
    垂直居中且不超出内容区（竖向 padding 写了非 0 就会把 20px 扣到装不下 13px
    的数字，字溢出到边框上 —— 那正是注释里警告的那件事）；④ 整行仍是 34px。
    """
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import QPoint
    from ui.live_metrics import _FIELD_H
    app = _qapp()
    bar = _live(_bar())
    bar.resize(bar.sizeHint().width(), 34)
    bar.show()
    for _ in range(6):
        app.processEvents()
    try:
        boxes = bar.findChildren(QWidget, "metricValueBox")
        assert len(boxes) == 6
        meter = bar._tiles["ctx"][2]
        for w in boxes + [meter]:
            assert w.height() == _FIELD_H, (w.objectName(), w.height())
        for key in set(bar._ALL_KEYS) - {"ctx"}:
            value = bar._tiles[key][1]
            column = value.parentWidget()          # #metricValueCol（strut + 数值）
            box = column.parentWidget()            # #metricValueBox（带框那层）
            assert box.objectName() == "metricValueBox", key
            assert box.height() > value.sizeHint().height(), key
            # 数字没被内容区裁掉：contentsRect 已算上 QSS 的 border + padding
            # （竖向 padding 写了非 0 就会把 20px 扣到装不下 13px 的数字）
            assert value.height() <= box.contentsRect().height(), key
            assert value.height() >= value.sizeHint().height(), key
        # 垂直居中：框、数字、计量条三者中线对齐（一律 mapTo 到条带坐标，
        # geometry() 是父坐标系的，直接比会隔层错开）
        def cy(widget):
            return widget.mapTo(bar, QPoint(widget.width() // 2,
                                            widget.height() // 2)).y()

        for key in set(bar._ALL_KEYS) - {"ctx"}:
            value = bar._tiles[key][1]
            box = value.parentWidget().parentWidget()
            assert abs(cy(value) - cy(box)) <= 1, key
            assert abs(cy(meter) - cy(box)) <= 1, key
        assert bar.minimumHeight() == 34
    finally:
        bar.close()


def test_bar_value_columns_are_fixed_width():
    """数值列定宽（_ValueColumn 的透明 strut）→ 刷新时数字列不左右移动。

    断言的是几何而不是 sizeHint：定宽的语义就是"当前文本不参与列宽"，
    QLabel 的 sizeHint 仍随文本变（旧版用 &nbsp; 填充时，测试环境的字体被
    换成比例字体后 nbsp 与数字不同宽，整行照样抖 —— 全量跑挂过一次）。
    """
    from PyQt6.QtCore import Qt
    app = _qapp()
    bar = _live(_bar())
    bar.resize(1100, 34)
    bar.show()                  # 几何只在真正进入布局后可读
    app.processEvents()
    try:
        def cols():
            return [(k, bar._tiles[k][1].width()) for k in bar._ALL_KEYS]

        wide = cols()
        assert all(w > 0 for _k, w in wide)
        # 6 位数 → 1 位数：文本位数变了，每格宽度与数字列位置不变
        bar.update(dict(_STATS, prefill_tps=9.7, decode_tps=1.2, ctx_frac=0.03,
                        prompt_total=7, prompt_cached_total=3,
                        predicted_total=2))
        app.processEvents()
        assert cols() == wide
        assert _val(bar, "prefill") == "9.7 t/s"
        # 右对齐：数字右边缘（= 列宽 - 单位宽）固定
        assert int(bar._tiles["prefill"][1].alignment())             & int(Qt.AlignmentFlag.AlignRight)
    finally:
        bar.close()


def test_bar_layout_follows_content_not_equal_columns():
    """2026-11 那批逐轮反馈钉住（“不要每个指标都均匀排布、prefill 这些就一个数字
    占那么大位置” / “进度条那个显示的特别短，可拉长啊” / “不同的指标间应留有一定
    的分隔或空白” / “那个进度条的数字从左侧改到右侧” / 后来“按钮与 metric 两行
    合并一行，中间 stretch 隔开”）。

    ① 格宽 = 内容宽：标签↔数值固定 4px、格宽 − 内容 ≤ 2px，不随条带宽度长；
    ② 条带横向 Maximum（只长到内容宽）+ 行内无弹性项 → 富余宽度只能归 MainWindow
       合一行里那条 stretch；
    ③ ctx 是「标签 → 计量条 → 数字」，数字在条**右**侧 4px；
    ④ 计量条定长 _BAR_W = 100（后来定案：中间 stretch 吃掉富余后，它不能再靠
       窗口变长 —— 实测后选定固定 100px）。"""
    from PyQt6.QtCore import QPoint
    from ui.live_metrics import _BAR_W
    from PyQt6.QtWidgets import QSizePolicy as SP
    app = _qapp()
    bar = _live(_bar())
    bar.show()

    def left(widget):
        return widget.mapTo(bar, QPoint(0, 0)).x()

    def right(widget):
        return widget.mapTo(bar, QPoint(widget.width(), 0)).x()

    try:
        # ② 只长到内容宽（外层合一行的 stretch 才能拿到富余）
        assert bar.sizePolicy().horizontalPolicy() == SP.Policy.Maximum
        # 只测"条带自己该占的宽度"这一档：minimum（窄窗口挤压态）与 sizeHint
        # （内容宽）。刻意不用 resize 到更宽 —— 强行拉宽是外层行为，Maximum
        # 策略只保证布局不会给它超出 sizeHint 的宽度
        for width in (bar.minimumSizeHint().width(), bar.sizeHint().width()):
            bar.resize(width, 34)
            bar.layout().activate()
            app.processEvents()
            from ui.live_metrics import _VALUE_GAP
            # ① 六个指标（除 ctx）：标签右边缘 → 读数框内数值左边缘 = _VALUE_GAP
            # （+ 框自己的 padding），格宽 = 内容宽，不随条带宽度长
            for key in set(bar._ALL_KEYS) - {"ctx"}:
                cell, value, _meter = bar._tiles[key]
                cap = cell.property("cap")
                box = value.parentWidget()
                pad = box.contentsMargins()          # QSS padding → contentsMargins
                assert (left(value) - pad.left() - right(cap)) == _VALUE_GAP, (
                    width, key)
                content = (cap.sizeHint().width() + _VALUE_GAP + value.width()
                           + pad.left() + pad.right())
                assert cell.width() - content <= 2, (width, key, cell.width())
            # ③ ctx：标签 → 计量条，**数字画在条里面**（后来的定案），所以条外没有
            # 第四个部件，条也仍是定长（不许随窗口拉长）
            ctx_cell, ctx_value, meter = bar._tiles["ctx"]
            ctx_cap = ctx_cell.property("cap")
            assert ctx_value is meter, width
            assert right(ctx_cap) <= left(meter), (width, "bar before label")
            assert meter.width() == _BAR_W, (width, meter.width())
        # ④ 计量条定长：与条带宽度无关
        widths = set()
        for width in (bar.minimumSizeHint().width(), 1200, 2400):
            bar.resize(width, 34)
            bar.layout().activate()
            widths.add(bar._tiles["ctx"][2].width())
        assert widths == {100}, widths
        # ② 行内没有**弹性**空隙（固定 addSpacing 当然有，但任何横向 Expanding
        # 的空隙都会与外层合一行里那条 stretch 抢富余宽度）
        from PyQt6.QtCore import Qt as _Qt
        lay = bar.layout()
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item.widget() is None:
                assert not (item.expandingDirections()
                            & _Qt.Orientation.Horizontal), i
        # ② 放进"stretch + 条带"的行里（就是 MainWindow.control_bar 的形状）：
        # 条带只占内容宽，富余宽度全在它左边
        from PyQt6.QtWidgets import QHBoxLayout, QWidget
        host = QWidget()
        hlay = QHBoxLayout(host)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(6)
        hlay.addStretch(1)
        hlay.addWidget(bar, 0)
        host.resize(1400, 34)
        host.show()
        hlay.activate()
        app.processEvents()
        # 阈值一律相对量，不写死像素（offscreen 字体宽度与真机不同）
        assert bar.width() <= bar.sizeHint().width(), (bar.width(), bar.sizeHint().width())
        leftover = host.width() - bar.width()
        assert bar.mapTo(host, QPoint(0, 0)).x() == leftover   # 富余全在它左边
        assert leftover > 0
        host.close()
        # 标签 / 计量条两处都可悬停（后来的要求：ctx 不加框、数值在条内 → 整块就是
        # 「标签 + 条」，条既是数值也是计量条）
        ctx_cell, ctx_val, ctx_meter = bar._tiles["ctx"]
        assert ctx_cell.objectName() == "metricCell"
        assert ctx_meter.parentWidget() is ctx_cell
        assert ctx_val is ctx_meter
        assert "上下文占用" in ctx_cell.toolTip()
        assert "上下文占用" in ctx_meter.toolTip()
        # 后来：未运行也是同一副七格 → ctx 的「标签 / 条 / 数字」三处一直在原位、
        # 一直可悬停；后来：停服后上下文条是 **0.0%**（KV 已空）而不是破折号
        bar.set_running(False)
        bar.resize(1100, 34)
        bar.layout().activate()
        app.processEvents()
        assert bar._tiles["ctx"][1].isVisibleTo(bar)
        assert bar._tiles["ctx"][2].isVisibleTo(bar)
        assert _val(bar, "ctx") == "0.0%"
        assert "服务未启动" in _tip(bar, "ctx")
    finally:
        bar.close()
def test_bar_ctx_meter_stays_visible_with_zero_when_there_is_no_activity():
    """上下文条常驻：刚开始（还没跑过任何请求）就是 0.0%，停服后回到 0.0%，
    只有**读不到**（/slots 被关 / 无 HTTP 端点）才给破折号。

    要求：“上下文进度条仅在有活动时显示，停止了就不显示了，应该一直显示，
    哪怕刚开始时也应为 0”。与累计组“开始就是 0”同一套规矩（后来的定案）。
    """
    _qapp()
    bar = _bar()
    # ① 未启动 → 0.0%（而不是 —），计量条为空
    assert _val(bar, "ctx") == "0.0%"
    assert bar._tiles["ctx"][2].value() == 0
    # ② 运行中、/slots 已应答但还没有读数（模型还在加载）→ 仍是 0.0%
    bar.set_running(True)
    bar.set_slots_state("available")
    bar.set_metrics_state("available")
    bar.update({"prefill_tps": None, "decode_tps": None})
    assert _val(bar, "ctx") == "0.0%"
    assert _tip(bar, "ctx") == "上下文占用\n0.0%\nKV 缓存为空"
    # ③ 跑过一段后是真数；停服后 KV 消失 → 回到 0.0%（而不是破折号）
    bar.update({"prefill_tps": 100.0, "decode_tps": 20.0,
                "ctx_frac": 0.25, "ctx_used": 1024, "ctx_total": 4096})
    assert _val(bar, "ctx") == "25.0%"
    # ③b 服务空闲但 KV 里仍占着这段上下文 → 保持真数（不回到 0%）
    #（要求：“不活动时 context 怎么还是 0？” —— 任务结束后服务端把任务计数器
    # 归零了，但 prompt 缓存故意留着）
    bar.update({"ctx_frac": 0.25, "ctx_used": 1024, "ctx_total": 4096,
                "active": False})
    assert _val(bar, "ctx") == "25.0%"
    # tooltip 就两行（名称 + 精确值）：不再追写“这段仍在 KV 里”那类解释
    #（要求：“tooltip 里不要刻意地写，重新整体规划下显示的内容”）
    assert _tip(bar, "ctx") == "上下文占用\n1,024 / 4,096（25.0%）"
    bar.set_running(False)
    assert _val(bar, "ctx") == "0.0%"
    assert bar._tiles["ctx"][2].value() == 0
    # ④ /slots 被关 → 真的读不到 → 才是破折号
    bar.set_running(True)
    bar.set_slots_state("off")
    assert _val(bar, "ctx").startswith("—")
    # ⑤ unix socket 无 HTTP 端点 → 同上
    bar.set_no_http(True)
    assert _val(bar, "ctx").startswith("—")
    assert "unix socket" in _tip(bar, "ctx")


def test_bar_session_counters_read_zero_before_first_poll():
    """运行中、/metrics 还没回第一批数据：累计组是 0，不是破折号（后来的定案）。

    与 `/metrics` **明确不可用**（unsupported / error）区分开：那是"读不到" →
    仍走破折号 + 说明 tooltip（见 test_bar_metrics_unavailable_dims_right_group）。
    """
    _qapp()
    bar = _bar()
    bar.set_running(True)
    bar.set_metrics_state("available")
    bar.update({"prefill_tps": 10.0})         # 只有 /slots 的数据
    assert _val(bar, "total_in") == "0"
    assert _val(bar, "cached_in") == "0"
    assert _val(bar, "total_out") == "0"
    assert _val(bar, "hit_rate") == "0.0%"
    # 0/0 的命中率写 0.0%（“开始就是 0”），tooltip 不再补一句“尚无输入 token”
    assert _tip(bar, "hit_rate") == "缓存命中率\n0.0%"
    # 实时组仍是当前值（有就显示，没有就破折号）
    assert _val(bar, "prefill") == "10.0 t/s"
    assert _val(bar, "decode").startswith("—")
    # 第一批 /metrics 到位 → 直接换成真实值，列宽不变（strut 定宽）
    w_before = bar._tiles["total_in"][1].width()
    bar.update({"prompt_total": 5000, "prompt_cached_total": 1000,
                "predicted_total": 20})
    assert _val(bar, "total_in") == "6.0K"
    assert _val(bar, "hit_rate") == "16.7%"
    assert bar._tiles["total_in"][1].width() == w_before


def test_bar_labels_highlight_the_current_phase():
    """格标签按当前阶段染色（要求：“在不同阶段（prefill/decode）时，它的 label
    最好能显示个不同颜色，用于指示提醒用户当前在哪个阶段”）。

    正在跑的那一格自己亮着，其余保持 info 灰 —— 空闲时两格都灰，一眼就知道没活动；
    多 slot 混合阶段时两个同时亮。停服归灰；换主题 / 换语言后阶段色不丢。
    """
    _qapp()
    prefill_c, decode_c, info = "#1234ab", "#56cd65", "#707070"
    bar = _bar()
    bar.set_theme_colors("#101010", "#606060", info, prefill_c, decode_c)

    def cap(key):
        return bar._tiles[key][0].property("cap").styleSheet()

    # 空闲：两格都是 info 灰
    assert info in cap("prefill") and info in cap("decode")
    # prefill 阶段（_STATS 默认）：只有 Prefill 亮蓝
    _live(bar)
    assert prefill_c in cap("prefill") and info in cap("decode")
    # tooltip 不再写“本阶段正在进行”（颜色已经说了这件事）：活动格也只有两行
    assert _tip(bar, "prefill") == "Prefill 速度\n85.3 t/s"
    assert _tip(bar, "decode") == "Decode 速度\n12.4 t/s"
    # decode 阶段：反过来
    _live(bar, prefilling=False, decoding=True)
    assert decode_c in cap("decode") and info in cap("prefill")
    # 多 slot 混合：两个同时亮
    _live(bar, prefilling=True, decoding=True)
    assert prefill_c in cap("prefill") and decode_c in cap("decode")
    # 本窗口无活动（两个阶段都没报）→ 回到灰
    bar.update({})
    assert info in cap("prefill") and info in cap("decode")
    # 停服也归灰，并且重新染一次
    _live(bar, prefilling=False, decoding=True)
    bar.set_running(False)
    assert info in cap("prefill") and info in cap("decode")
    # 主题同步（_apply_theme 走同一入口）不会把阶段色洗成 info
    _live(bar, prefilling=True, decoding=False)
    bar.set_theme_colors("#101010", "#606060", info, prefill_c, decode_c)
    assert prefill_c in cap("prefill") and info in cap("decode")


def test_bar_phase_colors_do_not_move_the_layout():
    """阶段色只改颜色、不改宽度：这一行按内容定宽，阶段来回切不能让整行跳动
    （也提醒后人别给标签加粗体 —— 那会让 sizeHint 变）。
    """
    _qapp()
    bar = _live(_bar())
    bar.resize(1200, 34)
    bar.layout().activate()
    width = bar.sizeHint().width()
    for _ in range(3):
        _live(bar, prefilling=True, decoding=False)
        _live(bar, prefilling=False, decoding=True)
    bar.layout().activate()
    assert bar.sizeHint().width() == width


def test_bar_tooltips_share_one_shape_name_value_optional_identity():
    """要求（2026-11 末次改版）：“tooltip 里不要刻意地写，重新整体规划下显示的内容”
    → 七格固定三槽：**名称 / 精确值 /（必要时）一行身份**，缺的不占行。

    钉住：① 第一行永远是全名（格标签会被省略号截断，这里不会）；② 当前值
    就只两行 —— 含义/算法/来源/刷新频率一律不写；③ 第三行只在三档出现（上一段
    的均值 / 最后已知值 / 读不到的原因），而且**出现时格子必是次要色**（颜色与
    那行由同一个分支给出）；④ 旧版那些“追加一句提醒”不得复活。
    """
    from ui.live_metrics import LiveMetricsBar
    _qapp()
    banned = ("本阶段正在进行", "仍在 KV 缓存里", "计数器每秒差值",
              "同一套算法", "启动后在这里显示", "服务启动以来")

    def rows(bar, key):
        tip = _tip(bar, key)
        for word in banned:
            assert word not in tip, (key, word, tip)
        return tip.split("\n")

    # ①② 实时值：两行，第一行是全名，第二行是带单位的值
    bar = _live(_bar())
    for key in bar._ALL_KEYS:
        line1 = rows(bar, key)[0]
        assert line1 == LiveMetricsBar._FULL_NAMES[key], (key, line1)
        assert len(rows(bar, key)) == 2, (key, rows(bar, key))
    assert rows(bar, "prefill")[1].endswith(" t/s")
    assert rows(bar, "total_in")[1] == "1,500 tokens"     # 屏上是缩写的 1.5K

    # ③ 上一段的均值：第三行 + 次要色同进同出
    bar.set_last_task_speeds(1990.01, 74152, 92.63, 196)
    _live(bar, prefill_tps=None, decode_tps=None)
    lines = rows(bar, "prefill")
    assert len(lines) == 3 and lines[2].startswith("上一段的均值")
    assert bar._muted in bar._tiles["prefill"][1].text()
    # tokens 缺席（临界日志）时那一行缩短，但仍存在
    bar.set_last_task_speeds(1990.01, None, 92.63, None)
    assert rows(bar, "prefill")[2] == "上一段的均值"

    # ③ 最后已知值：第三行 + 次要色
    bar2 = _live(_bar())
    bar2.set_metrics_state("error")
    lines = rows(bar2, "total_in")
    assert len(lines) == 3 and lines[2].startswith("最后已知值")
    assert bar2._muted in bar2._tiles["total_in"][1].text()

    # ③ 读不到：第一行名称 + 最后一行原因（破折号不占一行）
    bar3 = _bar()
    assert rows(bar3, "prefill") == ["Prefill 速度", "服务未启动"]
    bar3.set_running(True)
    bar3.set_slots_state("available")
    assert rows(bar3, "decode") == ["Decode 速度", "当前没有该类活动"]
    bar3.set_slots_state("off")
    assert rows(bar3, "ctx") == ["上下文占用", "/slots 端点已关闭"]
    bar3.set_no_http(True)
    assert rows(bar3, "prefill")[-1] == "unix socket 无 HTTP 端点"


def test_bar_running_update_renders_values():
    _qapp()
    bar = _live(_bar())
    assert _val(bar, "prefill") == "85.3 t/s"
    assert _val(bar, "ctx") == "42.3%"        # % 紧跟数字，t/s 前留空隙
    assert _val(bar, "total_in") == "1.5K"    # 1000 + 500
    assert _val(bar, "cached_in") == "500"
    assert _val(bar, "total_out") == "800"
    assert _val(bar, "hit_rate") == "33.3%"
    # 计量条：绿档 + 数值
    cbar = bar._tiles["ctx"][2]
    assert cbar.value() in (422, 423)
    assert "#16a34a" in cbar.styleSheet()
    # 命中率 tooltip：屏上那个值的精确版（本任务那一档不再写 —— 两行结构）
    assert _tip(bar, "hit_rate") == "缓存命中率\n33.3%"
    # 实时速度格的 tooltip：名称 + 带单位的值
    assert _tip(bar, "prefill") == "Prefill 速度\n85.3 t/s"
    assert _tip(bar, "ctx") == "上下文占用\n1,733 / 4,096（42.3%）"
    # 无 decode 活动的窗口、且一个任务都没跑过 → 仍是定宽灰破折号（列宽不变）
    _live(bar, decode_tps=None)
    assert _val(bar, "decode") == "— t/s"


def test_bar_shows_previous_run_average_when_no_live_rate():
    """空档格显示**上一段连续活动**的均值，不再是一排破折号。

    数值是服务端自己在 `slot print_timing` 里算的单任务总量 ÷ 总时长（见
    `ui/log_parser.py` 的 `prompt_tps_last` / `decode_tps_last`），所以它天然就是
    “上一段”而不是全程平均，也没有 1s 轮询差分的边界误差。
    """
    _qapp()
    bar = _live(_bar())
    bar.set_last_task_speeds(1990.01, 74152, 92.63, 196)
    # 本窗口两类活动都没有（服务空闲）→ 两格都落到上一段均值
    _live(bar, prefill_tps=None, decode_tps=None)
    assert _val(bar, "prefill") == "1990.0 t/s"
    assert _val(bar, "decode") == "92.6 t/s"
    # 次要色（与破折号同族）：静止的历史均值不能被读成“当前速度”
    html = bar._tiles["prefill"][1].text()
    assert bar._muted in html and bar._text not in html
    # tooltip 说清来历：上一段 + 精确值 + token 数
    tip = _tip(bar, "prefill")
    assert "上一段" in tip and "1990.0" in tip and "74,152" in tip
    # 实时值优先：均值绝不覆盖当前速率
    _live(bar)
    assert _val(bar, "prefill") == "85.3 t/s"
    assert _val(bar, "decode") == "12.4 t/s"
    # 跳阶段（decode 期间的 Prefill 格）同样走均值
    _live(bar, prefill_tps=None, decode_tps=12.4)
    assert _val(bar, "prefill") == "1990.0 t/s"
    assert _val(bar, "decode") == "12.4 t/s"


def test_bar_previous_run_average_clears_on_stop():
    """停服回到破折号：均值属于**这个**服务实例，不能留给下个实例。"""
    _qapp()
    bar = _live(_bar())
    bar.set_last_task_speeds(1990.01, 74152, 92.63, 196)
    _live(bar, prefill_tps=None, decode_tps=None)
    assert _val(bar, "prefill") == "1990.0 t/s"
    bar.set_running(False)
    assert bar._last_task == {}
    assert _val(bar, "prefill") == "— t/s"
    # 重新起服务、还没跑过任务 → 仍是破折号
    bar.set_running(True)
    bar.set_slots_state("available")
    bar.update({})
    assert _val(bar, "prefill") == "— t/s"


def test_bar_slots_off_falls_back_to_average_with_its_own_tooltip():
    """/slots 被关：均值来自日志、与端点无关 → 显示它，但 tooltip 换成 slots 的说法；
    token 数缺席（畸形日志）时 tooltip 不写那一截。"""
    _qapp()
    bar = _bar()
    bar.set_running(True)
    bar.set_slots_state("off")
    bar.set_last_task_speeds(1990.01, 74152, 92.63, None)
    assert _val(bar, "prefill") == "1990.0 t/s"
    tip = _tip(bar, "prefill")
    assert "/slots" in tip and "1990.0" in tip and "74,152" not in tip
    assert "tokens" not in _tip(bar, "decode")


def test_bar_previous_run_average_follows_language():
    """新 tooltip 在英文模式下跟着走（字面量全部进了 _EN）。"""
    from core.i18n import get_language, set_language
    _qapp()
    bar = _live(_bar())
    bar.set_last_task_speeds(1990.01, 74152, 92.63, 196)
    _live(bar, prefill_tps=None, decode_tps=None)
    back = get_language()
    try:
        set_language("en")
        bar.retranslate_ui()
        assert "last segment's average" in _tip(bar, "prefill")
        set_language("zh")
        bar.retranslate_ui()
        assert "上一段的均值" in _tip(bar, "prefill")
    finally:
        set_language(back)


def test_first_task_prefill_average_is_there_during_its_own_decode(temp_settings):
    """回归（报告的 bug）：“第一次 prefill 完了到 decode 时 prefill 那里会显示 -，
    第二次就显示出来”。

    根因不在指标带，而在数据源：`print_timings()`（`prompt eval time` /
    `eval time`）只在任务**结束**分支里调（llama.cpp server-context.cpp），所以第一个
    任务的 decode 阶段全仓没有任何 prefill 均值可用 —— 第二个任务才拿得到上一个
    任务的那对。修法是多认两行**阶段运行中**的 slot print_timing（下面直接重放真实环境里
    的 last_run.log 里的真实行）。
    """
    _qapp()
    w = _window(temp_settings)
    try:
        w.live_metrics.set_running(True)
        w.live_metrics.set_slots_state("available")
        w.live_metrics.set_metrics_state("available")
        # prefill 还在跑（阶段内的累计均值，每约 1s 一行）
        w._parse_log_line(
            "0.22.925.546 I slot print_timing: id  0 | task 10 | prompt processing,"
            " n_tokens =  25814, progress = 1.00, t =   9.09 s / 2838.98 tokens per second")
        # 进入 decode：本窗口没有 prefill 活动，而本任务的精确均值（prompt eval time）
        # 还没打 —— 以前这里就是破折号
        w.live_metrics.update({"prefill_tps": None, "decode_tps": 104.0,
                               "ctx_frac": 0.5, "ctx_used": 2048, "ctx_total": 4096})
        assert _val(w.live_metrics, "prefill") == "2839.0 t/s"
        assert _val(w.live_metrics, "decode") == "104.0 t/s"
        # 生成中的 tg 行把 decode 均值也带进来（任务结束前就能读到）
        w._parse_log_line(
            "0.26.103.860 I slot print_timing: id  0 | task 10 | n_gen =    310,"
            " tg = 102.37 t/s, tg_3s = 102.70 t/s")
        assert w.live_metrics._last_task["decode"] == (102.37, 310)
        # 任务结束：精确的那对覆盖阶段内的累计值（取精确值，不取 tg_3s 那种窗口值）
        w._parse_log_line(
            "2.43.428.294 I slot print_timing: id  0 | task 10 | prompt eval time ="
            "    9333.32 ms / 25825 tokens (    0.36 ms per token,  2766.97 tokens per second)")
        w._parse_log_line(
            "2.43.428.299 I slot print_timing: id  0 | task 10 |        eval time ="
            "  140342.79 ms / 15364 tokens (    9.14 ms per token,   109.47 tokens per second)")
        assert w.live_metrics._last_task["prefill"] == (2766.97, 25825)
        assert w.live_metrics._last_task["decode"] == (109.47, 15364)
    finally:
        w.close()


def test_last_task_speeds_come_from_the_log_and_reach_the_row(temp_settings):
    """接线：slot print_timing 日志行 → runtime info 数值键 → 指标带。

    这是全仓唯一的数据源：没有 MainWindow._parse_log_line 里那一同步，带上的
    均值分支就是死代码（而日志行只到 runtime info，带自己读不到）。
    """
    _qapp()
    w = _window(temp_settings)
    try:
        w.live_metrics.set_running(True)
        w.live_metrics.set_slots_state("available")
        w._parse_log_line(
            "slot print_timing: id  0 | task 0 | prompt eval time =   37262.14 ms"
            " / 74152 tokens (    0.50 ms per token,  1990.01 tokens per second)")
        w._parse_log_line(
            "slot print_timing: id  0 | task 0 |        eval time =    2105.08 ms"
            " /   196 tokens (   10.80 ms per token,    92.63 tokens per second)")
        assert w._runtime_info["prompt_tps_last"] == 1990.01
        assert w.live_metrics._last_task["prefill"] == (1990.01, 74152)
        assert w.live_metrics._last_task["decode"] == (92.63, 196)
        # 没实时值时真的画到格子上
        assert _val(w.live_metrics, "prefill") == "1990.0 t/s"
        # 停服/异常退出：_reset_runtime_state 一并清空（回到 —）
        w._reset_runtime_state()
        assert w.live_metrics._last_task == {}
    finally:
        w.close()


def test_ctx_percent_is_painted_inside_the_bar():
    """ctx 的百分比画在**计量条里面**（后来的定案），并且绘制路径真的跑得起来。

    这条测试首先是“进程别死”：`_CtxMeter.paintEvent` 是 C++ 绘制路径调的虚函数，
    在里面抛异常不会变成 traceback，而是整个进程静默 fastfail（写错枚举名
    `QStyle.ComplexControl.CE_ProgressBar`（它在 ControlElement 里）就踩过一次：
    整条 pytest 并成 21 个后就没了输出，faulthandler 也说不了话）。grab() 会真走
    一遍 paintEvent → 它能返回位图就说明路径是通的。

    像素对比只对比“同一个条、只有一个变量 = 条里有没有字”：把文字清空再抓一张，
    两图必须不同（差异只能来自文字），而不是去断言具体颜色（offscreen 平台的
    字体渲染与真机不同，写死像素必挂）。
    """
    app = _qapp()
    bar = _live(_bar())
    bar.resize(bar.sizeHint().width(), 34)
    bar.show()
    for _ in range(6):
        app.processEvents()
    try:
        meter = bar._tiles["ctx"][2]
        assert meter is bar._tiles["ctx"][1]      # 条外没有第二个数字部件
        assert _val(bar, "ctx") == "42.3%"        # 数字 + % 全部在条里
        with_text = meter.grab().toImage()
        assert not with_text.isNull()
        text = meter.text()
        meter.set_text("")
        without = meter.grab().toImage()
        meter.set_text(text)
        diffs = [(x, y) for y in range(with_text.height())
                 for x in range(with_text.width())
                 if with_text.pixel(x, y) != without.pixel(x, y)]
        assert diffs, "条里的文字一个像素都没画上"
        xs = [x for x, _y in diffs]
        ys = [y for _x, y in diffs]
        # 文字居中且完整地在条内（左右各留一点边 → 没被条裁掉）
        assert min(xs) > 0 and max(xs) < meter.width() - 1, (min(xs), max(xs))
        assert max(ys) - min(ys) >= 4, ys        # 真字的身高，不是拖动一个像素
    finally:
        bar.close()


def test_bar_ctx_bar_color_tiers():
    _qapp()
    bar = _bar()
    bar.set_running(True)
    for frac, color in ((0.5, "#16a34a"), (0.75, "#d97706"), (0.95, "#dc2626")):
        bar.update({"ctx_frac": frac, "ctx_used": None, "ctx_total": None})
        assert color in bar._tiles["ctx"][2].styleSheet()
    # 无读数（/slots 还没回数据）→ 计量条为空、写 0.0%（后来的要求：常驻，
    # 不再是破折号；chunk 宽 0 所以什么也不画）
    bar.update({})
    assert bar._tiles["ctx"][2].value() == 0
    assert _val(bar, "ctx") == "0.0%"
    # 真的读不到（/slots 被关）→ 清空样式 + 破折号（旧版空轨道像渲染 bug 的方块）
    bar.set_slots_state("off")
    assert bar._tiles["ctx"][2].styleSheet() == ""
    assert _val(bar, "ctx").startswith("—")


def test_bar_metrics_unavailable_dims_right_group():
    _qapp()
    bar = _bar()
    bar.set_running(True)
    bar.set_metrics_state("unsupported")
    assert all(bar._tiles[k][0].isVisibleTo(bar)
               for k in bar._ALL_KEYS)     # 运行中：仍是两组指标视图
    right = ("total_in", "cached_in", "total_out", "hit_rate")
    assert all(_val(bar, k).startswith("—") for k in right)
    # 未勾选 → "勾选并重启" tooltip
    assert "Prometheus" in _tip(bar, "total_in")
    # 已勾选 → "重启后生效" tooltip
    bar.set_metrics_checked(True)
    assert "重启服务" in _tip(bar, "total_in")


def test_bar_session_totals_survive_the_metrics_endpoint_dying():
    """端点半路挂了（error）：已经不为 0 的累计值继续显示，不藏成破折号。

    要求：“右边那几个指标，是否也符合这个逻辑：表达这次 session 状态、累积的
    数值（非瞬时值），只要不为 0，就要保持一直显示” —— 之前唯一违反这条的就是
    `metrics_state` 一变成 error/unsupported 就整组改破折号（把手里已有的数藏了）。
    次要色 + tooltip 把“为什么不再更新”写在最前面；**一个数都没读到过**时仍是
    破折号（未知≠0）。
    """
    _qapp()
    bar = _live(_bar())          # 运行中 + 两端可用 + 一帧完整数据（累计组非 0）
    assert _val(bar, "total_in") == "1.5K"
    normal = bar._tiles["total_in"][1].text()
    assert bar._text in normal and bar._muted not in normal
    bar.set_metrics_state("error")
    # 数字留在原地（而不是变破折号），转次要色，tooltip 先说原因
    assert _val(bar, "total_in") == "1.5K"
    assert _val(bar, "cached_in") == "500"
    assert _val(bar, "total_out") == "800"
    assert _val(bar, "hit_rate") == "33.3%"
    html = bar._tiles["total_in"][1].text()
    assert bar._muted in html and bar._text not in html
    tip = _tip(bar, "total_in")
    assert "/metrics" in tip and "1,500" in tip
    # 新结构：第一行永远是全名，第二行是精确值，第三行才是“最后已知值”
    assert tip.startswith("输入 token\n1,500 tokens\n")
    # /metrics 恢复 → 回到主色（不需要新数据也能恢复：状态信号自己会回来）
    bar.set_metrics_state("available")
    assert bar._text in bar._tiles["total_in"][1].text()
    # 一个数都没读到过 → 仍是破折号
    bar2 = _bar()
    bar2.set_running(True)
    bar2.set_slots_state("available")
    bar2.set_metrics_checked(True)
    bar2.set_metrics_state("unsupported")
    assert all(_val(bar2, k).startswith("—") for k in bar2._METRIC_KEYS)


def test_bar_slots_off_dims_left_group_and_row_stays():
    _qapp()
    bar = _bar()
    bar.set_running(True)
    bar.set_metrics_state("unsupported")
    bar.set_slots_state("off")
    left = ("prefill", "decode", "ctx")
    assert all(_val(bar, k).startswith("—") for k in left)
    assert "/slots" in _tip(bar, "prefill")
    # 常驻显示：双组全灰也不隐藏整行（show() 后 isHidden() 才是显式状态
    # —— 从未 show 的 widget 恒报 True）
    bar.show()
    assert not bar.isHidden()


def test_bar_has_no_status_dot_any_more():
    """2026-11 改版：条带里那个绿色小圆点删掉了（要求：“metric 行那个绿色小圆点
    删了或者移动到运行时间那”）→ 运行状态由状态栏那一个点表达（见
    tests/test_right_tabs_e15.py::test_status_dot_tracks_run_and_endpoint_state），
    条带变成纯数据。“端点是否应答”仍在这里判定，交给状态栏染色。"""
    from PyQt6.QtWidgets import QWidget
    _qapp()
    bar = _bar()
    assert bar.findChildren(QWidget, "metricDot") == []
    assert not hasattr(bar, "_dot")
    assert not hasattr(bar, "_set_dot")
    assert bar.endpoints_alive() is True          # unknown 按“活”算
    bar.set_slots_state("off")
    assert bar.endpoints_alive() is True          # /metrics 仍可能应答
    bar.set_metrics_state("unsupported")
    assert bar.endpoints_alive() is False


def test_bar_idle_shows_the_metric_cells_not_a_hint():
    """后来：未运行时**不再**折叠成一句提示。

    意见是：“这行文字换成指标值，即
    不用启动后再显示出来，一直都显示" → 提示语删除，未运行时七格常驻。

    钉住：① 未运行时七格都可见：速度格是破折号，**上下文条与累计组是 0**
    （0 是个值，不是“读不到”）；② 原因在 tooltip（未勾选 --metrics 时带引导，
    勾选后换成通用说明）；③ 启动前后**只有一种排版** → 地板不变 → 窗口最小宽度
    不随服务启停跳（旧版提示语比七格窄得多，模式切换会改变整行需要的宽度）。
    """
    _qapp()
    bar = _bar()
    assert bar._tiles["prefill"][0].isVisibleTo(bar)
    # 速度格：未知 → 破折号
    assert all(_val(bar, k).startswith("—") for k in bar._SPEED_KEYS)
    # 上下文条：0.0%，不是破折号（要求：“停止了就不显示了，应该一直显示，
    # 哪怕刚开始时也应为 0”）—— 没启动就是 KV 为空，0 是个值
    assert _val(bar, "ctx") == "0.0%"
    assert bar._tiles["ctx"][2].value() == 0
    # 累计组：**0**，不是破折号（后来的要求："session 里的值开始不应该没有值，
    # 开始就是 0"）—— 计数从 0 起算，一排破折号看着像坏了
    assert _val(bar, "total_in") == "0"
    assert _val(bar, "cached_in") == "0"
    assert _val(bar, "total_out") == "0"
    assert _val(bar, "hit_rate") == "0.0%"
    assert "服务未启动" in _tip(bar, "prefill")
    # 三行结构（名称 / 精确值 / 一行身份）：未启动时七格共用“服务未启动”那一句。
    # “怎么勾上 --metrics”不再拼到这里：没启动时不可行动，启动后累计格自己会说
    assert _tip(bar, "total_in") == "输入 token\n0 tokens\n服务未启动"
    assert "Prometheus" not in _tip(bar, "total_in")
    bar.set_metrics_checked(True)
    assert "Prometheus" not in _tip(bar, "total_in")
    # Maximum：宽度 = 内容宽，不给就不撑（富余归外层合一行的 stretch）
    bar.resize(1100, 34)
    bar.layout().activate()
    floor_before = bar.min_content_width()
    bar.set_running(True)
    _live(bar)
    assert _val(bar, "prefill") == "85.3 t/s"
    assert bar.min_content_width() == floor_before, (
        bar.min_content_width(), floor_before)


def test_theme_and_language_sync_survives_reapply():
    """set_theme_colors 会被 _apply_theme 反复调用：格标签是 ElidingLabel
    （只认 palette），颜色必须随之更新，文案不能被刷掉。"""
    _qapp()
    bar = _bar()
    bar.set_theme_colors("#cdd6f4", "#7f849c", "#9399b2")
    _live(bar)          # 一帧完整数据（默认处在 prefill 阶段）
    assert "#cdd6f4" in bar._tiles["prefill"][1].text()
    from PyQt6.QtGui import QPalette
    # 不在阶段的格标签 → info
    cap = bar._tiles["total_in"][0].property("cap")
    assert cap.palette().color(QPalette.ColorRole.Text).name() == "#9399b2"
    # 正在进行的阶段 → 阶段色（这里没传 prefill/decode → 浅色默认值）；
    # 换主题时 MainWindow 会重注两套阶段色，这里验证同一入口不会把它洗回 info
    pre = bar._tiles["prefill"][0].property("cap")
    assert pre.palette().color(
        QPalette.ColorRole.Text).name() == bar._phase_colors["prefill"]
    assert "Prefill 速度" in _tip(bar, "prefill")


def test_bar_no_http_state():
    _qapp()
    bar = _bar()
    bar.set_running(True)
    bar.set_no_http(True)
    # 无 HTTP 端点：七格常驻，专门说明在 tooltip（区别于"未启动"）。
    # 实时组未知 → 破折号；累计组是"启动以来"的计数 → 0（后来的定案）
    assert bar._tiles["prefill"][0].isVisibleTo(bar)
    assert all(_val(bar, k).startswith("—")
               for k in bar._SPEED_KEYS + ("ctx",))
    assert all(_val(bar, k).startswith("0")
               for k in bar._METRIC_KEYS)
    assert "unix socket" in _tip(bar, "prefill")
    # 停掉后回落"未启动"说明（_no_http 一并重置）
    bar.set_running(False)
    assert "服务未启动" in _tip(bar, "prefill")
    assert "unix socket" not in _tip(bar, "prefill")


# ---------------------------------------------------------------------------
# MainWindow 接线（offscreen）
# ---------------------------------------------------------------------------

import core.config as CC  # noqa: E402
from PyQt6.QtCore import QThread, pyqtSignal  # noqa: E402


class _FakeLiveWorker(QThread):
    """LiveStatsWorker 替身：不碰网络、run() 空转。"""
    stats_ready = pyqtSignal(object)
    metrics_state = pyqtSignal(str)
    slots_state = pyqtSignal(str)

    def __init__(self, host, port, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True

    def run(self):
        return


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(CC, "SETTINGS_FILE", settings_file)
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr(CC, "PRESETS_DIR", presets_dir)
    yield settings_file


def _window(temp_settings):
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    return MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))






def test_metrics_row_floor_keeps_values_visible(temp_settings):
    """2026-11 改版：条带是 Maximum 策略（只长到内容宽），但这**不等于**压不扁它
    —— 容器比布局最小值还窄时 QLayout 会把每一项都压到自己的最小值以下。实测窗口
    停在最小宽度、指标态下：条带实得 446px、数值单元从 sizeHint 88px 被压到 30px，
    **数字直接看不见了**，而这行的全部意义就是那几个数字。

    修法：`MainWindow._sync_panel_min` 把合一行**按部件**算进窗口最小宽度
    （按钮 sizeHint + 间距 + `LiveMetricsBar.min_content_width()`，后者由布局自己
    量：数值 + 计量条 + 固定间距，标签可省略所以不计）。窗口够宽 → 行不需要压缩
    → 数值完整，被省略的只有标签。

    钉住：① 窗口最小宽度 ≥ 合一行的部件和；② 停在最小宽度的指标态下，条带宽度 ≥
    地板、右端在行内、每个数值 ≥ 自身 sizeHint；③ 地板与模式无关（服务启停不改变
    窗口最小宽度）；④ 地板由布局量出（与捆绑字体同源），不是写死的常数。"""
    from ui.live_metrics import _BAR_W
    app = _qapp()
    w = _window(temp_settings)
    try:
        bar = w.live_metrics
        assert bar.min_content_width() > 0

        def settle():
            """让最小宽度按"当前量到的地板"重算一遍。

            真实机器上字体随首显示一起就位；offscreen 平台的字体数据库要晚几轮
            事件循环才可用（同一进程内构造期量到 344、就位后 551），应用自己靠
            `MainWindow._resync_minimum_after_show` / 顶层 resize 补上这一次，
            测试里走的是同一条路径 —— 断言因此不依赖平台的字体时机。"""
            w._resync_if_strip_floor_changed()
            for _ in range(8):
                app.processEvents()

        w.show()
        for _ in range(8):
            app.processEvents()
        settle()
        floor = bar.min_content_width()
        idle_min = w.minimumWidth()
        # ① 窗口最小宽度覆盖合一行的部件和（不读布局缓存的那个算法）
        row = w.control_bar
        parts = (sum(b.sizeHint().width() for b in
                     (w.btn_start, w.btn_stop, w.btn_copy_cmd, w.btn_webui))
                 + row.layout().spacing() * 4 + floor)
        assert w.minimumWidth() >= parts, (w.minimumWidth(), parts)

        _live(bar)
        settle()
        assert all(bar._tiles[k][0].isVisibleTo(bar) for k in bar._ALL_KEYS)
        # ③ 模式无关：服务启动不改变窗口最小宽度
        assert bar.min_content_width() == floor
        assert w.minimumWidth() == idle_min, (w.minimumWidth(), idle_min)

        w.resize(w.minimumWidth(), w.minimumHeight())
        for _ in range(8):
            w._right_panel.layout().activate()
            app.processEvents()
        # ② 停在最小宽度：条带不被压扁，右端不出行，数值完整可见
        assert bar.width() >= floor, (bar.width(), floor)
        assert bar.geometry().right() <= row.width(), (row.width(), bar.geometry())
        for key, (_cell, value, meter) in bar._tiles.items():
            assert value.isVisibleTo(bar), key
            if meter is value:
                # ctx：定长计量条（数字在里面），定长就是它的"完整可见"标准
                assert value.width() == _BAR_W, (key, value.width())
                continue
            assert value.width() >= value.sizeHint().width() - 1, (
                key, value.width(), value.sizeHint().width())
        # ④ 地板由控件自己的最小宽度实时累加（同一个排版引擎），与显隐无关
        assert bar.layout().minimumSize().width() <= floor, (
            bar.layout().minimumSize().width(), floor)
    finally:
        w.close()


def test_live_row_position_and_visible_by_default(temp_settings):
    _qapp()
    w = _window(temp_settings)
    try:
        # 2026-11 改版：指标行与启动按钮**合成一行**（self.control_bar），这一行
        # 贴在右栏 tab widget 下方、是最后一个条目 → 三个 tab 都能看到指标。
        # isHidden() 是自身显式隐藏态 —— isVisible() 要求整条祖先链可见，未
        # show() 的窗口下恒为 False
        assert w.live_metrics.parent() is w.control_bar
        assert w.live_metrics.parent() is not w.params_tab
        rlay = w._right_panel.layout()
        assert (rlay.itemAt(rlay.count() - 1).widget() is w.control_bar)
        row = w.control_bar.layout()
        widgets = [row.itemAt(i).widget() for i in range(row.count())]
        widgets = [x for x in widgets if x is not None]
        assert widgets[-1] is w.live_metrics
        assert widgets.index(w.btn_start) < widgets.index(w.live_metrics)
        assert not w.live_metrics.isHidden()
        # 未运行：七格常驻 + 灰破折号（后来的定案），行本身也从不隐藏
        assert w.live_metrics._running is False
        assert w.live_metrics._tiles["prefill"][0].isVisibleTo(w.live_metrics)
        assert "服务未启动" in w.live_metrics._tiles["prefill"][0].toolTip()
        assert w._live_worker is None
    finally:
        w.close()


def _settle(app, win, width, height):
    win.resize(width, height)
    for _ in range(12):
        app.processEvents()


def test_live_row_visible_on_every_tab(temp_settings):
    """要求是：切到「日志输出」/「运行信息」时这一行也必须在——它现在在
    标签页外面（下方），不再属于 tab 1。"""
    from PyQt6.QtCore import QPoint
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        _settle(app, w, 1360, 860)
        assert w.tab_widget.count() == 3
        for index in range(w.tab_widget.count()):
            w.tab_widget.setCurrentIndex(index)
            _settle(app, w, 1360, 860)
            assert not w.live_metrics.isHidden()
            assert w.live_metrics.height() == 34
            assert w.live_metrics.width() >= 400
            # 行在标签页下方，且没被挤出右栏/窗口
            y_in_panel = w.live_metrics.mapTo(w._right_panel,
                                              QPoint(0, 0)).y()
            assert y_in_panel > w.tab_widget.geometry().bottom()
            assert w.live_metrics.mapTo(w.centralWidget(),
                                        QPoint(0, 0)).y() < w.height()
    finally:
        w.close()


def test_live_row_starts_on_ready_and_stops(temp_settings, monkeypatch):
    import ui.main_window as MW
    _qapp()
    w = _window(temp_settings)
    try:
        monkeypatch.setattr(MW, "LiveStatsWorker", _FakeLiveWorker)
        monkeypatch.setattr(
            w, "_get_current_values",
            lambda: {"host": "0.0.0.0", "port": 9931, "metrics": True})
        w._start_live_stats()
        worker = w._live_worker
        assert isinstance(worker, _FakeLiveWorker)
        assert worker._host == "127.0.0.1"  # 0.0.0.0 → 回环
        assert worker._port == 9931
        assert w.live_metrics._running is True
        assert w.live_metrics._metrics_checked is True
        assert w.live_metrics._tiles["prefill"][0].isVisibleTo(w.live_metrics)
        w._stop_live_stats()
        assert w._live_worker is None
        assert worker.stop_requested is True
        # 停止后仍是同一副七格（数值回灰破折号），行不隐藏
        assert w.live_metrics._running is False
        assert w.live_metrics._tiles["prefill"][0].isVisibleTo(w.live_metrics)
    finally:
        w.close()


def test_live_row_never_starts_for_unix_socket_host(temp_settings, monkeypatch):
    import ui.main_window as MW
    _qapp()
    w = _window(temp_settings)
    try:
        monkeypatch.setattr(MW, "LiveStatsWorker", _FakeLiveWorker)
        monkeypatch.setattr(
            w, "_get_current_values",
            lambda: {"host": "/tmp/llama.sock", "port": 9931,
                     "metrics": True})
        w._start_live_stats()
        assert w._live_worker is None
        # unix socket 无 HTTP 端点：七格灰显 + 专门 tooltip（区别于"未启动"）
        assert w.live_metrics._no_http is True
        assert "unix socket" in w.live_metrics._tiles["prefill"][0].toolTip()
    finally:
        w.close()


def test_live_row_stays_visible_when_both_groups_off(temp_settings,
                                                     monkeypatch):
    import ui.main_window as MW
    _qapp()
    w = _window(temp_settings)
    try:
        monkeypatch.setattr(MW, "LiveStatsWorker", _FakeLiveWorker)
        monkeypatch.setattr(
            w, "_get_current_values",
            lambda: {"host": "127.0.0.1", "port": 9931, "metrics": False})
        w._start_live_stats()
        # 双组全灰 → 仍是指标视图（点变琥珀 + tooltip 说明），不隐藏整行
        w.live_metrics.set_metrics_state("unsupported")
        w.live_metrics.set_slots_state("off")
        assert not w.live_metrics.isHidden()
        assert all(w.live_metrics._tiles[k][0].isVisibleTo(w.live_metrics)
                   for k in w.live_metrics._ALL_KEYS)
        # 之后 /slots 恢复应答 → 数值直接渲染（行本就一直在）
        w.live_metrics.set_slots_state("available")
        w._on_live_stats({"decode_tps": 3.0})
        assert _val(w.live_metrics, "decode") == "3.0 t/s"
    finally:
        w.close()
