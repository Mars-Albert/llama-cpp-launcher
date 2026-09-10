"""Pure log line parsing and coloring for llama-server output (no Qt dependency).

Extracted from ui/main_window.py (optimization-plan C2): level-based HTML
coloring and the pre-compiled pattern table that feeds runtime info.

Verbosity note (llama.cpp >= #23021, commit 67b2b7f2f "logs: reduce"): the
library INFO lines (model load, VRAM, context, ggml backends) are emitted
through a log callback that maps INFO -> TRACE, so at the binary's default
-lv 3 (info) they are suppressed entirely. The launcher therefore defaults
log_verbosity to 4 (trace) — see core/params_schema.py — which shows every
line below except debug (level 5). Patterns for level-3-only lines (srv/cmn
INFO, warnings, slot timings) are kept so the panel still fills in when the
user lowers the level, and ui/runtime_info.py shows a hint when the parsed
`verbosity = N` line reports N < 4.
"""
import html as html_mod
import os
import re

from core.i18n import t


# Log level colors for colored output, mirroring llama.cpp's terminal
# color roles (common/log.cpp print(): D=yellow, I=green, W=magenta,
# E=red). The log area is always dark, so each ANSI role is rendered with
# the matching Catppuccin Mocha shade.
_LOG_LEVEL_COLORS = {
    'D': '#f9e2af',   # Debug - yellow (ANSI 33)
    'I': '#a6e3a1',   # Info - green (ANSI 32)
    'W': '#cba6f7',   # Warning - magenta (ANSI 35, mauve in Mocha)
    'E': '#f38ba8',   # Error - red (ANSI 31)
    'F': '#f38ba8',   # Fatal - red (defensive; llama.cpp never emits F)
}
_LOG_LEVEL_RE = re.compile(r'^[\d.]+\s+([DIWEF])\s')

# Length guards. Verbose/debug verbosity makes llama.cpp dump the raw
# prompt/completion text to stdout — in real runs single lines over
# 500 KB appeared. Running the ~73-pattern table against such lines costs
# ~0.5 s of GUI-thread time each, and letting them into the log view made
# one giant unbounded block (see the per-line block rendering in
# ui/main_window._flush_log_buffer). Runtime facts only ever appear on
# short structured lines, so:
#   - lines > PARSE_LINE_MAX are skipped for runtime-info parsing (model
#     text matching a check string would corrupt the info anyway);
#   - the log view shows at most DISPLAY_LINE_MAX chars per line.
PARSE_LINE_MAX = 2048
DISPLAY_LINE_MAX = 1024


def colorize_log_line(line, max_len=DISPLAY_LINE_MAX):
    """Convert a log line to HTML with color based on log level.

    Lines longer than max_len are truncated for display (the full line is
    still kept in the run-log file); a marker notes the original length.
    Every line is wrapped in a white-space:pre span: appendHtml applies HTML
    whitespace rules, which collapse the runs of spaces llama.cpp uses for
    column alignment ("srv  slot   0 …") into single spaces — pre keeps the
    alignment visible (and in search / exported view text).
    """
    if len(line) > max_len:
        escaped = html_mod.escape(line[:max_len])
        escaped += t("… 已截断（共 {n} 字符）", n=len(line))
    else:
        escaped = html_mod.escape(line)
    m = _LOG_LEVEL_RE.match(line)
    if m:
        level = m.group(1)
        color = _LOG_LEVEL_COLORS.get(level, '#cdd6f4')
        return f'<span style="color: {color}; white-space: pre;">{escaped}</span>'
    return f'<span style="white-space: pre;">{escaped}</span>'


def line_level(line):
    """Return the level char ('D'/'I'/'W'/'E'/'F') of a log line, or None.

    Used by the E3 level filter in the main window; lines without a
    level prefix are shown only in the unfiltered view (see
    ui/main_window._log_level_visible).
    """
    m = _LOG_LEVEL_RE.match(line)
    return m.group(1) if m else None




