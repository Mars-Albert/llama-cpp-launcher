"""Tests for llama-server command construction (ui/command_builder.py).

Covers (optimization-plan D2, with A2/A3 behavior):
- default values are not emitted;
- negatable flags emit bidirectionally (default-on -> --no-X, default-off -> --X);
- n_gpu_layers "all" -> 999, numeric, and default "auto" handling;
- extra_args shlex parsing and exception fallback;
- quote_arg display quoting for paths with spaces.
"""
import pytest

from core.defaults import _FALLBACK_DEFAULTS
from ui.command_builder import CommandBuilder, quote_arg

# (param key, negative flag, positive flag) — must match CommandBuilder
NEG_FLAG_PARAMS = [
    ("mmproj_auto", "--no-mmproj-auto", "--mmproj-auto"),
    ("mmproj_offload", "--no-mmproj-offload", "--mmproj-offload"),
    ("cache_prompt", "--no-cache-prompt", "--cache-prompt"),
    ("kv_offload", "--no-kv-offload", "--kv-offload"),
    ("kv_unified", "--no-kv-unified", "--kv-unified"),
    ("escape", "--no-escape", "--escape"),
    ("cache_idle_slots", "--no-cache-idle-slots", "--cache-idle-slots"),
    ("repack", "--no-repack", "--repack"),
    ("warmup", "--no-warmup", "--warmup"),
    ("op_offload", "--no-op-offload", "--op-offload"),
    ("spec_draft_backend_sampling", "--no-spec-draft-backend-sampling", "--spec-draft-backend-sampling"),
    ("webui", "--no-webui", "--webui"),
    ("cont_batching", "--no-cont-batching", "--cont-batching"),
    ("slots", "--no-slots", "--slots"),
    ("cors_credentials", "--no-cors-credentials", "--cors-credentials"),
    ("models_autoload", "--no-models-autoload", "--models-autoload"),
    ("jinja", "--no-jinja", "--jinja"),
    ("prefill_assistant", "--no-prefill-assistant", "--prefill-assistant"),
    # binary documents "(default: enabled)" — bool_pos would make it un-toggleable off
    ("reasoning_preserve", "--no-reasoning-preserve", "--reasoning-preserve"),
]

# Positive-logic booleans that only ever emit their positive flag (A3 must not touch these)
POSITIVE_LOGIC_PARAMS = [
    ("no_host", "--no-host"),
    ("context_shift", "--context-shift"),
    ("webui_mcp_proxy", "--webui-mcp-proxy"),
    ("skip_chat_parsing", "--skip-chat-parsing"),
]


def make_builder(key=None, value=None, **overrides):
    """Build a CommandBuilder with fallback defaults, optionally one key overridden."""
    defaults = dict(_FALLBACK_DEFAULTS)
    defaults.update(overrides)
    if key is not None:
        defaults[key] = value
    return CommandBuilder(defaults)


def emit(builder, explicit=(), **values):
    v = dict(_FALLBACK_DEFAULTS)
    v.update(values)
    return builder.build(v, explicit=set(explicit))


# ---------------------------------------------------------------------------
# Defaults are not emitted
# ---------------------------------------------------------------------------

class TestDefaultsNotEmitted:
    def test_all_defaults_produce_no_args(self):
        b = make_builder()
        assert emit(b) == []

    def test_no_negation_flags_with_default_values(self):
        b = make_builder()
        args = emit(b)
        assert not [a for a in args if "no-" in a]

    def test_default_bool_not_emitted(self):
        b = make_builder()
        args = emit(b, cache_prompt=True, webui=True, jinja=True)
        assert not [a for a in args if a in ("--cache-prompt", "--webui", "--jinja", "--no-cache-prompt", "--no-webui", "--no-jinja")]

    def test_default_int_not_emitted(self):
        b = make_builder()
        args = emit(b, batch_size=2048, ubatch_size=512)
        assert "-b" not in args and "-ub" not in args

    def test_default_string_not_emitted(self):
        b = make_builder()
        args = emit(b, flash_attn="auto", split_mode="layer")
        assert "--flash-attn" not in args and "--split-mode" not in args

    def test_n_gpu_layers_default_auto_not_emitted(self):
        b = make_builder()  # fallback default: "auto"
        args = emit(b, n_gpu_layers="auto")
        assert "-ngl" not in args


# ---------------------------------------------------------------------------
# Non-default values are emitted
# ---------------------------------------------------------------------------

