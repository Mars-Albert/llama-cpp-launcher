import re
import subprocess
import logging

from core.i18n import t

logger = logging.getLogger(__name__)


_FALLBACK_DEFAULTS = {
    "threads": -1,
    "threads_batch": -1,
    "threads_http": -1,
    "prio": "normal",
    "prio_batch": "normal",
    "poll": 50,
    "poll_batch": 50,
    "cpu_strict": 0,
    "cpu_strict_batch": 0,
    "cpu_mask": "",
    "cpu_range": "",
    "cpu_mask_batch": "",
    "cpu_range_batch": "",
    "ctx_size": 0,
    "n_predict": -1,
    "batch_size": 2048,
    "ubatch_size": 512,
    "keep": 0,
    "swa_full": False,
    "flash_attn": "auto",
    "perf": False,
    "escape": True,
    "defrag_thold": 0,
    "rope_scaling": "linear",
    "rope_scale": 0,
    "rope_freq_base": 0,
    "rope_freq_scale": 0,
    "yarn_orig_ctx": 0,
    "yarn_ext_factor": -1.0,
    "yarn_attn_factor": -1.0,
    "yarn_beta_slow": -1.0,
    "yarn_beta_fast": -1.0,
    "kv_offload": True,
    "repack": True,
    "no_host": False,
    "cache_type_k": "f16",
    "cache_type_v": "f16",
    "mlock": False,
    "mmap": True,
    "direct_io": False,
    "numa": "disable",
    "device": "",
    "load_mode": "auto",
    "split_mode": "layer",
    "tensor_split": "",
    "rpc": "",
    "main_gpu": 0,
    "n_gpu_layers": "auto",
    "fit": "on",
    "fit_target": "1024",
    "fit_ctx": 4096,
    "check_tensors": False,
    "override_tensor": "",
    "override_kv": "",
    "op_offload": True,
    "n_cpu_moe": 0,
    "lora": [],
    "lora_scaled": [],
    "control_vector": [],
    "control_vector_scaled": [],
    "control_vector_layer_range": "",
    "alias": "",
    "tags": "",
    "samplers": "penalties;dry;top_n_sigma;top_k;typ_p;top_p;min_p;xtc;temperature",
    "sampler_seq": "edskypmxt",
    "seed": -1,
    "ignore_eos": False,
    "temp": 0.8,
    "top_k": 40,
    "top_p": 0.95,
    "min_p": 0.05,
    "top_n_sigma": -1.0,
    "xtc_probability": 0.0,
    "xtc_threshold": 0.1,
    "typical_p": 1.0,
    "repeat_last_n": 64,
    "repeat_penalty": 1.0,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "dry_multiplier": 0.0,
    "dry_base": 1.75,
    "dry_allowed_length": 2,
    "dry_penalty_last_n": 64,
    "dry_sequence_breaker": "",
    "adaptive_target": -1.0,
    "adaptive_decay": 0.9,
    "dynatemp_range": 0.0,
    "dynatemp_exp": 1.0,
    "mirostat": 0,
    "mirostat_lr": 0.1,
    "mirostat_ent": 5.0,
    "backend_sampling": False,
    "logit_bias": "",
    "grammar": "",
    "grammar_file": "",
    "json_schema": "",
    "json_schema_file": "",
    "ctx_checkpoints": 32,
    "checkpoint_min_step": 8192,
    "cache_ram": 8192,
    "kv_unified": True,
    "cache_idle_slots": True,
    "context_shift": False,
    "spm_infill": False,
    "warmup": True,
    "pooling": "none",
    "embd_normalize": 2,
    "cpu_moe": False,
    "mmproj_auto": True,
    "mmproj_offload": True,
    "image_min_tokens": 0,
    "image_max_tokens": 0,
    "mtmd_batch_max_tokens": 1024,
    "verbose": False,
    "log_verbosity": 3,
    "log_colors": "auto",
    "log_file": "",
    "log_disable": False,
    "log_prompts_dir": "",
    "log_prefix": False,
    "log_timestamps": False,
    "offline": False,
    "host": "127.0.0.1",
    "port": 8080,
    "sse_ping_interval": 30,
    "cors_origins": "*",
    "cors_methods": "GET, POST, DELETE, OPTIONS",
    "cors_headers": "*",
    "cors_credentials": True,
    "reuse_port": False,
    "path": "",
    "api_prefix": "",
    "webui": True,
    "webui_config": "",
    "webui_config_file": "",
    "webui_mcp_proxy": False,
    "tools": [],
    "tools_runtime": "",
    "mcp_servers_config": "",
    "mcp_servers_json": "",
    "agent": False,
    "embedding": False,
    "rerank": False,
    "timeout": 3600,
    "cache_prompt": True,
    "cache_reuse": 0,
    "metrics": False,
    "props": False,
    "slots": True,
    "slot_save_path": "",
    "media_path": "",
    "jinja": True,
    "reasoning": "auto",
    "reasoning_format": "auto",
    "reasoning_budget": -1,
    "reasoning_budget_message": "",
    "reasoning_preserve": False,
    "chat_template": "",
    "chat_template_file": "",
    "chat_template_kwargs": "",
    "skip_chat_parsing": False,
    "prefill_assistant": True,
    "slot_prompt_similarity": 0.1,
    "lora_init_without_apply": False,
    "sleep_idle_seconds": -1,
    "cont_batching": True,
    "parallel": -1,
    "ssl_key_file": "",
    "ssl_cert_file": "",
    "api_key": "",
    "api_key_file": "",
    "extra_args": "",
    "model": "",
    "model_url": "",
    "docker_repo": "",
    "hf_repo": "",
    "hf_file": "",
    "hf_token": "",
    "mmproj": "",
    "mmproj_url": "",
    "reverse_prompt": "",
    "special": False,
    "draft_model": "",
    "spec_draft_hf": "",
    "threads_draft": -1,
    "threads_batch_draft": -1,
    "spec_draft_cpu_mask": "",
    "spec_draft_cpu_range": "",
    "spec_draft_cpu_strict": 0,
    "spec_draft_prio": "normal",
    "spec_draft_poll": 50,
    "spec_draft_cpu_mask_batch": "",
    "spec_draft_cpu_strict_batch": 0,
    "spec_draft_prio_batch": "normal",
    "spec_draft_poll_batch": 50,
    "device_draft": "",
    "n_gpu_layers_draft": "auto",
    "cpu_moe_draft": False,
    "n_cpu_moe_draft": 0,
    "cache_type_k_draft": "f16",
    "cache_type_v_draft": "f16",
    "draft_max": 3,
    "draft_min": 0,
    "draft_p_min": 0.0,
    "spec_draft_p_split": 0.10,
    "spec_draft_backend_sampling": True,
    "spec_type": "none",
    "spec_ngram_size_n": 12,
    "spec_ngram_size_m": 48,
    "spec_ngram_min_hits": 1,
    "spec_ngram_mod_n_min": 48,
    "spec_ngram_mod_n_max": 64,
    "spec_ngram_mod_n_match": 24,
    "spec_ngram_map_k_size_n": 12,
    "spec_ngram_map_k_size_m": 48,
    "spec_ngram_map_k_min_hits": 1,
    "spec_ngram_map_k4v_size_n": 12,
    "spec_ngram_map_k4v_size_m": 48,
    "spec_ngram_map_k4v_min_hits": 1,
    "lookup_cache_static": "",
    "lookup_cache_dynamic": "",
    "models_max": 4,
    "models_autoload": True,
    "models_dir": "",
    "models_preset": "",
    "override_tensor_draft": "",
}

