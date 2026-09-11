import re
import subprocess
import logging

from core.i18n import t
from core.params_schema import fallback_defaults, help_flag_maps

logger = logging.getLogger(__name__)


# C1: default values are derived from the single parameter schema
# (core/params_schema.py) — no longer a hand-maintained copy.
_FALLBACK_DEFAULTS = fallback_defaults()

# C5: parameters excluded from the version-drift check (used by
# MainWindow._validate_params). These are per-user inputs (model paths, keys,
# free text) or machine-specific settings (CPU masks, device layout), so a
# "default" for them is not meaningful version drift. Genuine server-behavior
# defaults (e.g. tools, sampler_seq, cors_origins, cors_headers) are
# deliberately NOT in this set and participate in the drift check.
USER_INPUT_PARAMS = frozenset({
    # model / multimodal / LoRA / control vector paths
    "model", "mmproj", "lora", "lora_scaled",
    "control_vector", "control_vector_scaled", "control_vector_layer_range",
    "draft_model", "spec_draft_hf",
    # user file paths and free text
    "alias", "tags", "extra_args",
    "chat_template", "chat_template_file", "chat_template_kwargs",
    "reasoning_budget_message",
    "log_file", "ssl_key_file", "ssl_cert_file", "webui_config_file",
    "webui_config", "path", "api_prefix",
    "grammar", "grammar_file", "json_schema", "json_schema_file",
    "reverse_prompt", "logit_bias", "dry_sequence_breaker",
    "slot_save_path", "media_path",
    "hf_repo", "hf_file", "hf_token", "model_url", "docker_repo", "mmproj_url",
    "api_key", "api_key_file",
    "rpc", "override_tensor", "override_kv",
    "models_dir", "models_preset",
    "lookup_cache_static", "lookup_cache_dynamic",
    "mcp_servers_config", "mcp_servers_json", "tools_runtime",
    "log_prompts_dir",
    # machine-specific hardware settings
    "device", "device_draft", "tensor_split",
    "cpu_mask", "cpu_range", "cpu_mask_batch", "cpu_range_batch",
    "spec_draft_cpu_mask", "spec_draft_cpu_range", "spec_draft_cpu_mask_batch",
    # launcher-hardcoded known defaults (the parsed value is a launcher
    # constant, so a drift check against it would be meaningless)
    "samplers", "cors_methods",
    # log_verbosity: the launcher intentionally runs llama-server with 4
    # (trace) while the binary's own default is 3 — since llama.cpp #23021
    # the library INFO lines the runtime-info panel parses are suppressed at 3.
    "log_verbosity",
})

_PRIO_MAP = {0: "normal", -1: "low", 1: "medium", 2: "high", 3: "realtime"}
_PRIO_REVERSE = {v: k for k, v in _PRIO_MAP.items()}


def _parse_prio(text):
    try:
        return _PRIO_MAP.get(int(text), "normal")
    except (ValueError, TypeError):
        return "normal"


# C1: the three --help flag maps are derived from the parameter schema
# (core/params_schema.py). The schema buckets params by how
# CommandBuilder EMITS them: models_autoload is negatable (emits
# --no-models-autoload) while no_host / skip_chat_parsing are
# positive-only — the _FLAG_INDEX below treats the flag and neg
# buckets identically, so --help parsing is unchanged.
_PARSER_BY_NAME = {"int": int, "float": float, "str": str, "prio": _parse_prio}
_s_value, _s_flag, _s_neg = help_flag_maps()
_VALUE_FLAG_MAP = {k: (list(f), _PARSER_BY_NAME[pn]) for k, (f, pn) in _s_value.items()}
_FLAG_MAP = {k: list(f) for k, f in _s_flag.items()}
_NEG_FLAG_MAP = {k: list(f) for k, f in _s_neg.items()}


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


# B4: reverse index built once at import time: flag -> (param_key, parser, kind, flags).
# kind is "value" (typed parser) or "bool". The old parser re-split every help
# line once per known flag (~300 lines x ~300 flags); now each line is
# tokenized once and resolved by set intersection.
_FLAG_INDEX = {}
for _key, (_flags, _parser) in _VALUE_FLAG_MAP.items():
    for _f in _flags:
        _FLAG_INDEX[_f] = (_key, _parser, "value", _flags)
for _key, _flags in _FLAG_MAP.items():
    for _f in _flags:
        _FLAG_INDEX[_f] = (_key, None, "bool", _flags)
