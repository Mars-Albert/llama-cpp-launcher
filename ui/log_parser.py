"""Pure log line parsing and coloring for llama-server output (no Qt dependency).

Extracted from ui/main_window.py (optimization-plan C2): level-based HTML
coloring and the pre-compiled pattern table that feeds runtime info.
"""
import html as html_mod
import os
import re

from core.i18n import t


# Log level colors for colored output (matching llama.cpp terminal colors)
_LOG_LEVEL_COLORS = {
    'D': '#6c7086',   # Debug - gray (subtle)
    'I': '#cdd6f4',   # Info - default light
    'W': '#f9e2af',   # Warning - yellow
    'E': '#f38ba8',   # Error - red
    'F': '#f38ba8',   # Fatal - red
}
_LOG_LEVEL_RE = re.compile(r'^[\d.]+\s+([DIWEF])\s')


def colorize_log_line(line):
    """Convert a log line to HTML with color based on log level."""
    escaped = html_mod.escape(line)
    m = _LOG_LEVEL_RE.match(line)
    if m:
        level = m.group(1)
        color = _LOG_LEVEL_COLORS.get(level, '#cdd6f4')
        return f'<span style="color: {color};">{escaped}</span>'
    return escaped


def line_level(line):
    """Return the level char ('D'/'I'/'W'/'E'/'F') of a log line, or None.

    Used by the E3 level filter in the main window; lines without a
    level prefix (banners, command echoes) always stay visible.
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

    # --- Context warning (new: `llama_context: n_ctx_seq (65536) < n_ctx_train (262144)`) ---
    def _handle_ctx_warning(info, m):
        info["ctx_size_seq"] = f"{int(m.group(1)):,}"
        info["train_ctx"] = f"{int(m.group(2)):,}"
        return True
    _add(["llama_context", "n_ctx_seq", "n_ctx_train"], r"n_ctx_seq\s*\((\d+)\)\s*<\s*n_ctx_train\s*\((\d+)\)", _handle_ctx_warning)

    # --- Prompt cache (new: `srv load_model: use '--cache-ram 0' to disable the prompt cache`) ---
    def _handle_cache_hint(info, m):
        if "prompt_cache" not in info:
            info["prompt_cache"] = "已启用"
        return True
    _add(["srv", "prompt cache"], r"disable the prompt cache", _handle_cache_hint)

    # --- Speculative decoding (new: `srv load_model: speculative decoding will use checkpoints`) ---
    _simple(["srv", "speculative decoding"], r"speculative decoding", "speculative_decoding",
            lambda m: "已启用")

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

    # ========== OLD FORMAT (legacy) ==========

    # --- GPU info (old: `Device 0: NVIDIA GeForce RTX 4090, compute capability 8.9, VRAM: 24564 MiB`) ---
    def _handle_device_old(info, m):
        info["gpu_name"] = m.group(1).strip()
        info["gpu_vram"] = f"{m.group(2).strip()} MiB"
        return True
    _add("device 0:", r"Device \d+: (.+?),.*?VRAM:\s*([\d,]+)\s*MiB", _handle_device_old)

    def _handle_compute_cap(info, m):
        info["gpu_compute_cap"] = m.group(1)
        return True
    _add("device 0:", r"compute capability\s+([\d.]+)", _handle_compute_cap)

    # --- System info (old) ---
    _kv("system_info:", r"n_threads\s*=\s*(\d+)", "n_threads")
    _kv("system_info:", r"n_threads_batch\s*=\s*(\d+)", "n_threads_batch")
    _kv("system_info:", r"total_threads\s*=\s*(\d+)", "total_threads")

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
    _kv(["file type", "print_info"], r"file type\s*=\s*(.+)", "quant_type")
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

    # --- E8: in-use device line (new: `main: using device CUDA0 (NVIDIA GeForce RTX 5090) (CUDA0) - 30819 MiB free`) ---
    def _handle_using_device(info, m):
        idx = m.group(1)
        name = m.group(2).strip()
        if not info.get(f"gpu{idx}_name"):
            info[f"gpu{idx}_name"] = name
        if "gpu_name" not in info:
            info["gpu_name"] = name
        return True
    _add("using device", r"using device CUDA(\d+) \((.+?)\) \(", _handle_using_device)

    # --- VRAM buffers (old) ---
    _kv(["model buffer size", "cuda"], r"CUDA\d+\s+model buffer size\s+=\s+(.+)", "model_vram")
    _kv("cpu_mapped model buffer size", r"CPU_Mapped model buffer size\s+=\s+(.+)", "cpu_buffer")

    def _handle_kv_buffer(info, m):
        prev_total = info.get("kv_cache_total", 0.0)
        if isinstance(prev_total, str):
            pm = re.search(r"([\d.]+)", prev_total)
            prev_total = float(pm.group(1)) if pm else 0.0
        curr_match = re.search(r"([\d.]+)", m.group(1))
        if curr_match:
            info["kv_cache_total"] = prev_total + float(curr_match.group(1))
            return True
        return False
    _add(["kv buffer size", "cuda"], r"CUDA\d+\s+KV buffer size\s+=\s+(.+)", _handle_kv_buffer)

    _kv(["compute buffer size", "cuda"], r"CUDA\d+\s+compute buffer size\s+=\s+(.+)", "compute_buffer",
         exclude=["host", "cpu"])

    # --- Graph (old) ---
    _kv(["graph nodes", "sched_reserve"], r"graph nodes\s+=\s+(\d+)", "graph_nodes")
    _kv(["graph splits", "sched_reserve"], r"graph splits\s+=\s+(\d+)", "graph_splits")

    # --- n_ctx (old) ---
    _int_comma(["n_ctx", "llama_context"], r"n_ctx\s+=\s+(\d+)", "ctx_size",
               exclude=["n_ctx_seq", "n_ctx_orig", "n_ctx_train"])

    # --- Prompt cache (old) ---
    _kv("prompt cache is enabled", r"size limit:\s+([\d,]+)\s*MiB", "prompt_cache")

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


def parse_log_line(line, info):
    """Parse one log line, mutating `info`. Returns True if anything changed."""
    stripped = line.strip()
    lower = stripped.lower()
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


