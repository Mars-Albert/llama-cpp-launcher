"""Pure llama-server command line construction (no Qt dependency).

Extracted from ui/main_window.py (optimization-plan C2). CommandBuilder holds
the live-parsed defaults and emits a CLI flag only when a parameter differs
from its default (see is_default / neg_flag).

C1: the per-parameter emission is driven by the single parameter schema
(core/params_schema.py). Each Param carries its emit mode, value format, and
CLI flag(s); build() walks the schema in emit order (model -> context ->
sampling -> performance -> server -> chat -> advanced -> extra) and dispatches
to the matching emitter. The emit modes mirror the original per-category
build_* methods one-to-one:

  truthy       file-like params: emit flag+value when the value is set
               (no default comparison), lists joined with ","
  diff         emit flag+formatted value when different from the default
  diff_nonempty   like diff, but additionally require a non-empty value
  diff_pos     integer params: emit only when the value is positive
  diff_skip    like diff_nonempty, but also skip "inactive" values
               (e.g. spec_type "none", numa "disable")
  diff_ge0     float params: emit when the value is >= 0 (adaptive_*)
  diff_join    list params: emit flag+joined when different and non-empty
  bool_pos     positive-only flag: emit the flag when different and true
  bool_neg     negatable flag: bidirectional emission via neg_flag()
  prio         priority names mapped to numeric values via _PRIO_REVERSE
  index        integer index values (mirostat, log verbosity)
  ngl          n_gpu_layers: "all" -> 999, numeric pass-through, bad -> 999
  ngl_draft    n_gpu_layers_draft: like ngl but bad values emit nothing
  extra        extra_args: free-form string, shlex-split
  none         schema-only params with no CLI flag (override_tensor_draft)

Explicit emission (2026-10, per-row toggle): build(v, explicit=keys) writes the
listed keys' values verbatim — the default check and every inactive-value
guard are bypassed (see _emit_explicit / explicit_eligible).
"""
import re
import shlex

from core.defaults import _PRIO_REVERSE
from core.params_schema import PARAMS

_ARG_NEEDS_QUOTE_RE = re.compile(r'[\s"&|<>^]')


# -- Explicit-output toggle eligibility (2026-10) ------------------------

def explicit_eligible(p) -> bool:
    """Whether a param row gets a per-row explicit-output toggle.

    Explicit emission must be able to change the command, otherwise the
    toggle is a dead control: truthy/extra/none emit every set value
    already (nothing is ever swallowed), and a positive-only flag with
    an off default emits whenever it is on and has no "off" token that
    could be explicit."""
    if p.emit in ("diff", "diff_nonempty", "diff_pos", "diff_ge0",
                  "diff_skip", "diff_join", "bool_neg", "prio", "index",
                  "ngl", "ngl_draft"):
        return True
    if p.emit == "bool_pos":
        return bool(p.default)
    return False


# Keys the per-row toggle may target (UI params only). MainWindow
# sanitizes persisted explicit-output sets against this in _restore_ui_state.
EXPLICIT_ELIGIBLE_KEYS = frozenset(
    p.key for p in PARAMS if p.wattr is not None and explicit_eligible(p))


