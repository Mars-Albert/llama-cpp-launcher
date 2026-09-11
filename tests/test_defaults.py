"""Tests for the llama-server --help parser (core/defaults.py).

Covers: numeric/bool/string default extraction, flag aliases, placeholder
normalization, prio mapping, _KNOWN_STRING_DEFAULTS, chat template extraction,
version parsing, and fallback behavior when llama-server is unavailable.

`tests/data/llama-server-help-b10825.txt` is a real `llama-server --help`
capture (build 10825, new srv-prefixed format). The old-format sample below
is a minimal reconstruction of legacy (pre-9174) single-line help entries.
"""
from pathlib import Path

from core import defaults as D
from core.defaults import (
    _FALLBACK_DEFAULTS,
    _parse_bool,
    _parse_help_to_defaults,
    _parse_prio,
    get_chat_templates,
    get_default_params,
    get_server_version,
)

DATA_DIR = Path(__file__).parent / "data"
HELP_NEW = (DATA_DIR / "llama-server-help-b10825.txt").read_text(encoding="utf-8")

# Legacy (old-format) help: one line per flag, defaults inline
HELP_OLD = """\
usage:
  llama-server [options]

options:
  -h,  --help               Show help and exit.
  -m FNAME, --model FNAME   Model path (default: '')
  -c N, --ctx-size N        Text context size (default: 4096)
  -b N, --batch-size N      Batch size for non-interactive mode (default: 2048)
  -ngl N, --gpu-layers N    How many layers to push to the GPU (default: 0)
  -t N, --threads N         Number of threads (default: 8)
  --prio N                  Thread priority class (default: 0)
  --mmap, --no-mmap         Memory-map the model (default: enabled)
  --flash-attn [on|off]     Flash attention (default: auto)
  --api-key STR             API key (default: none)
  --samplers STR            List of samplers (default: 'top_k;top_p')
"""


# ---------------------------------------------------------------------------
# New format (real capture, build 10825)
# ---------------------------------------------------------------------------

