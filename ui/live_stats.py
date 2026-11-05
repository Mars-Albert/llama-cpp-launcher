# -*- coding: utf-8 -*-
"""实时指标数据源：轮询运行中 llama-server 的 HTTP 端点（实时指标行）。

纯函数（无 Qt 依赖，可无显示环境单测）+ 一个 QThread 轮询器：

- GET /slots    每 ~1s —— 每 slot 的 *live* 计数器。服务端按任务重置它们
                （任务开始时 n_prompt_tokens_processed 清零、n_decoded 随
                slot 归零），所以两次轮询之间计数器 *变小* 即为任务边界：
                差分逻辑丢弃该窗口的增量并重新起算，绝不产生负速度。
- GET /metrics  每 ~5s —— 只取 Prometheus *累计 counter*
                （prompt_tokens_total / prompt_tokens_cached_total /
                tokens_predicted_total）。刻意不用 gauge：decode gauge
                只在任务结束时入桶（长生成期间恒 0），且每次抓取都会
                reset_bucket，轮询太频会切碎真实 Prometheus 抓取者的窗口。

端点可用性靠 *探测* 而不是猜参数：/metrics 未勾选 --metrics 时不存在，
/slots 默认开、只有 extra_args 里 --slots 关闭时才 404。404 会永久定格
该组的"不可用"（会话内不重试）；连接失败按常量重试若干次后同样定格。
METRICS/SLOT_GET 任务在 decode 让出期间也被服务端处理
（server-context.cpp 的 yield 豁免），所以生成中轮询不阻塞出 token。
"""
import json
import logging
import math
import re
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

from core.constants import (LIVE_STATS_METRICS_PROBE_MAX_TRIES,
                            LIVE_STATS_METRICS_SECONDS,
                            LIVE_STATS_SLOTS_SECONDS)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /slots：差分
# ---------------------------------------------------------------------------