def quote_arg(a) -> str:
    """Quote a single argument for display/copy so the pasted command runs in a shell.

    Only used for display text, clipboard copy, and log rendering.
    QProcess.setArguments passes arguments individually and must NOT be quoted.
    """
    s = "" if a is None else str(a)
    if not s or _ARG_NEEDS_QUOTE_RE.search(s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


class CommandBuilder:
    """Builds llama-server CLI arguments from a params dict."""

    def __init__(self, defaults):
        self.defaults = defaults

    def is_default(self, key, v):
        if key not in v:
            return True
        if key not in self.defaults:
            return False
        return v[key] == self.defaults[key]

    def neg_flag(self, v, key, neg, pos):
        """Bidirectional emission for a negatable boolean param. Returns the flags to append.

        - default on  + user off -> [neg]  (e.g. --no-mmap)
        - default off + user on  -> [pos]  (e.g. --mmap)
        - matches default (or default unknown) -> []
        """
        if self.is_default(key, v):
            return []
        if not v.get(key, True):
            return [neg]
        if self.defaults.get(key) is False:
            return [pos]
        return []

    # -- C1: schema-driven emission -------------------------------------

    @staticmethod
    def _format_value(p, value):
        """Render a value according to the schema's fmt field."""
        if p.fmt == "f2":
            return f"{value:.2f}"
        if p.fmt == "join":
            return ",".join(value)
        if p.fmt == "int":
            return str(value)
        return value

    def _emit(self, p, v, explicit=False):
        """Emit the CLI arguments for one schema param. Returns a list."""
        key = p.key
        val = v.get(key)
        mode = p.emit

        if mode == "none":
            return []

        if mode == "extra":
            extra = (val or "").strip()
            if not extra:
                return []
            try:
                return shlex.split(extra)
            except ValueError:
                return extra.split()

        if mode == "truthy":
            if not val:
                return []
            if isinstance(val, list):
                return [p.flag, ",".join(val)]
            return [p.flag, val]

        # Explicit emission (per-row toggle, 2026-10): write the value
        # verbatim — no default check, no inactive-value guard below.
        if explicit:
            return self._emit_explicit(p, val)

        # All modes except bool_neg only emit when the value differs from
        # the live-parsed default (a missing key counts as default).
        if mode != "bool_neg" and self.is_default(key, v):
            return []

        if mode == "diff":
            return [p.flag, self._format_value(p, v[key])]

        if mode == "diff_nonempty":
            if not val:
                return []
            return [p.flag, val]

        if mode == "diff_pos":
            value = v.get(key, 0)
            if not (value and value > 0):
                return []
            return [p.flag, str(value)]

        if mode == "diff_skip":
            if not val or val in p.skip_values:
                return []
            return [p.flag, val]

        if mode == "diff_ge0":
            value = v.get(key, -1.0)
            if value is None or value < 0:
                return []
            return [p.flag, f"{value:.2f}"]

        if mode == "diff_join":
            if not val:
                return []
            return [p.flag, ",".join(val)]

        if mode == "bool_pos":
            if not v.get(key):
                return []
            return [p.flag]

        if mode == "bool_neg":
            pos, neg = p.flag
            return self.neg_flag(v, key, neg, pos)

        if mode == "prio":
            return [p.flag, str(_PRIO_REVERSE.get(str(v.get(key, "normal")), 0))]

        if mode == "index":
            return [p.flag, str(v[key])]

        if mode in ("ngl", "ngl_draft"):
            ngl = v.get(key, "auto")
            if not ngl:
                return []
            if ngl == "all":
                return [p.flag, "999"]
            try:
                return [p.flag, str(int(ngl))]
            except (ValueError, TypeError):
                # ngl (main model) falls back to 999; the draft variant
                # silently omits the flag.
                return [p.flag, "999"] if mode == "ngl" else []

        raise ValueError(f"unknown emit mode: {mode!r} (key={key})")

    def _emit_explicit(self, p, val):
        """Explicit emission (per-row toggle): write the value verbatim.

        No default-equality check, no inactive-value guard — 0, -1,
        'none' and even the empty string are written (the command line
        is meant to be fully explicit, user decision 2026-10). Booleans
        still can only be present or absent: a explicit-off positive-only
        flag has no token to write."""
        mode = p.emit
        if mode == "bool_neg":
            pos, neg = p.flag
            return [pos if val else neg]
        if mode == "bool_pos":
            return [p.flag] if val else []
        if mode in ("ngl", "ngl_draft"):
            # "all" keeps the 999 mapping; "auto" and numbers pass
            # through as literals (the binary accepts 'auto'/'all').
            if val == "all":
                return [p.flag, "999"]
            return [p.flag, "" if val is None else str(val)]
        if mode == "prio":
            return [p.flag, str(_PRIO_REVERSE.get(str(val), 0))]
        if mode == "index":
            return [p.flag, str(val)]
        if p.fmt == "f2":
            return [p.flag, f"{val:.2f}"]
        if p.fmt == "join":
            return [p.flag, ",".join(val)]
        if p.fmt == "int":
            return [p.flag, str(val)]
        return [p.flag, val]

    def build(self, v, explicit=frozenset()):
        args = []
        # --verbose (schema order: row 5) is emitted BEFORE --log-verbosity
        # (row 6) and forces verbosity to INT_MAX; emitting --log-verbosity
        # afterwards would silently downgrade the user's "log everything"
        # request, so skip it whenever verbose is on (explicit included).
        verbose_on = bool(v.get("verbose"))
        for p in PARAMS:
            if p.key == "log_verbosity" and verbose_on:
                continue
            args.extend(self._emit(p, v, p.key in explicit))
        return args
