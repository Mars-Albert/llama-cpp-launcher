# -*- coding: utf-8 -*-
"""E10: user-configurable ⚡ 快捷开关 (quick toggles).

The quick-toggles group in BasicPanel is schema-driven: the user picks the
params to show (QuickParamsDialog) and the group rebuilds its widgets from
core.params_schema. Values flow through the usual get_values() /
set_values() contract, so presets / undo / command building stay compatible
without changes.

Pool rules (human-friendly bounds):
  * only single-line widget kinds (check / combo / combo_index / spin /
    dspin; combo_edit only with static items) — no file/dir/mtext/list rows
  * params owned by the basic panel's other groups (model / sampling /
    server) are excluded: every key keeps exactly one owning widget, so
    editing a value in one place can never desync another.
"""
import re

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QWidget,
)

from core.i18n import t
from core.params_schema import PARAMS

#: The five toggles shown before the user customizes anything (E10 baseline
#: = the pre-E10 hardcoded set, so existing users see no change).
QUICK_DEFAULT_KEYS = ("flash_attn", "reasoning", "split_mode", "spec_type", "draft_max")

#: Params rendered by the basic panel's other groups (model / sampling /
#: server). Never offered as quick toggles — one widget per key.
BASIC_OWNED_KEYS = frozenset({
    "model", "mmproj", "n_gpu_layers", "ctx_size",
    "temp", "top_p", "top_k", "min_p", "repeat_penalty",
    "host", "port", "parallel", "webui", "verbose",
})

_QUICK_KINDS = ("check", "combo", "combo_index", "spin", "dspin")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_FLAG_RE = re.compile(r"\s*\(--[^)]*\)")


def _T(s: str) -> str:
    """Translate a schema string at build/retranslate time (C1 pattern)."""
    return t(s) if _CJK_RE.search(s) else s


def quick_eligible():
    """All schema params allowed in the quick-toggles group (schema order)."""
    out = []
    for p in PARAMS:
        kind = p.widget
        if kind in _QUICK_KINDS:
            ok = True
        elif kind == "combo_edit":
            ok = p.items is not None  # static items only (skip chat_template)
        else:
            ok = False
        if ok and p.key not in BASIC_OWNED_KEYS:
            out.append(p)
    return out


def quick_pool_keys():
    return {p.key for p in quick_eligible()}


def sanitize_quick_keys(raw, default=QUICK_DEFAULT_KEYS):
    """Validate an ordered key list (e.g. from settings.json): drop unknown
    keys / non-strings / duplicates, keep order. Empty result -> default set.
    (llama.cpp version drift can invalidate stored keys.)"""
    pool = quick_pool_keys()
    seen, out = set(), []
    for k in (raw or []):
        if isinstance(k, str) and k in pool and k not in seen:
            seen.add(k)
            out.append(k)
    if not out:
        out = [k for k in default if k in pool]
    return out


def quick_short_label(p) -> str:
    """Chinese-source label without the CLI-flag suffix:
    'Flash Attention (--flash-attn):' -> 'Flash Attention'."""
    label = p.label or p.key
    return _FLAG_RE.sub("", label).rstrip(":：").strip()


def quick_label_text(p) -> str:
    """Translated short label (t() applied at build/retranslate time)."""
    return t(quick_short_label(p))


def kind_display_name(kind: str) -> str:
    return {
        "check": t("开关"),
        "combo": t("下拉"),
        "combo_index": t("下拉"),
        "combo_edit": t("下拉(可输入)"),
        "spin": t("整数"),
        "dspin": t("小数"),
    }[kind]


# ---------------------------------------------------------------------------
# Compact widget factory (mirrors AdvancedPanel._build_param_row semantics)
# ---------------------------------------------------------------------------

def _set_combo_width(w: QComboBox):
    """Size to the longest item (with a sane floor/ceiling for the row)."""
    longest = max((len(w.itemText(i)) for i in range(w.count())), default=0)
    w.setFixedWidth(max(90, min(170, longest * 7 + 34)))


def build_quick_widget(p) -> QWidget:
    """One compact control for a quick-toggle slot, initialized from the
    schema default (live defaults / presets arrive later via set_values)."""
    kind = p.widget
    if kind == "check":
        w = QCheckBox(quick_label_text(p))
        if p.default:
            w.setChecked(True)
    elif kind in ("combo", "combo_index"):
        w = QComboBox()
        w.addItems([_T(i) for i in (p.items or ())])
        if kind == "combo" and p.curtext:
            w.setCurrentText(p.curtext)
        if kind == "combo_index" and p.curidx is not None:
            w.setCurrentIndex(p.curidx)
        _set_combo_width(w)
    elif kind == "combo_edit":
        w = QComboBox()
        w.setEditable(True)
        w.addItems([_T(i) for i in (p.items or ())])
        if p.curtext:
            w.setCurrentText(p.curtext)
        _set_combo_width(w)
    elif kind == "spin":
        w = QSpinBox()
        w.setRange(p.min if p.min is not None else 0,
                   p.max if p.max is not None else 999999)
        if p.default:
            w.setValue(p.default)
        w.setFixedWidth(72)
    elif kind == "dspin":
        w = QDoubleSpinBox()
        w.setRange(p.min if p.min is not None else 0.0,
                   p.max if p.max is not None else 999999.0)
        if p.step:
            w.setSingleStep(p.step)
        if p.default:
            w.setValue(float(p.default))
        w.setFixedWidth(84)
    else:
        raise ValueError(f"unsupported quick-toggle widget kind: {kind!r}")
    if p.tooltip:
        w.setToolTip(t(p.tooltip))
    return w


def read_quick(p, w):
    """Read the slot value back into params-dict semantics (same as
    AdvancedPanel._read_param for these kinds)."""
    kind = p.widget
    if kind == "check":
        return w.isChecked()
    if kind == "combo_index":
        return w.currentIndex()
    if kind in ("combo", "combo_edit"):
        return w.currentText()
    if kind in ("spin", "dspin"):
        return w.value()
    raise ValueError(kind)


def write_quick(p, w, val):
    """Apply a params-dict value to the slot. Raises TypeError/ValueError on
    corrupt values — the caller (set_values) skips bad keys per-key."""
    kind = p.widget
    if kind == "check":
        w.setChecked(bool(val))
    elif kind == "combo_index":
        w.setCurrentIndex(int(val))
    elif kind == "combo":
        w.setCurrentText(str(val))
    elif kind == "combo_edit":
        val = str(val)
        idx = w.findText(val)
        if idx >= 0:
            w.setCurrentIndex(idx)
        else:
            w.setEditText(val)
    elif kind == "spin":
        w.setValue(int(val))
    elif kind == "dspin":
        w.setValue(float(val))
    else:
        raise ValueError(kind)


# NOTE: a Python QLayout subclass (flow layout) was the original wrapping
# strategy, but in the pinned PyQt6 6.11 build any Python QLayout subclass
# crashes the process at the first layout pass (QLayoutItem.setGeometry
# from Python kills the process, silently — verified with a minimal probe).
# BasicPanel therefore arranges the quick-toggle slots in a plain C++
# QGridLayout and recomputes the column count on resize.