def _int_or_zero(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def diff_slots(prev, slots, now):
    """把一次 /slots 快照与上一次差分。

    prev: 上一次调用返回的状态 dict（首轮为 None）。slots: 解析后的
    /slots JSON（list）。now: 单调时钟时间戳。

    返回 (result, new_prev)：
      result —— {"prefill_tps", "decode_tps", "ctx_frac", "ctx_used",
                 "ctx_total", "active", "prefilling", "decoding",
                 "task_cache_hit", "task_cache_tokens"}；速度字段为 None 表示
                 "本窗口无该活动"（首轮 / 任务边界 / 纯 decode 窗口里的 prefill）；
                 `prefilling` / `decoding` = 此刻有 slot 在算输入 / 在生成
                 （多 slot 时可能同时 True）。
                 上下文占用 = max(slot 账本 `n_prompt_tokens`, 任务账本
                 `processed + cached + decoded`)；两个都不能单独用，也不能相加，
                 理由见函数 docstring 与下方注释。
      new_prev —— 下次调用作为 prev 传入。

    两个账本：**任务账本** = `n_prompt_tokens_processed +
    n_prompt_tokens_cache + n_decoded`（与 llama.cpp WebUI 的 `contextUsed` 同一
    套），**slot 账本** = `n_prompt_tokens`（= `slot.prompt.tokens.size()`）。上下文
    占用取两者的 **较大值**，因为任务账本只在任务期间存在：任务一结束
    `server_slot::reset()` 就把 `stats = {}`（而 prompt 缓存故意保留），三个计数器
    归零但 KV 里整段对话还在 → 只用任务账本会“一空闲就显示 0%”（报告的 bug，
    见 `test_diff_slots_ctx_keeps_the_occupancy_when_the_slot_goes_idle`）。
    **绝不能把两个账本相加**（旧算法 `n_prompt_tokens + n_decoded` 就是把生成
    token 数了两遍，同一个坑见下方注释）。

    计数器按任务在服务端重置，new < old 即任务边界：该 slot 本窗口只重新
    起算基线。n_prompt_tokens_cache 在整个任务内固定，因此"本任务缓存
    命中率"只在 id_task 变化时更新（去重，避免同一任务反复覆盖）。
    """
    result = {
        "prefill_tps": None,
        "decode_tps": None,
        "ctx_frac": None,
        "ctx_used": None,
        "ctx_total": None,
        "active": False,
        # 当前阶段（指标带的格标签颜色拿它做提示）：多 slot 时两个可能同时为 True
        "prefilling": False,
        "decoding": False,
        "task_cache_hit": None,
        "task_cache_tokens": None,
    }
    prev = prev or {}
    prev_slots = prev.get("slots", {})
    prev_ts = prev.get("ts")
    dt = (now - prev_ts) if prev_ts is not None else None
    if dt is not None and dt <= 0:
        dt = 0.001
    task = prev.get("task")
    d_pre = 0
    d_dec = 0
    new_slots = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        sid = slot.get("id")
        next_token = slot.get("next_token")
        if not isinstance(next_token, list) or not next_token:
            next_token = [{}]
        decoded = _int_or_zero(next_token[0].get("n_decoded"))
        processed = _int_or_zero(slot.get("n_prompt_tokens_processed"))
        n_prompt = _int_or_zero(slot.get("n_prompt_tokens"))
        n_cached = _int_or_zero(slot.get("n_prompt_tokens_cache"))
        n_ctx = _int_or_zero(slot.get("n_ctx"))
        active = bool(slot.get("is_processing"))
        result["active"] = result["active"] or active
        # 阶段判定：**看 `n_decoded` 是不是还在 0**。不用 `processed < n_prompt_tokens`
        # 判“输入还没算完”：投机解码会把生成 token 追进 `n_prompt_tokens`（那个历史
        # 长度，见上面 ctx 那段注释），使该式在生成期间也成立 → 阶段永远停在 prefill。
        if active and decoded > 0:
            result["decoding"] = True
        elif active:
            result["prefilling"] = True

        old = prev_slots.get(sid)
        if old is not None:
            # decoded < old：任务边界（计数器重置）—— 只重新起算，不取负
            if decoded > old["decoded"]:
                d_dec += decoded - old["decoded"]
            if processed > old["processed"]:
                d_pre += processed - old["processed"]
        new_slots[sid] = {"decoded": decoded, "processed": processed}

        if n_ctx > 0:
            # 上下文占用：两个账本取**较大者**。
            #
            # ① 任务账本 `processed + cached + decoded`：与 llama.cpp 自带 WebUI
            #    同一套账（tools/ui `contextUsed` = `prompt_n + cache_n +
            #    predicted_n`，而 server-common.cpp 的 timings 就是
            #    `n_prompt_processed` / `n_prompt_cached` / `n_gen`）。
            # ② slot 账本 `n_prompt_tokens` = `slot.prompt.tokens.size()`：这个 slot
            #    真正占着的 token 数。prefill 期间随处理进度增长（每批
            #    `prompt.tokens.insert(...)`，见 server-context.cpp：“caller need to
            #    update prompt.tokens after a successful call to keep track of the
            #    processing progress”），生成期间每接受一个 `push_back`，新请求只复用
            #    前缀时 `keep_first(n_past)` 会把它砍到前缀长，`prompt_clear()` 清零
            #    —— 不写虚数，也不写陈旧数。
            #
            # **为何需要两个（末次改版，要求：“不活动时 context 怎么还是 0？”）**：任务
            # 一结束 `server_slot::release()` → `reset()` 就 `stats = {}`（普通 slot 的
            # prompt **不**清，只有 child/stateless/tts 才 `prompt_clear()`），于是
            # `n_prompt_tokens_processed` / `_cache` / `n_decoded` 全变 0，而
            # `n_prompt_tokens` 仍是整段对话长度（`ptask = task ? task : task_prev`
            # 所以任务后这几个字段依旧发布）。只取①⇒空闲时假性 0%，而 KV 里几
            # 万 token 还占着（prompt cache 复用的整个意义）。取 max ⇒ 任务内两本账
            # 本来就应该相当（旧断言不受影响），任务后只剩②。
            #
            # **绝不能相加**：投机解码（`--spec-type` / `--model-draft`，本仓库预设
            # 常用的 draft-mtp 就是）每验收到一批 token 就把它们追进②那段历史，而
            # `n_decoded` 计的正是同一批 —— 旧算法 `n_prompt + decoded` 把生成部分
            # **数了两遍**：decode 期间明显偏大（偏差 = 已生成的全部 token），下一个
            # 请求一进 prefill（n_decoded 归零）又“莫名变准”（上一版报告的 bug，
            # 见 test_diff_slots_ctx_is_not_double_counted_while_spec_decoding）。
            #
            # 老服务端没有①那两个字段时退回 `n_prompt + decoded`（那个年代
            # `n_prompt_tokens` = `task->n_tokens()`，是个常量，不含生成 token），
            # 否则新算法会永远算出 0。
            # 分母用的是 **slot 自己的** n_ctx（`n_ctx_slot()`）—— “这个槽位有多满”；
            # parallel = 1 时它等于 WebUI 用的 `/props n_ctx`，多槽位时它就是单槽上限
            # （比除以全局 ctx 更符合“取最忙 slot”这个展示意图）。
            if "n_prompt_tokens_processed" in slot:
                used = max(n_prompt, processed + n_cached + decoded)
            else:
                used = n_prompt + decoded
            frac = used / n_ctx
            if result["ctx_frac"] is None or frac > result["ctx_frac"]:
                result["ctx_frac"] = frac
                result["ctx_used"] = used
                result["ctx_total"] = n_ctx

        if active and n_prompt > 0:
            tid = slot.get("id_task")
            if tid is not None and tid != task:
                task = tid
                result["task_cache_hit"] = min(1.0, n_cached / n_prompt)
                result["task_cache_tokens"] = n_prompt

    if dt is not None:
        if d_pre:
            result["prefill_tps"] = d_pre / dt
        if d_dec:
            result["decode_tps"] = d_dec / dt
    return result, {"ts": now, "task": task, "slots": new_slots}


# ---------------------------------------------------------------------------
# /metrics：累计 counter（绝不用 gauge —— 见模块 docstring）
# ---------------------------------------------------------------------------

_METRIC_COUNTERS = (
    ("prompt", "llamacpp:prompt_tokens_total"),
    ("prompt_cached", "llamacpp:prompt_tokens_cached_total"),
    ("predicted", "llamacpp:tokens_predicted_total"),
)
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_metrics(text):
    """从 /metrics 响应体提取三个累计 counter。

    容错：缺行/NaN 直接缺席（全缺时返回 {}）。取值取行内 *最后一个*
    数字，可选的 {labels} 块不会混进来；名字后缀撞车
    （…prompt_tokens_total_seconds 之类）按 "_" 边界排除。
    """
    out = {}
    for key, name in _METRIC_COUNTERS:
        for line in text.splitlines():
            s = line.strip()
            if not s.startswith(name):
                continue
            if s[len(name):len(name) + 1] == "_":
                continue
            body = s[len(name):]
            if body.startswith("{"):
                close = body.find("}")
                if close == -1:
                    break
                body = body[close + 1:]
            nums = _NUMBER_RE.findall(body)
            if nums:
                try:
                    value = float(nums[-1])
                except ValueError:
                    break
                if not math.isnan(value):
                    out[key] = value
            break
    return out


def probe_metrics(host, port, timeout=2.0):
    """一次性 GET /metrics → "available" | "unsupported" | "error"。

    "unsupported" 对会话永久：404 或服务端 "does not support metrics"
    响应体（端点存在但 --metrics 未开）。"error" = 连接失败，由 worker
    在后续 tick 重试（有上限）。
    """
    url = f"http://{host}:{port}/metrics"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", "replace")
        return "available" if "llamacpp:" in body else "error"
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(2048).decode("utf-8", "replace").lower()
        except Exception:
            body = ""
        if exc.code == 404 or "does not support metrics" in body:
            return "unsupported"
        return "error"
    except Exception:
        return "error"


def fetch_url(host, port, path, timeout=1.0):
    """GET 一个端点 → (text, err)；err 为 None | "404" | "error"。"""
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read(1 << 20).decode("utf-8", "replace"), None
    except urllib.error.HTTPError as exc:
        return None, ("404" if exc.code == 404 else "error")
    except Exception:
        return None, "error"


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------

# 窗口关闭时仍在跑的 worker 由模块级引用保活（同 main_window 的
# _active_meta_workers 规矩：销毁 *运行中* 的 QThread 在本 PyQt6 构建里
# 是原生崩溃）；每个 worker 在 run() 返回时自行移除。
_active_live_workers: set = set()


class LiveStatsWorker(QThread):
    """在 GUI 线程之外轮询 GET /slots（1s）+ GET /metrics（5s）。

    stats_ready 在每次 /slots 成功解析、以及每次 /metrics 抓取更新时发
    合并 dict（差分速度 + 当前占用 + 最近一次累计 counter；/metrics 触
    发的 emit 复用最近一次 /slots 差分，避免把速度格刷成 "—"）；两个
    *状态* 信号只在状态迁移时发：
      - metrics_state: "available" | "unsupported" | "error"
      - slots_state:   "available" | "off"
    跨线程自动 queued 投递到 GUI。
    """
    stats_ready = pyqtSignal(object)
    metrics_state = pyqtSignal(str)
    slots_state = pyqtSignal(str)

    def __init__(self, host, port, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = int(port)
        self._stop = False
        self._last_metrics = {}
        self._last_slots = None  # 最近一次 diff_slots 的 result（合并用）

    def request_stop(self):
        self._stop = True

    def run(self):
        _active_live_workers.add(self)
        try:
            self._run_body()
        except Exception:  # 轮询器永不致命：静默退出，行保持最后状态
            log.exception("live stats worker died")
        finally:
            _active_live_workers.discard(self)

    def _sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while not self._stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def _merged(self):
        s = dict(self._last_slots) if self._last_slots else {}
        m = self._last_metrics
        s.update({
            "prompt_total": m.get("prompt"),
            "prompt_cached_total": m.get("prompt_cached"),
            "predicted_total": m.get("predicted"),
        })
        return s

    def _fetch_metrics(self):
        text, err = fetch_url(self._host, self._port, "/metrics", timeout=2.0)
        if err is None:
            parsed = parse_metrics(text)
            if parsed:
                self._last_metrics.update(parsed)
                return True
        return False

    def _run_body(self):
        slots_prev = None
        next_met_at = 0.0
        met_state = "unknown"
        met_final = False
        met_tries = 0
        slots_off = False
        while not self._stop:
            now = time.monotonic()
            # --- /slots：每个 tick；404 = 端点被关，定格置灰
            if not slots_off:
                text, err = fetch_url(self._host, self._port, "/slots",
                                      timeout=1.0)
                if err == "404":
                    slots_off = True
                    self.slots_state.emit("off")
                elif err is None:
                    try:
                        slots = json.loads(text)
                    except ValueError:
                        slots = None
                    if isinstance(slots, list):
                        res, slots_prev = diff_slots(slots_prev, slots, now)
                        # 本任务缓存命中率只在 id_task 变化的窗口上报；
                        # 任务内后续窗口携带上一窗口的值（否则 tooltip
                        # 里的"本任务 x%"只存活一秒）
                        if (self._last_slots is not None
                                and res["task_cache_hit"] is None):
                            res["task_cache_hit"] = (
                                self._last_slots["task_cache_hit"])
                        self._last_slots = res
                        self.stats_ready.emit(self._merged())
                    # 空列表 = slot 尚未就绪（加载中）—— 继续轮询
                # 连接错误 = 瞬态 —— 保留最后状态，下个 tick 再试
            # --- /metrics：先探测，成功后每 5s 取 counter
            if met_state == "available":
                if now >= next_met_at:
                    next_met_at = now + LIVE_STATS_METRICS_SECONDS
                    if self._fetch_metrics():
                        self.stats_ready.emit(self._merged())
            elif not met_final and now >= next_met_at:
                next_met_at = now + 2.0
                met_state = probe_metrics(self._host, self._port)
                met_tries += 1
                self.metrics_state.emit(met_state)
                if met_state == "available":
                    next_met_at = now + LIVE_STATS_METRICS_SECONDS
                    self._fetch_metrics()
                elif met_state == "unsupported":
                    met_final = True
                elif met_tries >= LIVE_STATS_METRICS_PROBE_MAX_TRIES:
                    met_final = True  # 保持 "error"，本会话不再重试
            self._sleep(LIVE_STATS_SLOTS_SECONDS)
