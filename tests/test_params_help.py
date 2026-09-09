# -*- coding: utf-8 -*-
"""Integrity tests for core.params_help (the "?" parameter help cards).

* Every explanation key must be a real params_schema key.
* Every CJK explanation needs an _EN entry (the UI passes the literal
  through t(); unlike schema strings this is not visible to an AST scan,
  so it is pinned explicitly here).
"""
import re

from core.i18n import _EN
from core.params_help import HELP_TEXTS, has_help, help_text
from core.params_schema import PARAMS_BY_KEY

_CJK = re.compile(r"[\u4e00-\u9fff]")


def test_help_keys_exist_in_schema():
    unknown = [k for k in HELP_TEXTS if k not in PARAMS_BY_KEY]
    assert not unknown, f"unknown param keys: {unknown}"


def test_help_i18n_coverage():
    missing = [s for s in HELP_TEXTS.values()
               if _CJK.search(s) and s not in _EN]
    assert not missing, f"missing _EN entries: {missing[:5]}"


def test_accessors():
    assert has_help("temp")
    assert help_text("temp")
    assert help_text("nonexistent_key") == ""
    assert not has_help("nonexistent_key")


def test_basic_panel_keys_covered():
    """Every parameter exposed in the basic panel must have an explanation
    (basic_panel inserts a '?' button for each of these)."""
    basic_keys = [
        "model", "mmproj", "n_gpu_layers", "ctx_size",
        "temp", "top_p", "top_k", "min_p", "repeat_penalty",
        "host", "port", "parallel", "webui", "verbose",
        "flash_attn", "reasoning", "split_mode", "spec_type", "draft_max",
    ]
    missing = [k for k in basic_keys if not has_help(k)]
    assert not missing, f"basic panel params without help: {missing}"