class TestFlagEmission:
    def test_nondefault_int(self):
        b = make_builder()
        assert emit(b, batch_size=4096) == ["-b", "4096"]

    def test_temp_format_two_decimals(self):
        b = make_builder()
        assert emit(b, temp=1.0) == ["--temp", "1.00"]

    def test_model_path(self):
        b = make_builder()
        assert emit(b, model="C:/models/foo.gguf") == ["-m", "C:/models/foo.gguf"]

    def test_n_gpu_layers_all_becomes_999(self):
        b = make_builder()
        assert emit(b, n_gpu_layers="all") == ["-ngl", "999"]

    def test_n_gpu_layers_numeric(self):
        b = make_builder()
        assert emit(b, n_gpu_layers=99) == ["-ngl", "99"]

    def test_n_gpu_layers_invalid_string_becomes_999(self):
        b = make_builder()
        assert emit(b, n_gpu_layers="garbage") == ["-ngl", "999"]

    def test_prio_value_mapped_to_number(self):
        # builder emits the numeric prio; "normal" is 0 and equals the default
        b = make_builder()
        assert emit(b, prio="high") == ["--prio", "2"]


# ---------------------------------------------------------------------------
# Negatable flags: bidirectional emission (A3)
# ---------------------------------------------------------------------------

class TestNegFlags:
    @pytest.mark.parametrize("key, neg, pos", NEG_FLAG_PARAMS)
    def test_default_on_user_off_emits_negative(self, key, neg, pos):
        b = make_builder()  # fallback default: True for all these keys
        args = emit(b, **{key: False})
        assert neg in args
        assert pos not in args

    @pytest.mark.parametrize("key, neg, pos", NEG_FLAG_PARAMS)
    def test_default_on_user_on_emits_nothing(self, key, neg, pos):
        b = make_builder()
        args = emit(b, **{key: True})
        assert neg not in args
        assert pos not in args

    @pytest.mark.parametrize("key, neg, pos", NEG_FLAG_PARAMS)
    def test_default_off_user_on_emits_positive(self, key, neg, pos):
        # Simulate a llama-server version whose default is off (plan A3 scenario)
        b = make_builder(key, False)
        args = emit(b, **{key: True})
        assert pos in args
        assert neg not in args

    @pytest.mark.parametrize("key, neg, pos", NEG_FLAG_PARAMS)
    def test_default_off_user_off_emits_nothing(self, key, neg, pos):
        b = make_builder(key, False)
        args = emit(b, **{key: False})
        assert neg not in args
        assert pos not in args

    @pytest.mark.parametrize("key, flag", POSITIVE_LOGIC_PARAMS)
    def test_positive_logic_params_unchanged(self, key, flag):
        b = make_builder()  # fallback default: False for these
        assert emit(b, **{key: True}) == [flag]
        assert emit(b, **{key: False}) == []


# ---------------------------------------------------------------------------
# Explicit emission (2026-10 per-row toggle): the value is written verbatim,
# bypassing the default check and every inactive-value guard
# ---------------------------------------------------------------------------