_PRIO_MAP = {0: "normal", -1: "low", 1: "medium", 2: "high", 3: "realtime"}
_PRIO_REVERSE = {v: k for k, v in _PRIO_MAP.items()}


def _parse_prio(text):
    try:
        return _PRIO_MAP.get(int(text), "normal")
    except (ValueError, TypeError):
        return "normal"


_VALUE_FLAG_MAP = {
    "threads": (["-t", "--threads"], int),
    "threads_batch": (["-tb", "--threads-batch"], int),
    "threads_http": (["--threads-http"], int),
    "prio": (["--prio"], _parse_prio),
    "prio_batch": (["--prio-batch"], _parse_prio),
    "poll": (["--poll"], int),
    "poll_batch": (["--poll-batch"], int),
    "cpu_strict": (["--cpu-strict"], int),  # <0|1>
    "cpu_strict_batch": (["--cpu-strict-batch"], int),  # <0|1>
    "cpu_mask": (["-C", "--cpu-mask"], str),
    "cpu_range": (["-Cr", "--cpu-range"], str),
    "cpu_mask_batch": (["-Cb", "--cpu-mask-batch"], str),
    "cpu_range_batch": (["-Crb", "--cpu-range-batch"], str),
    "ctx_size": (["-c", "--ctx-size"], int),
    "n_predict": (["-n", "--predict", "--n-predict"], int),
    "batch_size": (["-b", "--batch-size"], int),
    "ubatch_size": (["-ub", "--ubatch-size"], int),
    "keep": (["--keep"], int),
    "defrag_thold": (["-dt", "--defrag-thold"], float),  # DEPRECATED
    "flash_attn": (["-fa", "--flash-attn"], str),  # [on|off|auto]
    "rope_scaling": (["--rope-scaling"], str),
    "rope_scale": (["--rope-scale"], float),
    "rope_freq_base": (["--rope-freq-base"], float),
    "rope_freq_scale": (["--rope-freq-scale"], float),
    "yarn_orig_ctx": (["--yarn-orig-ctx"], int),
    "yarn_ext_factor": (["--yarn-ext-factor"], float),
    "yarn_attn_factor": (["--yarn-attn-factor"], float),
    "yarn_beta_slow": (["--yarn-beta-slow"], float),
    "yarn_beta_fast": (["--yarn-beta-fast"], float),
    "cache_type_k": (["-ctk", "--cache-type-k"], str),
    "cache_type_v": (["-ctv", "--cache-type-v"], str),
    "device": (["-dev", "--device"], str),
    "load_mode": (["-lm", "--load-mode"], str),
    "split_mode": (["-sm", "--split-mode"], str),  # {none,layer,row,tensor}
    "tensor_split": (["-ts", "--tensor-split"], str),
    "rpc": (["--rpc"], str),
    "main_gpu": (["-mg", "--main-gpu"], int),
    "n_gpu_layers": (["-ngl", "--gpu-layers", "--n-gpu-layers"], str),  # N, 'auto', or 'all'
    "fit": (["-fit", "--fit"], str),
    "fit_target": (["-fitt", "--fit-target"], str),
    "fit_ctx": (["-fitc", "--fit-ctx"], int),
    "n_cpu_moe": (["-ncmoe", "--n-cpu-moe"], int),
    "override_tensor": (["-ot", "--override-tensor"], str),
    "override_kv": (["--override-kv"], str),
    "lora_scaled": (["--lora-scaled"], str),
    "control_vector_scaled": (["--control-vector-scaled"], str),
    "control_vector_layer_range": (["--control-vector-layer-range"], str),
    "alias": (["-a", "--alias"], str),
    "tags": (["--tags"], str),
    "samplers": (["--samplers"], str),
    "sampler_seq": (["--sampler-seq", "--sampling-seq"], str),
    "seed": (["-s", "--seed"], int),
    "temp": (["--temp", "--temperature"], float),
    "top_k": (["--top-k"], int),
    "top_p": (["--top-p"], float),
    "min_p": (["--min-p"], float),
    "top_n_sigma": (["--top-nsigma", "--top-n-sigma"], float),
    "xtc_probability": (["--xtc-probability"], float),
    "xtc_threshold": (["--xtc-threshold"], float),
    "typical_p": (["--typical", "--typical-p"], float),
    "repeat_last_n": (["--repeat-last-n"], int),
    "repeat_penalty": (["--repeat-penalty"], float),
    "presence_penalty": (["--presence-penalty"], float),
    "frequency_penalty": (["--frequency-penalty"], float),
    "dry_multiplier": (["--dry-multiplier"], float),
    "dry_base": (["--dry-base"], float),
    "dry_allowed_length": (["--dry-allowed-length"], int),
    "dry_penalty_last_n": (["--dry-penalty-last-n"], int),
    "dry_sequence_breaker": (["--dry-sequence-breaker"], str),
    "adaptive_target": (["--adaptive-target"], float),
    "adaptive_decay": (["--adaptive-decay"], float),
    "dynatemp_range": (["--dynatemp-range"], float),
    "dynatemp_exp": (["--dynatemp-exp"], float),
    "mirostat": (["--mirostat"], int),
    "mirostat_lr": (["--mirostat-lr"], float),
    "mirostat_ent": (["--mirostat-ent"], float),
    "logit_bias": (["-l", "--logit-bias"], str),
    "grammar": (["--grammar"], str),
    "grammar_file": (["--grammar-file"], str),
    "json_schema": (["-j", "--json-schema"], str),
    "json_schema_file": (["-jf", "--json-schema-file"], str),
    "ctx_checkpoints": (["-ctxcp", "--ctx-checkpoints", "--swa-checkpoints"], int),
    "checkpoint_min_step": (["-cms", "--checkpoint-min-step"], int),
    "cache_ram": (["-cram", "--cache-ram"], int),
    "pooling": (["--pooling"], str),
    "embd_normalize": (["--embd-normalize"], int),
    "image_min_tokens": (["--image-min-tokens"], int),
    "image_max_tokens": (["--image-max-tokens"], int),
    "mtmd_batch_max_tokens": (["--mtmd-batch-max-tokens"], int),
    "log_verbosity": (["-lv", "--verbosity", "--log-verbosity"], int),
    "log_colors": (["--log-colors"], str),
    "log_file": (["--log-file"], str),
    "log_prompts_dir": (["--log-prompts-dir"], str),
    "host": (["--host"], str),
    "port": (["--port"], int),
    "sse_ping_interval": (["--sse-ping-interval"], int),
    "cors_origins": (["--cors-origins"], str),
    "cors_methods": (["--cors-methods"], str),
    "cors_headers": (["--cors-headers"], str),
    "path": (["--path"], str),
    "api_prefix": (["--api-prefix"], str),
    "webui_config": (["--webui-config", "--ui-config"], str),
    "webui_config_file": (["--webui-config-file", "--ui-config-file"], str),
    "timeout": (["-to", "--timeout"], int),
    "cache_reuse": (["--cache-reuse"], int),
    "slot_save_path": (["--slot-save-path"], str),
    "media_path": (["--media-path"], str),
    "reasoning": (["-rea", "--reasoning"], str),
    "reasoning_format": (["--reasoning-format"], str),
    "reasoning_budget": (["--reasoning-budget"], int),
    "reasoning_budget_message": (["--reasoning-budget-message"], str),
    "chat_template": (["--chat-template"], str),
    "chat_template_file": (["--chat-template-file"], str),
    "chat_template_kwargs": (["--chat-template-kwargs"], str),
    "slot_prompt_similarity": (["-sps", "--slot-prompt-similarity"], float),
    "sleep_idle_seconds": (["--sleep-idle-seconds"], int),
    "parallel": (["-np", "--parallel"], int),
    "ssl_key_file": (["--ssl-key-file"], str),
    "ssl_cert_file": (["--ssl-cert-file"], str),
    "api_key": (["--api-key"], str),
    "api_key_file": (["--api-key-file"], str),
    "model_url": (["-mu", "--model-url"], str),
    "docker_repo": (["-dr", "--docker-repo"], str),
    "hf_repo": (["-hf", "-hfr", "--hf-repo"], str),
    "hf_file": (["-hff", "--hf-file"], str),
    "hf_token": (["-hft", "--hf-token"], str),
    "mmproj_url": (["-mmu", "--mmproj-url"], str),
    "draft_model": (["-md", "--model-draft", "--spec-draft-model"], str),
    "spec_draft_hf": (["--spec-draft-hf", "-hfd", "-hfrd", "--hf-repo-draft"], str),
    "threads_draft": (["-td", "--threads-draft", "--spec-draft-threads"], int),
    "threads_batch_draft": (["-tbd", "--threads-batch-draft", "--spec-draft-threads-batch"], int),
    "spec_draft_cpu_mask": (["--spec-draft-cpu-mask", "-Cd", "--cpu-mask-draft"], str),
    "spec_draft_cpu_range": (["--spec-draft-cpu-range", "-Crd", "--cpu-range-draft"], str),
    "spec_draft_cpu_strict": (["--spec-draft-cpu-strict", "--cpu-strict-draft"], int),
    "spec_draft_prio": (["--spec-draft-prio", "--prio-draft"], _parse_prio),
    "spec_draft_poll": (["--spec-draft-poll", "--poll-draft"], int),
    "spec_draft_cpu_mask_batch": (["--spec-draft-cpu-mask-batch", "-Cbd", "--cpu-mask-batch-draft"], str),
    "spec_draft_cpu_strict_batch": (["--spec-draft-cpu-strict-batch", "--cpu-strict-batch-draft"], int),
    "spec_draft_prio_batch": (["--spec-draft-prio-batch", "--prio-batch-draft"], _parse_prio),
    "spec_draft_poll_batch": (["--spec-draft-poll-batch", "--poll-batch-draft"], int),
    "device_draft": (["-devd", "--device-draft", "--spec-draft-device"], str),
    "n_gpu_layers_draft": (["-ngld", "--gpu-layers-draft", "--n-gpu-layers-draft", "--spec-draft-ngl"], str),
    "n_cpu_moe_draft": (["-ncmoed", "--n-cpu-moe-draft", "--spec-draft-n-cpu-moe", "--spec-draft-ncmoe"], int),
    "cache_type_k_draft": (["--spec-draft-type-k", "-ctkd", "--cache-type-k-draft"], str),
    "cache_type_v_draft": (["--spec-draft-type-v", "-ctvd", "--cache-type-v-draft"], str),
    "draft_max": (["--spec-draft-n-max"], int),
    "draft_min": (["--spec-draft-n-min"], int),
    "draft_p_min": (["--spec-draft-p-min", "--draft-p-min"], float),
    "spec_draft_p_split": (["--spec-draft-p-split", "--draft-p-split"], float),
    "spec_ngram_size_n": (["--spec-ngram-simple-size-n"], int),
    "spec_ngram_size_m": (["--spec-ngram-simple-size-m"], int),
    "spec_ngram_min_hits": (["--spec-ngram-simple-min-hits"], int),
    "spec_ngram_mod_n_min": (["--spec-ngram-mod-n-min"], int),
    "spec_ngram_mod_n_max": (["--spec-ngram-mod-n-max"], int),
    "spec_ngram_mod_n_match": (["--spec-ngram-mod-n-match"], int),
    "spec_ngram_map_k_size_n": (["--spec-ngram-map-k-size-n"], int),
    "spec_ngram_map_k_size_m": (["--spec-ngram-map-k-size-m"], int),
    "spec_ngram_map_k_min_hits": (["--spec-ngram-map-k-min-hits"], int),
    "spec_ngram_map_k4v_size_n": (["--spec-ngram-map-k4v-size-n"], int),
    "spec_ngram_map_k4v_size_m": (["--spec-ngram-map-k4v-size-m"], int),
    "spec_ngram_map_k4v_min_hits": (["--spec-ngram-map-k4v-min-hits"], int),
    "lookup_cache_static": (["-lcs", "--lookup-cache-static"], str),
    "lookup_cache_dynamic": (["-lcd", "--lookup-cache-dynamic"], str),
    "models_max": (["--models-max"], int),
    "models_dir": (["--models-dir"], str),
    "models_preset": (["--models-preset"], str),
    "tools_runtime": (["--tools-runtime"], str),
    "mcp_servers_config": (["--mcp-servers-config"], str),
    "mcp_servers_json": (["--mcp-servers-json"], str),
    "numa": (["--numa"], str),
    "reverse_prompt": (["-r", "--reverse-prompt"], str),
    "spec_type": (["--spec-type"], str),
    "override_tensor_draft": (["--spec-draft-override-tensor", "-otd"], str),
}