class TestParseHelpNewFormat:
    def test_result_superset_of_fallback_keys(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert set(_FALLBACK_DEFAULTS) <= set(d)

    def test_int_defaults(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["ctx_size"] == 0
        assert d["n_predict"] == -1
        assert d["batch_size"] == 2048

    def test_bool_defaults(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["mmap"] is True
        assert d["escape"] is True

    def test_string_defaults(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["flash_attn"] == "auto"
        assert d["n_gpu_layers"] == "auto"
        assert d["split_mode"] == "layer"
        assert d["rope_scaling"] == "linear"
        assert d["cache_type_k"] == "f16"

    def test_prio_mapping(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["prio"] == "normal"
        assert d["prio_batch"] == "normal"

    def test_known_string_defaults(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["samplers"] == (
            "penalties;dry;top_n_sigma;top_k;typ_p;top_p;min_p;xtc;temperature"
        )
        assert d["fit"] == "on"

    def test_placeholder_api_key_normalized_to_empty(self):
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["api_key"] == ""

    def test_multiline_description_joined(self):
        # In the real capture the --mmap default sits on a continuation line:
        #   --mmap, --no-mmap  DEPRECATED in favor of `--load-mode`: whether
        #                      to memory-map model. (if ...)
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["mmap"] is True

    def test_log_verbosity_default_after_dash_list(self):
        # The -lv description is a multi-line list whose items start with
        # "-" (" - 0: generic output" … " - 5: debug"); the continuation
        # join must keep going over those indented dash lines so the
        # trailing "(default: 3)" is found. When it was missed the live
        # default stayed the launcher's fallback 4, CommandBuilder saw
        # value 4 == "default" 4 and never emitted --log-verbosity, so
        # the server ran at its built-in 3 while the UI showed 4 (and
        # the runtime panel kept showing the low-verbosity hint).
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["log_verbosity"] == 3

    def test_reasoning_format_default_after_dash_list(self):
        # Same shape as -lv: list items, then "(default: auto)".
        d = _parse_help_to_defaults(HELP_NEW)
        assert d["reasoning_format"] == "auto"


# ---------------------------------------------------------------------------
# Old format (synthetic legacy sample)
# ---------------------------------------------------------------------------

class TestParseHelpOldFormat:
    def test_int_defaults(self):
        d = _parse_help_to_defaults(HELP_OLD)
        assert d["ctx_size"] == 4096
        assert d["batch_size"] == 2048
        assert d["threads"] == 8

    def test_string_defaults(self):
        d = _parse_help_to_defaults(HELP_OLD)
        assert d["n_gpu_layers"] == "0"
        assert d["flash_attn"] == "auto"

    def test_bool_and_prio(self):
        d = _parse_help_to_defaults(HELP_OLD)
        assert d["mmap"] is True
        assert d["prio"] == "normal"

    def test_placeholder_normalization(self):
        d = _parse_help_to_defaults(HELP_OLD)
        # (default: none) is a "not set" placeholder -> ""
        assert d["api_key"] == ""

    def test_flag_alias_short_form(self):
        # The line carries both -c and --ctx-size; either alias must match
        d = _parse_help_to_defaults(HELP_OLD)
        assert d["ctx_size"] == 4096

    def test_fallback_preserved_for_unlisted_flags(self):
        d = _parse_help_to_defaults(HELP_OLD)
        # Not mentioned in the sample -> fallback value stays
        assert d["webui"] is True
        assert d["parallel"] == _FALLBACK_DEFAULTS["parallel"]


# ---------------------------------------------------------------------------
# Placeholder normalization (all accepted tokens)
# ---------------------------------------------------------------------------

class TestPlaceholderNormalization:
    def test_none_unused_disabled_all_become_empty(self):
        text = (
            "--api-key STR          key (default: none)\n"
            "--draft-model FNAME    draft (default: unused)\n"
            "--hf-repo REPO         repo (default: disabled)\n"
        )
        d = _parse_help_to_defaults(text)
        assert d["api_key"] == ""
        assert d["draft_model"] == ""
        assert d["hf_repo"] == ""

    def test_real_value_kept(self):
        text = "--api-key STR  key (default: secret123)\n"
        d = _parse_help_to_defaults(text)
        assert d["api_key"] == "secret123"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestParseBool:
    def test_truthy(self):
        for raw in ("true", "True", "enabled", "on", "1"):
            assert _parse_bool(raw) is True, raw

    def test_falsy(self):
        for raw in ("false", "False", "disabled", "off", "0"):
            assert _parse_bool(raw) is False, raw

    def test_non_bool(self):
        assert _parse_bool("auto") is None
        assert _parse_bool("") is None


class TestParsePrio:
    def test_all_classes(self):
        assert _parse_prio("0") == "normal"
        assert _parse_prio("-1") == "low"
        assert _parse_prio("1") == "medium"
        assert _parse_prio("2") == "high"
        assert _parse_prio("3") == "realtime"

    def test_unknown_falls_back_to_normal(self):
        assert _parse_prio("99") == "normal"
        assert _parse_prio("high") == "normal"
        assert _parse_prio("") == "normal"


# ---------------------------------------------------------------------------
# Chat template extraction
# ---------------------------------------------------------------------------

class TestChatTemplates:
    def test_extracts_names_from_list(self):
        text = (
            "--chat-template STR  Chat template (default: '')\n"
            "    list of built-in templates:\n"
            "        bailing, bailing-think, chatglm3\n"
            "        chatml, command-r, deepseek\n"
            "    (env: LLAMA_CHAT_TEMPLATE)\n"
        )
        assert get_chat_templates(help_text=text) == [
            "bailing", "bailing-think", "chatglm3", "chatml", "command-r", "deepseek"
        ]

    def test_real_capture_has_templates(self):
        names = get_chat_templates(help_text=HELP_NEW)
        assert "chatml" in names
        assert len(names) >= 10

    def test_empty_when_no_list(self):
        assert get_chat_templates(help_text="no templates here\n-h --help\n") == []

    def test_stops_at_new_flag(self):
        text = (
            "list of built-in templates:\n"
            "    chatml, llama3\n"
            "-m FNAME   model\n"
            "    more, junk\n"
        )
        assert get_chat_templates(help_text=text) == ["chatml", "llama3"]


# ---------------------------------------------------------------------------
# Version parsing (subprocess stubbed)
# ---------------------------------------------------------------------------

class TestGetServerVersion:
    def test_new_format(self, monkeypatch):
        monkeypatch.setattr(
            D, "_run_server_command",
            lambda args, server_path="llama-server": ("version: 10355 (dd1ea5243)\n", ""),
        )
        assert get_server_version() == "10355"

    def test_newer_build_format(self, monkeypatch):
        monkeypatch.setattr(
            D, "_run_server_command",
            lambda args, server_path="llama-server": (
                "version: 0.4.0-dev (build 10825, commit 9e0e22059)\n"
                "built with MSVC 19.43.34809.0 for x64\n",
                "",
            ),
        )
        assert get_server_version() == "10825"

    def test_old_build_format(self, monkeypatch):
        monkeypatch.setattr(
            D, "_run_server_command",
            lambda args, server_path="llama-server": ("llama-server  b12345\n", ""),
        )
        assert get_server_version() == "b12345"

    def test_missing_binary_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            D, "_run_server_command",
            lambda args, server_path="llama-server": (None, None),
        )
        assert get_server_version() is None


# ---------------------------------------------------------------------------
# Fallback when llama-server is unavailable
# ---------------------------------------------------------------------------

class TestFallback:
    def test_get_default_params_empty_help_text(self):
        assert get_default_params(help_text="") == dict(_FALLBACK_DEFAULTS)

    def test_get_default_params_missing_server(self, monkeypatch):
        monkeypatch.setattr(
            D, "_run_server_command",
            lambda args, server_path="llama-server": (None, None),
        )
        assert get_default_params() == dict(_FALLBACK_DEFAULTS)

    def test_chat_templates_missing_server(self, monkeypatch):
        monkeypatch.setattr(
            D, "_run_server_command",
            lambda args, server_path="llama-server": (None, None),
        )
        assert get_chat_templates() == []

    def test_parse_empty_help_equals_fallback(self):
        assert _parse_help_to_defaults("") == dict(_FALLBACK_DEFAULTS)


class TestUserInputParams:
    """C5: the drift-check skip set lives in core.defaults and is well-formed."""

    def test_subset_of_fallback(self):
        assert D.USER_INPUT_PARAMS <= set(_FALLBACK_DEFAULTS)

    def test_size(self):
        # 67 original inline keys, minus the 4 genuine server defaults
        # (tools, sampler_seq, cors_origins, cors_headers) exposed to the check,
        # plus log_verbosity (launcher runs llama-server at trace by default)
        assert len(D.USER_INPUT_PARAMS) == 64

    def test_exposed_keys_exist(self):
        for key in ("tools", "sampler_seq", "cors_origins", "cors_headers"):
            assert key in _FALLBACK_DEFAULTS
            assert key not in D.USER_INPUT_PARAMS

    def test_hardcoded_defaults_still_skipped(self):
        # their parsed values are launcher constants, not real help parsing
        for key in ("samplers", "cors_methods", "log_verbosity"):
            assert key in D.USER_INPUT_PARAMS