for _key, _flags in _NEG_FLAG_MAP.items():
    for _f in _flags:
        _FLAG_INDEX[_f] = (_key, None, "bool", _flags)
_INDEXED_FLAGS = frozenset(_FLAG_INDEX)


def _parse_help_to_defaults(help_text):
    defaults = dict(_FALLBACK_DEFAULTS)
    lines = help_text.split("\n")

    for i, line in enumerate(lines):
        if not line.strip().startswith("-"):
            continue  # skip blank lines and description continuation text
        combined = line
        j = i + 1
        while j < len(lines) and lines[j].strip():
            nxt = lines[j]
            stripped = nxt.strip()
            # A new option line starts with '-' at column 0 (current
            # --help layout) or at a shallow indent (older layouts
            # indented flags by two spaces). Deeply indented dash lines
            # are description list items — e.g. the -lv entries
            # " - 0: generic output" … " - 5: debug" — and must be
            # joined, otherwise the "(default: 3)" line after such a
            # list is missed and the value silently stays the fallback.
            # For -lv that made the live default 4 instead of the
            # binary's 3, so CommandBuilder's is_default() comparison
            # never emitted --log-verbosity and the server ran at its
            # built-in level 3 despite the UI showing 4.
            indent = len(nxt) - len(nxt.lstrip(" "))
            if stripped.startswith("-") and indent < 8:
                break
            combined += " " + stripped
            j += 1

        tokens = set(line.replace(",", " ").replace("=", " ").split())
        hits = tokens & _INDEXED_FLAGS
        if not hits:
            continue
        seen_params = set()
        for flag in hits:
            param_key, parser, kind, flags = _FLAG_INDEX[flag]
            if param_key in seen_params:
                continue
            seen_params.add(param_key)
            raw = _extract_default_from_text(combined, flags)
            if raw is None:
                continue
            if kind == "value":
                try:
                    defaults[param_key] = parser(raw)
                except (ValueError, TypeError):
                    pass
            else:
                val = _parse_bool(raw)
                if val is not None:
                    defaults[param_key] = val

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


def _resolve_server_path(server_path):
    """E1: resolve None to the configured/PATH server path.

    core.config is imported lazily: it imports this module, so a top-level
    import here would be circular.
    """
    if server_path:
        return server_path
    from core.config import get_server_path
    return get_server_path()


def _run_server_command(args, server_path=None):
    server_path = _resolve_server_path(server_path)
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


def get_server_version(server_path=None):
    stdout, stderr = _run_server_command(["--version"], server_path)
    if stdout is None:
        return None
    text = (stdout + stderr).strip()
    if text:
        # New format: "version: 10355 (dd1ea5243)"
        m = re.search(r"version:\s*(\d+)\s*\(", text)
        if m:
            return m.group(1)
        # Newer format: "version: 0.4.0-dev (build 10825, commit 9e0e22059)"
        m = re.search(r"version:[^\n]*\(build\s*(\d+)", text)
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


def fetch_help_text(server_path=None):
    stdout, stderr = _run_server_command(["--help"], server_path)
    if stdout is None and stderr is None:
        return None
    return (stdout or "") + (stderr or "")


def get_default_params(server_path=None, help_text=None):
    if help_text is None:
        stdout, stderr = _run_server_command(["--help"], server_path)
        if stdout is None and stderr is None:
            return dict(_FALLBACK_DEFAULTS)
        help_text = stdout if stdout and stdout.strip() else stderr
    if help_text and help_text.strip():
        return _parse_help_to_defaults(help_text)
    return dict(_FALLBACK_DEFAULTS)


def get_chat_templates(server_path=None, help_text=None):
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

# E8: --list-devices probe output parsing
_DEVICE_LINE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9]*\d*):\s*(.+?)\s+\((\d[\d,]*)\s*MiB,\s*(\d[\d,]*)\s*MiB\s+free\)\s*$",
    re.MULTILINE,
)


def parse_device_list(text):
    """Parse `llama-server --list-devices` output into a list of device dicts.

    The server prints one line per non-CPU backend, e.g.:

        Available devices:
          CUDA0: NVIDIA GeForce RTX 5090 (32579 MiB, 30819 MiB free)

    or `  (none)` when no GPU is available (CPU-only machines).
    """
    devices = []
    for m in _DEVICE_LINE_RE.finditer(text or ""):
        devices.append({
            "index": m.group(1),
            "name": m.group(2).strip(),
            "total_mib": int(m.group(3).replace(",", "")),
            "free_mib": int(m.group(4).replace(",", "")),
        })
    return devices
