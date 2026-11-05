"""Tests for the -lv 4 (trace) runtime-info pipeline.

llama.cpp >= #23021 (commit 67b2b7f2f "logs: reduce") maps library INFO to
TRACE, so the binary's default -lv 3 suppresses all the model-load / VRAM /
context detail lines. The launcher now defaults log_verbosity to 4; these
tests pin the new parser patterns (real lines from a -lv 4 run), the new
runtime-info rows, the low-verbosity hint, and the --verbose/--log-verbosity
emission interplay.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.params_schema import PARAMS_BY_KEY
from ui.command_builder import CommandBuilder
from ui.log_parser import parse_log_line
from ui.runtime_info import build_info_html


# ---------------------------------------------------------------------------
# parser: library INFO detail lines (visible at -lv 4)
# ---------------------------------------------------------------------------

def test_device_lines_nvidia_dual():
    info = {}
    parse_log_line(
        "  Device 0: NVIDIA GeForce RTX 5090, compute capability 9.0, VMM: yes, VRAM: 32579 MiB",
        info)
    parse_log_line(
        "  Device 1: NVIDIA GeForce RTX 2080, compute capability 7.5, VMM: no, VRAM: 8191 MiB",
        info)
    assert info["gpu0_name"] == "NVIDIA GeForce RTX 5090"
    assert info["gpu0_vram"] == "32579 MiB"
    assert info["gpu1_name"] == "NVIDIA GeForce RTX 2080"
    assert info["gpu1_vram"] == "8191 MiB"
    # first device fills the single-GPU fields
    assert info["gpu_name"] == "NVIDIA GeForce RTX 5090"
    assert info["gpu_vram"] == "32579 MiB"
    assert info["gpu_compute_cap"] == "9.0"


def test_device_line_amd():
    info = {}
    parse_log_line(
        "  Device 0: AMD Radeon RX 7900 XTX, gfx906 (0x00000906), VMM: no, Wave Size: 32, VRAM: 24576 MiB",
        info)
    assert info["gpu0_name"] == "AMD Radeon RX 7900 XTX"
    assert info["gpu0_vram"] == "24576 MiB"


def test_device_line_legacy():
    info = {}
    parse_log_line("Device 0: NVIDIA GeForce RTX 4090, compute capability 8.9, VRAM: 24564 MiB", info)
    assert info["gpu_name"] == "NVIDIA GeForce RTX 4090"
    assert info["gpu_vram"] == "24564 MiB"
    assert info["gpu_compute_cap"] == "8.9"


def test_using_device_line_gpu_and_cpu():
    info = {}
    parse_log_line(
        "llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090) (0000:01:00.0) - 30991 MiB free",
        info)
    assert info["gpu0_name"] == "NVIDIA GeForce RTX 5090"
    assert info["gpu0_free"] == "30991 MiB"
    assert info["gpu_name"] == "NVIDIA GeForce RTX 5090"
    assert info["free_vram"] == "30991 MiB"
    parse_log_line(
        "main: using device CPU (12th Gen Intel(R) Core(TM) i7-12700K) (unknown id) - 53243 MiB free",
        info)
    assert info["cpu_name"] == "12th Gen Intel(R) Core(TM) i7-12700K"


def test_model_buffers_single_gpu():
    info = {}
    parse_log_line("load_tensors:        CUDA0 model buffer size = 18904.69 MiB", info)
    parse_log_line("load_tensors:   CPU_Mapped model buffer size =   994.63 MiB", info)
    assert info["model_vram"] == "18904.69 MiB"
    assert info["cpu_buffer"] == "994.63 MiB"
    assert "model_vram_detail" not in info


def test_model_buffers_multi_gpu():
    info = {}
    parse_log_line("load_tensors:        CUDA0 model buffer size = 18904.69 MiB", info)
    parse_log_line("load_tensors:        CUDA1 model buffer size = 7800.00 MiB", info)
    assert info["model_vram"] == "26704.69 MiB"
    assert "CUDA0: 18904.69" in info["model_vram_detail"]
    assert "CUDA1: 7800.00" in info["model_vram_detail"]


def test_kv_buffers_summed():
    info = {}
    parse_log_line("llama_kv_cache:      CUDA0 KV buffer size =  9579.50 MiB", info)
    parse_log_line("llama_kv_cache:      CUDA0 KV buffer size =     2.50 MiB", info)  # e.g. SWA cache
    assert abs(info["kv_cache_total"] - 9582.0) < 1e-6


def test_compute_buffer():
    info = {}
    parse_log_line("sched_reserve:       CUDA0 compute buffer size =  36.14 MiB", info)
    assert info["compute_buffer"] == "36.14 MiB"


def test_graph_first_wins():
    info = {}
    parse_log_line("sched_reserve: graph nodes  = 4423", info)
    parse_log_line("sched_reserve: graph splits = 2", info)
    # draft/speculative context reserves later — must not overwrite the main ctx
    parse_log_line("sched_reserve: graph nodes  = 56", info)
    parse_log_line("sched_reserve: graph splits = 1", info)
    assert info["graph_nodes"] == "4423"
    assert info["graph_splits"] == "2"


def test_graph_compute_meta_fallback():
    info = {}
    parse_log_line("reserve_compute_meta: graph splits = 1, nodes = 823", info)
    assert info["graph_nodes"] == "823"
    assert "graph_splits" not in info


def test_prompt_cache_variants():
    info = {}
    parse_log_line("srv load_model: prompt cache is enabled, size limit: no limit", info)
    assert info["prompt_cache"] == "已启用（无上限）"
    info = {}
    parse_log_line("srv load_model: prompt cache is enabled, size limit: 2048 MiB", info)
    assert info["prompt_cache"] == "已启用（上限 2048 MiB）"
    info = {}
    parse_log_line("srv load_model: prompt cache is disabled - use `--cache-ram N` to enable it", info)
    assert info["prompt_cache"] == "已禁用"


def test_speculative_decoding_signals():
    info = {}
    parse_log_line("spec common_specu: adding speculative implementation 'draft-mtp'", info)
    assert info["speculative_decoding"] == "draft-mtp"
    info = {}
    parse_log_line(
        "common_speculative_init_result: creating MTP draft context against the target model 'm.gguf'", info)
    assert info["speculative_decoding"] == "MTP"
    # legacy line still works
    info = {}
    parse_log_line("srv load_model: speculative decoding will use checkpoints", info)
    assert info["speculative_decoding"] == "已启用"


def test_reasoning_preserve_variants():
    info = {}
    parse_log_line(
        "srv init: chat template supports preserving reasoning, it is enabled by default "
        "(may use more tokens, disable via --no-reasoning-preserve)", info)
    assert info["reasoning_preserve"] == "默认开启"
    info = {}
    parse_log_line(
        "srv init: chat template supports preserving reasoning, "
        "consider enabling it via --reasoning-preserve", info)
    assert info["reasoning_preserve"] == "未开启（可手动开启）"
    info = {}
    parse_log_line(
        "srv init: chat template does NOT support preserving reasoning, --reasoning-preserve has no effect",
        info)
    assert info["reasoning_preserve"] == "不支持"


def test_threadpool_threads():
    info = {}
    parse_log_line("cmn init: llama threadpool init, n_threads = 12", info)
    assert info["n_threads"] == "12"


def test_system_info_total_threads():
    info = {}
    parse_log_line(
        "system_info: n_threads = 12 (n_threads_batch = 12) / 20 | CUDA : ARCHS = 750 | OPENMP = 1 | REPACK = 1",
        info)
    assert info["n_threads"] == "12"
    assert info["n_threads_batch"] == "12"
    assert info["total_threads"] == "20"


def test_verbosity_line():
    info = {}
    parse_log_line("cmn common_param: common_params_print_info: verbosity = 3 (adjust with the `-lv N` CLI arg)", info)
    assert info["log_level"] == 3


def test_moe_experts_stored_only_when_positive():
    info = {}
    parse_log_line("print_info: n_expert              = 128", info)
    parse_log_line("print_info: n_expert_used         = 8", info)
    assert info["n_expert"] == "128"
    assert info["n_expert_used"] == "8"
    info = {}
    parse_log_line("print_info: n_expert              = 0", info)
    parse_log_line("print_info: n_expert_used         = 0", info)
    assert "n_expert" not in info
    assert "n_expert_used" not in info


def test_rope_scaling():
    info = {}
    parse_log_line("print_info: rope scaling          = linear", info)
    assert info["rope_scaling"] == "linear"


def test_quant_type_guessed_stripped():
    info = {}
    parse_log_line("print_info: file type   = (guessed) Q5_K_XL", info)
    assert info["quant_type"] == "Q5_K_XL"


def test_ctx_warning_under_and_over():
    info = {}
    parse_log_line("llama_context: n_ctx_seq (200192) < n_ctx_train (262144) -- the full capacity of the model will not be utilized", info)
    assert info["ctx_size_seq"] == "200,192"
    assert info["train_ctx"] == "262,144"
    info = {}
    parse_log_line("llama_context: n_ctx_seq (300000) > n_ctx_train (262144) -- possible training context overflow", info)
    assert info["ctx_size_seq"] == "300,000"
    assert info["train_ctx"] == "262,144"


def test_parse_skips_oversized_lines():
    """Verbose prompt dumps produce 500KB+ lines: parsing them costs ~0.5 s
    of GUI-thread time each, and model text could corrupt runtime info —
    they are skipped entirely."""
    line = "x" * 506482
    info = {}
    assert parse_log_line(line, info) is False
    assert info == {}
    # an oversized line containing a pattern's text must not match either
    line = ("y" * 2000) + " prompt eval time = 100 ms / 50 tokens (1.00 ms per token, 0.50 tokens per second)"
    info = {}
    assert parse_log_line(line, info) is False
    assert "prompt_speed" not in info


def test_colorize_truncates_oversized_lines():
    from ui.log_parser import colorize_log_line, DISPLAY_LINE_MAX, PARSE_LINE_MAX
    html = colorize_log_line("z" * 5000)
    assert "z" * (DISPLAY_LINE_MAX + 1) not in html
    assert f"{5000}" in html  # truncation marker carries the original length
    assert PARSE_LINE_MAX > DISPLAY_LINE_MAX
    # short lines keep their text, wrapped in a pre span so appendHtml
    # cannot collapse whitespace runs (see colorize_log_line docstring)
    plain = colorize_log_line("plain line")
    assert "plain line" in plain
    assert "white-space: pre" in plain
    # runs of spaces survive the HTML round-trip in the actual editor
    from PyQt6.QtWidgets import QPlainTextEdit
    e = QPlainTextEdit()
    e.appendHtml(colorize_log_line("srv  slot   0 cmd (12 ms)"))
    assert e.toPlainText() == "srv  slot   0 cmd (12 ms)"


def test_slot_timings():
    info = {}
    parse_log_line(
        "slot print_timing: id  0 | task 0 | prompt eval time =   37262.14 ms / 74152 tokens "
        "(    0.50 ms per token,  1990.01 tokens per second)", info)
    parse_log_line(
        "slot print_timing: id  0 | task 0 |        eval time =    2105.08 ms /   196 tokens "
        "(   10.80 ms per token,    92.63 tokens per second)", info)
    assert info["prompt_speed"] == "1990.01 t/s · 74,152 tokens"
    assert info["decode_speed"] == "92.63 t/s · 196 tokens"
    # 实时指标带要**数值原值**（自己排版/上色/定宽列，不从给人看的字符串反解）；
    # 这两个键就是带子上“上一段连续活动的平均值”的全仓唯一数据源
    assert info["prompt_tps_last"] == 1990.01
    assert info["prompt_tokens_last"] == 74152
    assert info["decode_tps_last"] == 92.63
    assert info["decode_tokens_last"] == 196


# ---------------------------------------------------------------------------
# runtime info display
# ---------------------------------------------------------------------------

def test_slot_timings_in_flight_lines():
    """阶段**运行中**的两行 print_timing（与上面那对结束行同前缀，函数名被
    SLT_INF 的 `%12.*s` 截成 `print_timing`）也写 `*_tps_last`。

    样本直接取自真实运行落盘的 `~/.llama-cpp-launcher/logs/last_run.log`。没有它们，
    第一个任务的 decode 阶段就没有 prefill 均值可用（`print_timings()` 只在任务结束
    分支里调）—— 就是“第一次 decode 时 Prefill 显示 -”的根因。
    同时钉住：这两行**不改**给人看的 `prompt_speed` / `decode_speed`（运行信息页的
    「最近任务」是已完成任务的总结）。
    """
    info = {}
    parse_log_line(
        "0.22.925.546 I slot print_timing: id  0 | task 10 | prompt processing, "
        "n_tokens =  25814, progress = 1.00, t =   9.09 s / 2838.98 tokens per second", info)
    assert info["prompt_tps_last"] == 2838.98
    assert info["prompt_tokens_last"] == 25814
    assert "prompt_speed" not in info
    parse_log_line(
        "0.26.103.860 I slot print_timing: id  0 | task 10 | n_gen =    310,"
        " tg = 102.37 t/s, tg_3s = 102.70 t/s", info)
    # 取 tg（本段累计均值），不取 tg_3s（最近 3s 窗口）
    assert info["decode_tps_last"] == 102.37
    assert info["decode_tokens_last"] == 310
    assert "decode_speed" not in info
    # 任务结束的那对精确值覆盖阶段内的累计值
    parse_log_line(
        "2.43.428.294 I slot print_timing: id  0 | task 10 | prompt eval time ="
        "    9333.32 ms / 25825 tokens (    0.36 ms per token,  2766.97 tokens per second)",
        info)
    assert info["prompt_tps_last"] == 2766.97
    assert info["prompt_speed"] == "2766.97 t/s · 25,825 tokens"


def test_slot_timings_in_flight_lines_tolerate_garbage():
    """inf / 缺字段（旧版 llama.cpp 无这两行，或 %8.2f 溢出成 inf）→ 不写键、不报错。"""
    for line in (
            "slot print_timing: id  0 | task 10 | prompt processing, n_tokens = 10,"
            " progress = 0.01, t =   3.00 s /      inf tokens per second",
            "slot print_timing: id  0 | task 10 | n_gen = 120, tg =    inf t/s,"
            " tg_3s =   12.00 t/s",
            "slot print_timing: id  0 | task 10 | prompt processing, n_tokens = 10,"
            " progress = 0.01"):
        info = {}
        parse_log_line(line, info)
        assert "prompt_tps_last" not in info
        assert "decode_tps_last" not in info


def test_info_shows_new_rows():
    info = {
        "n_expert": "128", "n_expert_used": "8",
        "rope_scaling": "linear",
        "reasoning_preserve": "默认开启",
        "model_vram": "26704.69 MiB",
        "model_vram_detail": "CUDA0: 18904.69 + CUDA1: 7800.00",
        "prompt_speed": "1990.01 t/s · 74,152 tokens",
        "decode_speed": "92.63 t/s · 196 tokens",
    }
    html = build_info_html(info)
    assert "MoE 专家" in html
    assert "128 / 8" in html
    assert "RoPE 缩放" in html
    assert "linear" in html
    assert "推理保留" in html
    assert "默认开启" in html
    assert "26704.69 MiB" in html
    assert "CUDA0: 18904.69" in html
    assert "提示词处理速度" in html
    assert "生成速度" in html
    assert "1990.01 t/s" in html


def test_info_new_rows_omitted_when_empty():
    html = build_info_html({"model_params": "1.2 B"})
    for label in ("MoE 专家", "RoPE 缩放", "推理保留", "提示词处理速度", "生成速度"):
        assert label not in html


def test_info_low_verbosity_hint():
    html = build_info_html({"log_level": 3, "status": "✅ 服务就绪"})
    assert "日志详细度较低" in html
    assert "4 (trace)" in html
    # at trace level there is no hint
    html = build_info_html({"log_level": 4})
    assert "日志详细度较低" not in html
    # unknown verbosity (older builds / not parsed) -> no hint
    html = build_info_html({"status": "✅ 服务就绪"})
    assert "日志详细度较低" not in html


# ---------------------------------------------------------------------------
# schema default + CLI emission
# ---------------------------------------------------------------------------

def test_schema_default_is_trace():
    p = PARAMS_BY_KEY["log_verbosity"]
    assert p.default == 4
    assert p.curidx == 4


# The live-parsed --help default for log_verbosity is 3 (the binary's own
# default); the launcher's schema default is 4, so an untouched panel emits
# --log-verbosity 4 against the live baseline.
LIVE_DEFAULTS = {"log_verbosity": 3}


def _cmd(v):
    return CommandBuilder(LIVE_DEFAULTS).build(v)


def test_log_verbosity_emitted_by_default():
    args = _cmd({"log_verbosity": 4})
    assert "--log-verbosity" in args
    assert args[args.index("--log-verbosity") + 1] == "4"


def test_log_verbosity_lowered_to_binary_default_is_omitted():
    # matches the binary's own default -> no flag needed
    args = _cmd({"log_verbosity": 3})
    assert "--log-verbosity" not in args


def test_log_verbosity_raised_to_debug_is_emitted():
    args = _cmd({"log_verbosity": 5})
    assert args[args.index("--log-verbosity") + 1] == "5"


def test_verbose_suppresses_log_verbosity():
    args = _cmd({"verbose": True, "log_verbosity": 4})
    assert "--verbose" in args
    assert "--log-verbosity" not in args