_FLAG_MAP = {
    "swa_full": ["--swa-full"],
    "perf": ["--perf"],
    "context_shift": ["--context-shift"],
    "spm_infill": ["--spm-infill"],
    "cpu_moe": ["--cpu-moe"],
    "cpu_moe_draft": ["-cmoed", "--cpu-moe-draft", "--spec-draft-cpu-moe"],
    "check_tensors": ["--check-tensors"],
    "verbose": ["--verbose"],
    "log_prefix": ["--log-prefix"],
    "log_timestamps": ["--log-timestamps"],
    "log_disable": ["--log-disable"],
    "offline": ["--offline"],
    "reuse_port": ["--reuse-port"],
    "webui_mcp_proxy": ["--webui-mcp-proxy", "--ui-mcp-proxy"],
    "embedding": ["--embedding"],
    "rerank": ["--rerank"],
    "backend_sampling": ["-bs", "--backend-sampling"],
    "metrics": ["--metrics"],
    "props": ["--props"],
    "special": ["-sp", "--special"],
    "ignore_eos": ["--ignore-eos"],
    "mlock": ["--mlock"],
    "direct_io": ["--direct-io"],
    "lora_init_without_apply": ["--lora-init-without-apply"],
    "models_autoload": ["--models-autoload"],
    "reasoning_preserve": ["--reasoning-preserve"],
    "agent": ["-ag", "--agent"],
}