def compile_log_patterns():
    """Pre-compile all log parsing patterns for efficient per-line matching."""
    _re = lambda pat: re.compile(pat, re.IGNORECASE)
    patterns = []

    def _add(checks, regex, handler, exclude=None):
        patterns.append((
            tuple(checks) if isinstance(checks, (list, tuple)) else (checks,),
            tuple(exclude) if exclude else (),
            _re(regex) if isinstance(regex, str) else regex,
            handler,
        ))

    def _simple(checks, regex, key, transform, exclude=None):
        def handler(info, m):
            info[key] = transform(m)
            return True
        _add(checks, regex, handler, exclude)

    def _kv(checks, regex, key, exclude=None):
        _simple(checks, regex, key, lambda m: m.group(1).strip(), exclude)

    def _int_comma(checks, regex, key, exclude=None):
        _simple(checks, regex, key, lambda m: f"{int(m.group(1)):,}", exclude)

    def _first(checks, regex, key, transform, exclude=None):
        """Like _simple, but only the FIRST matching line wins (later repeats
        of the same value in draft/speculative contexts are ignored)."""
        def handler(info, m):
            if key in info:
                return False
            info[key] = transform(m)
            return True
        _add(checks, regex, handler, exclude)

    # ========== NEW FORMAT (v9174+) ==========

    # --- GPU info (new: `- CUDA0 : NVIDIA GeForce RTX 5090 (32606 MiB, 30991 MiB free)`) ---
    def _handle_gpu_new(info, m):
        idx = m.group(1)
        name = m.group(2).strip()
        total = m.group(3).strip()
        free = m.group(4).strip()
        info[f"gpu{idx}_name"] = name
        info[f"gpu{idx}_vram"] = f"{total} MiB"
        info[f"gpu{idx}_free"] = f"{free} MiB"
        if "gpu_name" not in info:
            info["gpu_name"] = name
            info["gpu_vram"] = f"{total} MiB"
            info["free_vram"] = f"{free} MiB"
        return True
    _add("cuda", r"-\s+CUDA(\d+)\s+:\s+(.+?)\s+\(([\d,]+)\s*MiB,\s*([\d,]+)\s*MiB\s+free\)", _handle_gpu_new)

    def _handle_cpu_new(info, m):
        info["cpu_name"] = m.group(1).strip()
        info["cpu_ram"] = f"{m.group(2).strip()} MiB"
        return True
    _add("- cpu", r"-\s+CPU\s+:\s+(.+?)\s+\(([\d,]+)\s*MiB", _handle_cpu_new)

    # --- Threads (new: `srv init: using 19 threads for HTTP server`) ---
    def _handle_threads_http(info, m):
        info["threads_http"] = m.group(1)
        return True
    _add(["srv", "using", "threads for http"], r"using\s+(\d+)\s+threads\s+for\s+HTTP", _handle_threads_http)

    # --- Slots (new: `srv load_model: initializing, n_slots = 1` / old: `initializing slots`) ---
    _int_comma(["srv", "initializing"], r"n_slots\s*=\s*(\d+)", "n_slots")

    # --- Slot context (old: `slot load_model: id  0 | task -1 | new slot, n_ctx = 65536`) ---
    def _handle_slot_ctx(info, m):
        info["ctx_size"] = f"{int(m.group(1)):,}"
        info["n_slots"] = info.get("n_slots", "1")
        return True
    _add(["slot", "new slot"], r"n_ctx\s*=\s*(\d+)", _handle_slot_ctx)

    # --- Slot context new format (new: `srv load_model: initializing, n_ctx_slot = 131072`) ---
    _int_comma(["srv", "initializing", "n_ctx_slot"], r"n_ctx_slot\s*=\s*(\d+)", "ctx_size")

    # --- Context warning (`llama_context: n_ctx_seq (65536) < n_ctx_train (262144)`,
    #     or the `>` overflow variant; library INFO → visible at -lv 4) ---
    def _handle_ctx_warning(info, m):
        info["ctx_size_seq"] = f"{int(m.group(1)):,}"
        info["train_ctx"] = f"{int(m.group(2)):,}"
        return True
    _add(["llama_context", "n_ctx_seq", "n_ctx_train"], r"n_ctx_seq\s*\((\d+)\)\s*[<>]\s*n_ctx_train\s*\((\d+)\)", _handle_ctx_warning)

    # --- Prompt cache (TRACE → visible at -lv 4) ---
    # `srv load_model: prompt cache is enabled, size limit: no limit`
    # `srv load_model: prompt cache is enabled, size limit: 2048 MiB`
    # `srv load_model: prompt cache is disabled - use `--cache-ram N` to enable it`
    def _handle_prompt_cache(info, m):
        if m.group(1) is None:
            info["prompt_cache"] = t("已启用")
        elif m.group(1) == "no limit":
            info["prompt_cache"] = t("已启用（无上限）")
        else:
            info["prompt_cache"] = t("已启用（上限 {n} MiB）", n=m.group(2))
        return True
    _add("prompt cache is enabled", r"prompt cache is enabled(?:,\s*size limit:\s*(no limit|([\d,]+) MiB))?", _handle_prompt_cache)
    _simple(["prompt cache is disabled"], r"prompt cache is disabled", "prompt_cache", lambda m: t("已禁用"))

    # --- Speculative decoding (INFO, always on) ---
    # `spec common_specu: adding speculative implementation 'draft-mtp'`
    # `common_speculative_init_result: creating MTP draft context against the target model '...gguf'`
    _simple(["adding speculative implementation"], r"adding speculative implementation '([^']+)'", "speculative_decoding", lambda m: m.group(1))
    _simple(["creating mtp draft context"], r"creating mtp draft context", "speculative_decoding", lambda m: "MTP")
    # legacy: `srv load_model: speculative decoding will use checkpoints`
    _simple(["srv", "speculative decoding"], r"speculative decoding", "speculative_decoding",
            lambda m: "已启用")

    # --- Reasoning preservation (chat-template capability; INFO/WARN, always on) ---
    # `srv init: chat template supports preserving reasoning, it is enabled by default (...)`
    # `srv init: chat template supports preserving reasoning, consider enabling it via --reasoning-preserve`
    # `srv init: chat template does NOT support preserving reasoning, --reasoning-preserve has no effect`
    _simple(["chat template supports preserving reasoning", "enabled by default"],
            r"enabled by default", "reasoning_preserve", lambda m: t("默认开启"))
    _simple(["chat template supports preserving reasoning", "consider enabling"],
            r"consider enabling", "reasoning_preserve", lambda m: t("未开启（可手动开启）"))
    _simple(["does not support preserving reasoning"], r"does NOT support", "reasoning_preserve", lambda m: t("不支持"))

    # --- CPU threadpool (INFO, always on) ---
    # `cmn init: llama threadpool init, n_threads = 12`
    _kv(["llama threadpool init"], r"n_threads\s*=\s*(\d+)", "n_threads")

    # --- Effective log verbosity (INFO, always on; drives the low-detail hint) ---
    # `cmn common_param: common_params_print_info: verbosity = 3 (adjust with the `-lv N` CLI arg)`
    _simple(["verbosity = "], r"verbosity = (\d+)", "log_level", lambda m: int(m.group(1)))

    # --- Per-task timings (slot INFO, always on) ---
    # `slot print_timing: id  0 | task 0 | prompt eval time = 37262.14 ms / 74152 tokens (0.50 ms per token, 1990.01 tokens per second)`
    def _handle_prompt_speed(info, m):
        info["prompt_speed"] = f"{m.group(2)} t/s · {int(m.group(1)):,} tokens"
        return True
    _add(["prompt eval time"], r"prompt eval time =\s+[\d.]+ ms /\s*(\d+) tokens \(\s*[\d.]+ ms per token,\s*([\d.]+) tokens per second\)", _handle_prompt_speed)

    # `slot print_timing: id  0 | task 0 | eval time = 2105.08 ms / 196 tokens (10.80 ms per token, 92.63 tokens per second)`
    def _handle_decode_speed(info, m):
        info["decode_speed"] = f"{m.group(2)} t/s · {int(m.group(1)):,} tokens"
        return True
    _add(["eval time"], r"\beval time =\s+[\d.]+ ms /\s*(\d+) tokens \(\s*[\d.]+ ms per token,\s*([\d.]+) tokens per second\)", _handle_decode_speed, exclude=["prompt"])

    # --- Model loaded (new: `srv main: model loaded`) ---
    def _handle_model_loaded_new(info, m):
        info["status"] = "🔄 模型加载完成"
        return True
    _add(["srv", "model loaded"], r"model loaded", _handle_model_loaded_new)

    # --- Thinking mode (new: chat template with <think> tag) ---
    def _handle_thinking_new(info, m):
        info["thinking_mode"] = "已启用"
        return True
    _add(["chat template", "<think>"], r"<think>", _handle_thinking_new)

    # --- KV unified warning (new: `srv init: --cache-idle-slots requires --kv-unified, disabling`) ---
    def _handle_kv_unified_hint(info, m):
        info["kv_unified"] = "需要 --kv-unified，已禁用"
        return True
    _add(["srv", "kv-unified", "disabling"], r"requires.*kv-unified.*disabling", _handle_kv_unified_hint)

    # --- Load hparams warnings (new: `load_hparams: Qwen-VL models require ...`) ---
    _kv(["load_hparams", "image", "tokens"], r"require.*?(\d+)\s*image\s*tokens", "vision_min_tokens")

    # ========== GPU DEVICE LINES ==========

    # --- ggml backend init (library INFO → visible at -lv 4; also matches the
    #     legacy llama_print_system_info line) ---
    # `  Device 0: NVIDIA GeForce RTX 5090, compute capability 9.0, VMM: yes, VRAM: 32579 MiB`
    # `  Device 0: AMD Radeon RX 7900 XTX, gfx906 (0x00000906), VMM: no, Wave Size: 32, VRAM: 24576 MiB`
    # legacy: `Device 0: NVIDIA GeForce RTX 4090, compute capability 8.9, VRAM: 24564 MiB`
    def _handle_gpu_device(info, m):
        # VRAM is always the LAST capture group (the optional named `cc`
        # group shifts the numbering between the three device patterns)
        idx = m.group(1)
        name = m.group(2).strip()
        vram = m.group(m.re.groups).strip()
        if not info.get(f"gpu{idx}_name"):
            info[f"gpu{idx}_name"] = name
        if not info.get(f"gpu{idx}_vram"):
            info[f"gpu{idx}_vram"] = f"{vram} MiB"
        cc = m.groupdict().get("cc")
        if cc and "gpu_compute_cap" not in info:
            info["gpu_compute_cap"] = cc
        if "gpu_name" not in info:
            info["gpu_name"] = name
            info["gpu_vram"] = f"{vram} MiB"
        return True
    _add("vram", r"Device (\d+): (.+?), compute capability (?P<cc>[\d.]+), VMM: \w+, VRAM: ([\d,]+) MiB", _handle_gpu_device)
    _add("vram", r"Device (\d+): (.+?), \S+ \(0x[0-9a-fA-F]+\), VMM: \w+, Wave Size: \d+, VRAM: ([\d,]+) MiB", _handle_gpu_device)
    _add("vram", r"Device (\d+): (.+?), compute capability (?P<cc>[\d.]+), VRAM: ([\d,]+) MiB", _handle_gpu_device)

    # --- System info (old: `system_info: n_threads = 12 (n_threads_batch = 12) / 20`) ---
    _kv("system_info:", r"n_threads\s*=\s*(\d+)", "n_threads")
    _kv("system_info:", r"n_threads_batch\s*=\s*(\d+)", "n_threads_batch")
    _kv("system_info:", r"total_threads\s*=\s*(\d+)", "total_threads")
    _kv("system_info:", r"n_threads_batch\s*=\s*\d+\)\s*/\s*(\d+)", "total_threads")

    # --- Projected VRAM (old) ---
    def _handle_projected(info, m):
        info["projected_vram"] = f"{m.group(1).strip()} MiB"
        info["free_vram"] = f"{m.group(2).strip()} MiB"
        return True
    _add(["projected to use", "device memory"], r"use ([\d,]+)\s*MiB.*?vs\.\s*([\d,]+)\s*MiB", _handle_projected)

    # --- Model loading (old) ---
    def _handle_model_file_old(info, m):
        info["model_file"] = os.path.basename(m.group(1))
        return True
    _add(["loading model", ".gguf"], r"'([^']+\.gguf)'", _handle_model_file_old, exclude=["multimodal"])

    # Also match new format: `srv main: loading model` + path in args
    def _handle_loading_model_new(info, m):
        info["model_file"] = os.path.basename(m.group(1))
        return True
    _add(["srv", "loading model", ".gguf"], r"([\w/\\:. -]+\.gguf)", _handle_loading_model_new)

    # --- GGUF / model info (old: print_info format / new: llama_model_loader format) ---
    _simple("file format", r"GGUF V(\d+)", "gguf_version", lambda m: f"V{m.group(1)}")
    _simple("version gguf", r"GGUF\s+V(\d+)", "gguf_version", lambda m: f"V{m.group(1)}")
    _simple(["file type", "print_info"], r"file type\s*=\s*(.+)", "quant_type",
            lambda m: m.group(1).replace("(guessed) ", "").strip())
    _kv(["file size", "print_info"], r"file size\s*=\s*(.+)", "file_size")
    _kv(["model params", "print_info"], r"model params\s*=\s*(.+)", "model_params")
    _kv("general.name", r"general\.name\s+(?:str\s+)?=\s+(.+)", "model_name")
    _simple(["arch", "print_info"], r"arch\s+=\s+(\w+)", "arch", lambda m: m.group(1))
    _int_comma(["n_vocab", "print_info"], r"n_vocab\s+=\s+(\d+)", "vocab_size")
    _int_comma(["n_ctx_train", "print_info"], r"n_ctx_train\s+=\s+(\d+)", "train_ctx")
    _int_comma(["n_embd", "print_info"], r"n_embd\s+=\s+(\d+)", "embed_dim",
               exclude=["n_embd_head", "n_embd_k_gqa", "n_embd_v_gqa", "n_embd_inp"])
    _kv(["n_layer", "print_info"], r"n_layer\s+=\s+(\d+)", "n_layers")
    _int_comma(["n_ff", "print_info"], r"n_ff\s+=\s+(\d+)", "n_ff")
    _int_comma(["n_swa", "print_info"], r"n_swa\s+=\s+(\d+)", "sliding_window")

    # --- MoE experts (print_info; only stored for expert models) ---
    def _handle_n_expert(info, m):
        if int(m.group(1)) > 0:
            info["n_expert"] = m.group(1)
            return True
        return False
    _add(["n_expert", "print_info"], r"\bn_expert\s+=\s+(\d+)", _handle_n_expert)

    def _handle_n_expert_used(info, m):
        if info.get("n_expert"):
            info["n_expert_used"] = m.group(1)
            return True
        return False
    _add(["n_expert_used", "print_info"], r"n_expert_used\s+=\s+(\d+)", _handle_n_expert_used)

    # --- RoPE scaling (print_info) ---
    _kv(["rope scaling", "print_info"], r"rope scaling\s+=\s+(\S+)", "rope_scaling")
    _simple(["vocab type", "print_info"], r"vocab type\s+=\s+(\w+)", "vocab_type", lambda m: m.group(1))
    _simple(["bos token", "print_info"], r"BOS token\s+=\s+(\d+)\s+'([^']*)'",
            "bos_token", lambda m: f"{m.group(1)} '{m.group(2)}'")
    _simple(["eos token", "print_info"], r"EOS token\s+=\s+(\d+)\s+'([^']*)'",
            "eos_token", lambda m: f"{m.group(1)} '{m.group(2)}'")
    _kv(["freq_base_train", "print_info"], r"freq_base_train\s+=\s+([\d.]+)", "freq_base")

    # --- Context (old) ---
    _int_comma(["n_batch", "llama_context"], r"n_batch\s+=\s+(\d+)", "n_batch")
    _int_comma(["n_ubatch", "llama_context"], r"n_ubatch\s+=\s+(\d+)", "n_ubatch")
    _kv(["freq_base", "llama_context"], r"freq_base\s+=\s+([\d.]+)", "freq_base_runtime")
    _int_comma(["n_ctx_seq", "llama_context"], r"n_ctx_seq\s+=\s+(\d+)", "ctx_size_seq")
    _int_comma(["n_seq_max", "llama_context"], r"n_seq_max\s+=\s+(\d+)", "n_slots")

    # --- Tensors / offload (old) ---
    def _handle_tensor_types(info, m):
        info.setdefault("tensor_types", {})[m.group(1)] = int(m.group(2))
        return True
    _add(["llama_model_loader", "- type", "tensors"], r"- type\s+(\w+):\s+(\d+)\s+tensors", _handle_tensor_types)

    def _handle_gpu_offload(info, m):
        info["gpu_offload"] = f"{m.group(1)}/{m.group(2)} " + t("层")
        return True
    # E8: the prefix changed across versions (`load_tensors:` legacy, `load_all_data:`
    # in newer builds), so the pre-filter only checks the stable wording
    _add(["offloaded", "layers"], r"offloaded (\d+)/(\d+) layers", _handle_gpu_offload)

    # --- In-use device line (library INFO → visible at -lv 4) ---
    # `llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090) (0000:01:00.0) - 30991 MiB free`
    # `main: using device CPU (12th Gen Intel(R) Core(TM) i7-12700K) (unknown id) - 53243 MiB free`
    def _handle_using_device(info, m):
        backend = m.group(1)
        idx = m.group(2) or "0"
        name = m.group(3).strip()
        free = m.group(4).strip()
        if backend.lower() == "cpu":
            info.setdefault("cpu_name", name)
        else:
            if not info.get(f"gpu{idx}_name"):
                info[f"gpu{idx}_name"] = name
            if not info.get(f"gpu{idx}_free"):
                info[f"gpu{idx}_free"] = f"{free} MiB"
            if "gpu_name" not in info:
                info["gpu_name"] = name
            if "free_vram" not in info:
                info["free_vram"] = f"{free} MiB"
        return True
    _add("using device", r"using device ([A-Za-z]+)(\d*)\s+\((.+?)\) \([^()]*\)\s+-\s+([\d,]+) MiB free", _handle_using_device)

    # --- Per-backend buffers (library INFO → visible at -lv 4) ---
    # `load_tensors:        CUDA0 model buffer size = 18904.69 MiB`
    # `load_tensors:   CPU_Mapped model buffer size =   994.63 MiB`
    # `llama_kv_cache:      CUDA0 KV buffer size =  9579.50 MiB`
    # `sched_reserve:       CUDA0 compute buffer size =  36.14 MiB`
    def _handle_model_buffer(info, m):
        bufs = info.setdefault("model_bufs", {})
        bufs[m.group(1)] = bufs.get(m.group(1), 0) + float(m.group(2))
        gpu = {k: v for k, v in bufs.items() if not k.startswith("CPU")}
        cpu = {k: v for k, v in bufs.items() if k.startswith("CPU")}
        if gpu:
            info["model_vram"] = f"{sum(gpu.values()):.2f} MiB"
            if len(gpu) > 1:
                info["model_vram_detail"] = " + ".join(f"{k}: {v:.2f}" for k, v in sorted(gpu.items()))
        if cpu:
            info["cpu_buffer"] = f"{sum(cpu.values()):.2f} MiB"
        return True
    _add("model buffer size", r"([A-Za-z_]\w*)\s+model buffer size\s+=\s+([\d.]+)\s*MiB", _handle_model_buffer)

    def _handle_kv_buffer(info, m):
        # full + SWA/DSA caches each print a line; the total is the sum
        info["kv_cache_total"] = info.get("kv_cache_total", 0.0) + float(m.group(2))
        return True
    _add("kv buffer size", r"([A-Za-z_]\w*)\s+KV buffer size\s+=\s+([\d.]+)\s*MiB", _handle_kv_buffer)

    def _handle_compute_buffer(info, m):
        bufs = info.setdefault("compute_bufs", {})
        bufs[m.group(1)] = bufs.get(m.group(1), 0) + float(m.group(2))
        gpu = {k: v for k, v in bufs.items() if not k.startswith("CPU")}
        if gpu:
            info["compute_buffer"] = f"{sum(gpu.values()):.2f} MiB"
        return True
    _add("compute buffer size", r"([A-Za-z_]\w*)\s+compute buffer size\s+=\s+([\d.]+)\s*MiB", _handle_compute_buffer)

    # --- Graph (first sched_reserve wins: the main context reserves before
    #     draft/speculative contexts, so last-wins would show the draft's) ---
    _first(["graph nodes", "sched_reserve"], r"graph nodes\s+=\s+(\d+)", "graph_nodes", lambda m: m.group(1))
    _first(["graph splits", "sched_reserve"], r"graph splits\s+=\s+(\d+)", "graph_splits", lambda m: m.group(1))
    # `reserve_compute_meta: graph splits = 1, nodes = 823` (compute-meta graph)
    _first(["reserve_compute_meta"], r"nodes\s*=\s*(\d+)", "graph_nodes", lambda m: m.group(1))

    # --- n_ctx (old) ---
    _int_comma(["n_ctx", "llama_context"], r"n_ctx\s+=\s+(\d+)", "ctx_size",
               exclude=["n_ctx_seq", "n_ctx_orig", "n_ctx_train"])

    # --- Vision (old) ---
    def _handle_mmproj(info, m):
        info["mmproj_file"] = os.path.basename(m.group(1))
        return True
    _add("loaded multimodal model", r"'([^']+\.gguf)'", _handle_mmproj)
    _kv(["model size:", "mib", "load_hparams:"], r"model size:\s+([\d.]+)\s*MiB", "vision_model_size")
    _kv(["image_size:", "load_hparams:"], r"image_size:\s+(\d+)", "vision_image_size")

    # --- Thinking (old) ---
    def _handle_thinking_old(info, m):
        info["thinking_mode"] = "已启用" if m.group(1) == "1" else "已禁用"
        return True
    _add(["thinking", "chat template"], r"thinking\s*=\s*(\d+)", _handle_thinking_old)

    # --- Address (old: `server is listening on` / new: `srv llama_server: listening on`) ---
    def _handle_address(info, m):
        info["address"] = m.group(1)
        return True
    _add("server is listening on", r"http://([\d.]+:\d+)", _handle_address)
    _add(["srv", "listening on"], r"http://([\d.]+:\d+)", _handle_address)

    return tuple(patterns)


