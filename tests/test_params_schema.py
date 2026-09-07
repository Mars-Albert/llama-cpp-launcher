"""C1: integrity tests for core.params_schema.

The schema is the single source of truth for parameter state (C3):
defaults, CLI emission (ui/command_builder), UI construction
(ui/advanced_panel) and i18n coverage all derive from it. These tests
pin down the invariants that keep the four consumers in sync.
"""
import re

from core import defaults
from core.i18n import _EN
from core.params_schema import (
    PARAMS,
    PARAMS_BY_KEY,
    TAB_ORDER,
    UI_PARAMS,
    fallback_defaults,
    help_flag_maps,
    schema_i18n_strings,
    tab_params,
)

_CJK = re.compile(r"[\u4e00-\u9fff]")

VALID_EMIT = {
    "none", "extra", "truthy", "diff", "diff_nonempty", "diff_pos",
    "diff_skip", "diff_ge0", "diff_join", "bool_pos", "bool_neg",
    "prio", "index", "ngl", "ngl_draft",
}
VALID_WIDGET = {
    "spin", "check", "text", "dspin", "combo", "file", "combo_edit",
    "mtext", "list", "password", "combo_index", "dir", "dir_text",
    "checklist",
}
# Emit modes that attach a value argument to the flag.
_VALUE_EMIT = {"diff", "diff_pos", "diff_ge0", "diff_join", "index",
               "ngl", "ngl_draft", "prio", "truthy", "diff_nonempty",
               "diff_skip"}


def test_param_count_and_keys():
    assert len(PARAMS) == 226
    assert set(PARAMS_BY_KEY) == set(p.key for p in PARAMS)
    # Single source of truth: schema keys == fallback default keys.
    assert set(PARAMS_BY_KEY) == set(defaults._FALLBACK_DEFAULTS)


def test_ui_params():
    assert len(UI_PARAMS) == 225
    assert [p.key for p in UI_PARAMS] == [p.key for p in PARAMS
                                          if p.wattr is not None]
    # wattr names are unique.
    attrs = [p.wattr for p in UI_PARAMS]
    assert len(attrs) == len(set(attrs))


def test_emit_and_widget_fields():
    for p in PARAMS:
        assert p.emit in VALID_EMIT, p.key
        if p.wattr is not None:
            assert p.widget in VALID_WIDGET, p.key
        if p.emit in ("none", "extra"):
            continue
        assert p.flag, f"{p.key}: emit={p.emit} needs a flag"
        if p.emit == "bool_neg":
            pos, neg = p.flag
            assert pos.startswith("--") and neg.startswith("--no-"), p.key
    # Flags (the --help alias list) are only needed for params that llama-server
    # documents in --help; model/mmproj/lora/cv/tools are positional or
    # multi-file args with no --help entry.
    s_value, s_flag, s_neg = help_flag_maps()
    parsed = set(s_value) | set(s_flag) | set(s_neg)
    for p in PARAMS:
        if p.key in parsed:
            assert p.flags, f"{p.key}: --help-parsed but no flag aliases"
        if p.emit in _VALUE_EMIT and p.key in parsed:
            assert p.flags[0] == p.flag or p.flag in p.flags, p.key


def test_rows_unique_and_contiguous_per_tab():
    # Rows reserved for non-parameter rows (E8 GPU-info label and the
    # draft-model section label, both on the gpu tab).
    reserved = {"gpu": {5, 38}}
    seen_tabs = set()
    for tab in TAB_ORDER:
        rows = [p.row for p in tab_params(tab)]
        assert len(rows) == len(set(rows)), tab
        expected = [r for r in range(max(rows) + 1)
                    if r not in reserved.get(tab, ())]
        assert rows == expected, tab
        seen_tabs.add(tab)
    for p in PARAMS:
        if p.wattr is not None:
            assert p.tab in seen_tabs, p.key


def test_flag_maps_match_legacy():
    """help_flag_maps() must reproduce the legacy --help parsing maps."""
    s_value, s_flag, s_neg = help_flag_maps()
    assert set(s_value) == set(defaults._VALUE_FLAG_MAP)
    assert set(s_flag) == set(defaults._FLAG_MAP)
    assert set(s_neg) == set(defaults._NEG_FLAG_MAP)
    for key, (flags, parser) in defaults._VALUE_FLAG_MAP.items():
        schema_flags, parser_name = s_value[key]
        assert list(schema_flags) == list(flags), key
        assert defaults._PARSER_BY_NAME[parser_name] is parser, key
    for key, flags in defaults._FLAG_MAP.items():
        assert list(s_flag[key]) == list(flags), key
    for key, flags in defaults._NEG_FLAG_MAP.items():
        assert list(s_neg[key]) == list(flags), key


def test_fallback_defaults_roundtrip():
    assert fallback_defaults() == defaults._FALLBACK_DEFAULTS
    # Defaults must be JSON-serializable (preset saving relies on it).
    import json
    json.dumps(fallback_defaults(), ensure_ascii=False)


def test_schema_i18n_coverage():
    """Every schema string containing CJK needs an _EN entry (D4/C1)."""
    missing = [s for s in schema_i18n_strings()
               if _CJK.search(s) and s not in _EN]
    assert not missing, f"missing _EN entries: {missing}"


def test_emit_order_stable():
    """PARAMS order IS the CLI emission order; pin the first/last few."""
    keys = [p.key for p in PARAMS]
    assert keys[0] == "model"
    assert keys[-1] == "extra_args"
    assert keys.count("model") == 1
    assert "n_gpu_layers" in keys and "prio_batch" in keys