_NEG_FLAG_MAP = {
    "kv_offload": ["-nkvo", "--no-kv-offload"],
    "repack": ["-nr", "--no-repack"],
    "no_host": ["--no-host"],
    "mmap": ["--no-mmap"],
    "op_offload": ["--no-op-offload"],
    "cache_prompt": ["--no-cache-prompt"],
    "kv_unified": ["-no-kvu", "--no-kv-unified"],
    "slots": ["--no-slots"],
    "jinja": ["--no-jinja"],
    "skip_chat_parsing": ["--skip-chat-parsing"],
    "prefill_assistant": ["--no-prefill-assistant"],
    "cont_batching": ["-nocb", "--no-cont-batching"],
    "escape": ["--no-escape"],
    "warmup": ["--no-warmup"],
    "mmproj_auto": ["--no-mmproj", "--no-mmproj-auto"],
    "mmproj_offload": ["--no-mmproj-offload"],
    "cache_idle_slots": ["--no-cache-idle-slots"],
    "webui": ["--no-webui"],
    "cors_credentials": ["--no-cors-credentials"],
    "spec_draft_backend_sampling": ["--no-spec-draft-backend-sampling"],
    "webui_mcp_proxy": ["--no-webui-mcp-proxy", "--no-ui-mcp-proxy"],
    "context_shift": ["--no-context-shift"],
}