class TestExplicitEmit:
    def test_default_int_written_verbatim(self):
        b = make_builder()
        assert emit(b, explicit=("port",), port=9931) == ["--port", "9931"]

    def test_zero_default_diff_pos_written(self):
        b = make_builder()  # ctx_size fallback default: 0
        assert emit(b, explicit=("ctx_size",), ctx_size=0) == ["-c", "0"]

    def test_default_float_two_decimals(self):
        b = make_builder()  # temp fallback default: 0.8
        assert emit(b, explicit=("temp",), temp=0.8) == ["--temp", "0.80"]

    def test_negative_default_diff_ge0_written(self):
        b = make_builder()  # adaptive_target fallback default: -1.0
        assert emit(b, explicit=("adaptive_target",), adaptive_target=-1.0) == [
            "--adaptive-target", "-1.00"
        ]

    def test_empty_string_written(self):
        b = make_builder()  # api_prefix fallback default: ''
        assert emit(b, explicit=("api_prefix",), api_prefix="") == [
            "--api-prefix", ""
        ]

    def test_skip_value_written(self):
        b = make_builder()  # spec_type fallback default: 'none'
        assert emit(b, explicit=("spec_type",), spec_type="none") == [
            "--spec-type", "none"
        ]

    def test_empty_join_list_written(self):
        b = make_builder()  # tools fallback default: []
        assert emit(b, explicit=("tools",), tools=[]) == ["--tools", ""]

    @pytest.mark.parametrize("key, neg, pos", NEG_FLAG_PARAMS)
    def test_negatable_explicit_on_writes_positive(self, key, neg, pos):
        b = make_builder()  # fallback default: True for all these keys
        assert emit(b, explicit=(key,), **{key: True}) == [pos]

    @pytest.mark.parametrize("key, neg, pos", NEG_FLAG_PARAMS)
    def test_negatable_explicit_off_writes_negative(self, key, neg, pos):
        b = make_builder()  # fallback default: True for all these keys
        assert emit(b, explicit=(key,), **{key: False}) == [neg]

    def test_negatable_default_off_explicit_on(self):
        b = make_builder("escape", False)
        assert emit(b, explicit=("escape",), escape=True) == ["--escape"]

    def test_positive_only_flag_explicit_on_with_default_on(self):
        b = make_builder("context_shift", True)
        assert emit(b, explicit=("context_shift",), context_shift=True) == [
            "--context-shift"
        ]

    def test_positive_only_flag_explicit_off_has_no_token(self):
        b = make_builder("context_shift", True)
        assert emit(b, explicit=("context_shift",), context_shift=False) == []

    def test_prio_explicit_default_written(self):
        b = make_builder()  # prio fallback default: 'normal'
        assert emit(b, explicit=("prio",), prio="normal") == ["--prio", "0"]

    def test_index_explicit_default_written(self):
        b = make_builder()  # mirostat fallback default: 0
        assert emit(b, explicit=("mirostat",), mirostat=0) == ["--mirostat", "0"]

    def test_ngl_explicit_auto_written_as_literal(self):
        b = make_builder()  # n_gpu_layers fallback default: 'auto'
        assert emit(b, explicit=("n_gpu_layers",), n_gpu_layers="auto") == [
            "-ngl", "auto"
        ]

    def test_ngl_explicit_all_still_999(self):
        b = make_builder()
        assert emit(b, explicit=("n_gpu_layers",), n_gpu_layers="all") == [
            "-ngl", "999"
        ]

    def test_ngl_explicit_numeric(self):
        b = make_builder()
        assert emit(b, explicit=("n_gpu_layers",), n_gpu_layers=3) == ["-ngl", "3"]

    def test_ngl_draft_explicit_auto_written_as_literal(self):
        b = make_builder()  # n_gpu_layers_draft fallback default: 'auto'
        assert emit(
            b, explicit=("n_gpu_layers_draft",), n_gpu_layers_draft="auto"
        ) == ["--n-gpu-layers-draft", "auto"]

    def test_log_verbosity_still_suppressed_when_verbose_on(self):
        b = make_builder()
        args = emit(b, explicit=("log_verbosity",),
                    verbose=True, log_verbosity=4)
        assert "--log-verbosity" not in args

    def test_log_verbosity_explicit_when_verbose_off(self):
        b = make_builder()  # log_verbosity fallback default: 4
        assert emit(b, explicit=("log_verbosity",), log_verbosity=4) == [
            "--log-verbosity", "4"
        ]

    def test_does_not_affect_truthy_or_extra(self):
        b = make_builder()
        assert emit(b, explicit=("model",), model="") == []
        assert emit(b, explicit=("extra_args",), extra_args="") == []

    def test_non_explicit_params_untouched(self):
        b = make_builder()  # host (server row 0) precedes port (row 1)
        args = emit(b, explicit=("port",), host="0.0.0.0", port=9931)
        assert args == ["--host", "0.0.0.0", "--port", "9931"]


# ---------------------------------------------------------------------------
# extra_args
# ---------------------------------------------------------------------------

class TestExtraArgs:
    def test_shlex_split(self):
        b = make_builder()
        assert emit(b, extra_args="--lora a.gguf --lora-scaled b.gguf 0.5") == [
            "--lora", "a.gguf", "--lora-scaled", "b.gguf", "0.5"
        ]

    def test_empty_extra_args(self):
        b = make_builder()
        assert emit(b, extra_args="   ") == []

    def test_unbalanced_quote_falls_back_to_plain_split(self):
        b = make_builder()
        args = emit(b, extra_args='--lora "a.gguf')
        assert args == ["--lora", '"a.gguf']


# ---------------------------------------------------------------------------
# quote_arg display quoting (A2)
# ---------------------------------------------------------------------------

class TestQuoteArg:
    def test_no_whitespace_unchanged(self):
        assert quote_arg("-m") == "-m"
        assert quote_arg("999") == "999"
        assert quote_arg("C:/models/foo.gguf") == "C:/models/foo.gguf"

    def test_spaces_quoted(self):
        assert quote_arg("C:/My Models/foo.gguf") == '"C:/My Models/foo.gguf"'

    def test_tab_quoted(self):
        assert quote_arg("a\tb") == '"a\tb"'

    def test_shell_metacharacters_quoted(self):
        for ch in ("&", "|", "<", ">", "^"):
            assert quote_arg(f"x{ch}y").startswith('"') and quote_arg(f"x{ch}y").endswith('"')

    def test_empty_and_none_quoted(self):
        assert quote_arg("") == '""'
        assert quote_arg(None) == '""'

    def test_embedded_double_quote_escaped(self):
        assert quote_arg('a"b') == '"a\\"b"'

    def test_full_command_line(self):
        args = ["-m", "C:/My Models/model.gguf", "--n-gpu-layers", "999"]
        cmd = "llama-server " + " ".join(quote_arg(a) for a in args)
        assert cmd == 'llama-server -m "C:/My Models/model.gguf" --n-gpu-layers 999'