# Pre-compiled at module level
LOG_PATTERNS = compile_log_patterns()

# Fast rejection set for parse_log_line: a line can match a pattern only if
# it contains that pattern's primary check string, so any line missing ALL
# primary checks can be skipped before the per-pattern loop. This is the
# hot path during verbose prompt-dump bursts (tens of thousands of
# arbitrary-text lines per second on the GUI thread).
_PARSE_ANCHORS = tuple(checks[0] for checks, _, _, _ in LOG_PATTERNS)


def parse_log_line(line, info):
    """Parse one log line, mutating `info`. Returns True if anything changed."""
    if len(line) > PARSE_LINE_MAX:
        return False
    stripped = line.strip()
    lower = stripped.lower()
    if not any(anchor in lower for anchor in _PARSE_ANCHORS):
        return False
    updated = False

    # Pre-compiled pattern matching
    for checks, exclude, regex, handler in LOG_PATTERNS:
        if all(c in lower for c in checks) and not any(e in lower for e in exclude):
            m = regex.search(stripped)
            if m and handler(info, m):
                updated = True

    # Special-case handlers (store raw Chinese keys, translate in _update_info_display)
    if "system_info:" in lower or "system info:" in lower:
        updated = True
        if "openmp" in lower:
            info["openmp"] = "是"
        if "repack" in lower:
            info["repack"] = "是"

    if "kv_unified" in lower and ("llama_context" in lower or "srv" in lower):
        updated = True
        if "true" in lower:
            info["kv_unified"] = "已启用（多槽位共享缓存）"
        elif "false" in lower:
            info["kv_unified"] = "已禁用（各槽位独立缓存）"

    if "flash_attn" in lower and "llama_context" in lower:
        updated = True
        if "enabled" in lower:
            info["flash_attn"] = "已启用"
        elif "disabled" in lower:
            info["flash_attn"] = "已禁用"
        elif "auto" in lower:
            info["flash_attn"] = "自动（根据后端支持）"

    if "flash attention is enabled" in lower:
        info["flash_attn"] = "已启用"
        updated = True

    if "has vision encoder" in lower:
        info["has_vision"] = True
        updated = True

    if "server is listening on" in lower or ("listening on" in lower and "srv" in lower):
        info["status"] = "✅ 服务就绪"
        updated = True

    if "model loaded" in lower and ("main:" in lower or "llama_server:" in lower):
        info["status"] = "🔄 模型加载完成"
        updated = True

    return updated