_KNOWN_STRING_DEFAULTS = {
    "--samplers": "penalties;dry;top_n_sigma;top_k;typ_p;top_p;min_p;xtc;temperature",
    "--fit": "on",
    "--chat-template": "",
    "--chat-template-file": "",
    "--reasoning-budget-message": "",
    "--model": "",
    "--mmproj": "",
    "--grammar": "",
    "--json-schema": "",
    "--logit-bias": "",
    "--prio": "normal",
    "--prio-batch": "normal",
    "--hf-token": "",
    "--cors-methods": "GET, POST, DELETE, OPTIONS",
    "--cpu-mask-batch": "",
    "--spec-draft-cpu-mask": "",
    "--spec-draft-cpu-mask-batch": "",
}


def _extract_default_from_text(text, flags):
    for flag in flags:
        if flag in _KNOWN_STRING_DEFAULTS:
            return _KNOWN_STRING_DEFAULTS[flag]
    m = re.search(r"default:\s*'([^']*)'", text)
    if m:
        return m.group(1)
    m = re.search(r'default:\s*"([^"]*)"', text)
    if m:
        return m.group(1)
    m = re.search(r"default:\s*(\S+)", text)
    if m:
        raw = m.group(1).rstrip(",)")
        return raw
    return None


def _parse_bool(text):
    lower_text = text.strip().lower()
    if lower_text in ("true", "enabled", "on", "1"):
        return True
    if lower_text in ("false", "disabled", "off", "0"):
        return False
    return None


