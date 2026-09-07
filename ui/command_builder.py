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
"""
import re
import shlex

from core.defaults import _PRIO_REVERSE
from core.params_schema import PARAMS


_ARG_NEEDS_QUOTE_RE = re.compile(r'[\s"&|<>^]')


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

    def _emit(self, p, v):
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

    def build(self, v):
        args = []
        for p in PARAMS:
            args.extend(self._emit(p, v))
        return args