def _parse_help_to_defaults(help_text):
    defaults = dict(_FALLBACK_DEFAULTS)
    lines = help_text.split("\n")

    for i, line in enumerate(lines):
        if not line.strip().startswith("-"):
            continue  # skip blank lines and description continuation text
        combined = line
        j = i + 1
        while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("-"):
            combined += " " + lines[j].strip()
            j += 1

        for param_key, (flags, parser) in _VALUE_FLAG_MAP.items():
            for flag in flags:
                if _flag_in_line(flag, line):
                    if flag in _KNOWN_STRING_DEFAULTS:
                        defaults[param_key] = _KNOWN_STRING_DEFAULTS[flag]
                    else:
                        raw = _extract_default_from_text(combined, flags)
                        if raw is not None:
                            try:
                                defaults[param_key] = parser(raw)
                            except (ValueError, TypeError):
                                pass
                    break

        for param_key, flags in _FLAG_MAP.items():
            for flag in flags:
                if _flag_in_line(flag, line):
                    raw = _extract_default_from_text(combined, flags)
                    if raw is not None:
                        val = _parse_bool(raw)
                        if val is not None:
                            defaults[param_key] = val
                    break

        for param_key, flags in _NEG_FLAG_MAP.items():
            for flag in flags:
                if _flag_in_line(flag, line):
                    raw = _extract_default_from_text(combined, flags)
                    if raw is not None:
                        val = _parse_bool(raw)
                        if val is not None:
                            defaults[param_key] = val
                    break

    # Normalize placeholder strings from --help to empty string
    # These mean "not set" in llama-server but would display as literal text in the GUI
    _PLACEHOLDER_DEFAULTS = {"none", "unused", "disabled"}
    for key in ("api_key", "api_key_file", "draft_model", "media_path", "slot_save_path",
                "hf_repo", "hf_file", "model_url", "docker_repo", "mmproj_url",
                "spec_draft_hf", "models_dir", "models_preset", "tools_runtime",
                "mcp_servers_config", "mcp_servers_json", "log_prompts_dir"):
        if defaults.get(key) in _PLACEHOLDER_DEFAULTS:
            defaults[key] = ""

    return defaults


def _flag_in_line(flag, line):
    parts = line.replace(",", " ").replace("=", " ").split()
    for part in parts:
        part_clean = part.strip(",")
        if part_clean == flag:
            return True
    return False


def _run_server_command(args, server_path="llama-server"):
    try:
        result = subprocess.run(
            [server_path] + args,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout, result.stderr
    except FileNotFoundError:
        logger.warning(t("未找到 {server_path}，请确保它在系统 PATH 中。", server_path=server_path))
        return None, None
    except subprocess.TimeoutExpired:
        logger.warning(t("{server_path} 命令超时（10秒）", server_path=server_path))
        return None, None
    except OSError as e:
        logger.warning(t("运行 {server_path} 命令失败: {e}", server_path=server_path, e=e))
        return None, None


def get_server_version(server_path="llama-server"):
    stdout, stderr = _run_server_command(["--version"], server_path)
    if stdout is None:
        return None
    text = (stdout + stderr).strip()
    if text:
        # New format: "version: 10355 (dd1ea5243)"
        m = re.search(r"version:\s*(\d+)", text)
        if m:
            return m.group(1)
        # Old format: "b1234"
        m = re.search(r"b\d+", text)
        if m:
            return m.group(0)
        m = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text)
        if m:
            return m.group(1)
        return text[:50]
    return None


def fetch_help_text(server_path="llama-server"):
    stdout, stderr = _run_server_command(["--help"], server_path)
    if stdout is None and stderr is None:
        return None
    return (stdout or "") + (stderr or "")


def get_default_params(server_path="llama-server", help_text=None):
    if help_text is None:
        stdout, stderr = _run_server_command(["--help"], server_path)
        if stdout is None and stderr is None:
            return dict(_FALLBACK_DEFAULTS)
        help_text = stdout if stdout and stdout.strip() else stderr
    if help_text and help_text.strip():
        return _parse_help_to_defaults(help_text)
    return dict(_FALLBACK_DEFAULTS)


def get_chat_templates(server_path="llama-server", help_text=None):
    if help_text is None:
        stdout, stderr = _run_server_command(["--help"], server_path)
        if stdout is None and stderr is None:
            return []
        help_text = (stdout or "") + (stderr or "")
    templates = []
    seen = set()
    in_list = False
    for line in help_text.split("\n"):
        if "list of built-in templates:" in line.lower():
            in_list = True
            continue
        if in_list:
            stripped = line.strip()
            # End of list: blank line, env line, or a new flag
            if not stripped or stripped.startswith("(") or stripped.startswith("-"):
                break
            for name in re.split(r"[,\s]+", stripped):
                name = name.strip()
                if name and name[0].isalpha() and name not in seen:
                    seen.add(name)
                    templates.append(name)
    return templates if templates else []
