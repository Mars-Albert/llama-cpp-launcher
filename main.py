import gc
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _get_work_dir():
    """Return the directory containing the exe in frozen mode, otherwise the script directory."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo, QFontMetrics, QIcon
from PyQt6.QtWidgets import QApplication

# The app-wide base font comes from the **bundled Inter TTF** first
# (assets/fonts/Inter-Regular.ttf, OFL license), registered at startup via
# QFontDatabase.addApplicationFont. The TTF's family name is NOT "Inter" but
# the private "LlamaCPPLauncher" (name table renamed in-repo; it is still
# the Inter 4.001 face). Why: the name "Inter" is squat-able — the report
# machine's font store (2026-09/10 user reports) carries a third-party
# "font beautification" file registered under several common family names at
# once, with scrambled Latin DIGIT glyphs (0→O,
# 4→×, 5→6, 8→≠, 9→女; letters and CJK stay intact). While that file
# claimed the name "Inter", Qt's per-glyph resolution of the ambiguous
# family pulled some digits from our bundled file (healthy) and others from
# the fake (mojibake) — spinbox values rendered ×O/≠O≠/I while
# buttons/labels looked fine, and the digit-ADVANCE probe below cannot catch
# such narrow-glyph swaps (O/×/≠ advance like normal digits). A private
# family name cannot be plausibly squatted, so the bundled file resolves
# unambiguously and digits/Latin always render from our file. History: a
# static family pin (Segoe UI, v1.8.3) did not help — the broken face IS
# what those names resolve to there; the first bundled-font fix (family
# still "Inter") was still collision-prone (reproduced 2026-10: fake
# "Inter" + bundled Inter → per-glyph mixed mojibake).
# CJK characters (absent from Inter) fall back per character through the
# family list to a system CJK font (CJK rendered fine on the report
# machine). As a second layer every candidate is still probed — in a
# healthy face each ASCII digit advances ~0.3–0.6em, a face whose digit
# code points map to wide CJK/symbol glyphs advances ~1em — and every
# probe result is logged to launcher.log (logger "font") so a report
# machine can be diagnosed from its log alone.
APP_FONT_CANDIDATES = ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Arial", "Tahoma", "Verdana"]
_FONT_CJK_FALLBACKS = ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial"]
_DIGIT_PROBE = "0123456789"
_DIGIT_MAX_ADVANCE_EM = 0.75
_BUNDLED_FONT = os.path.join("assets", "fonts", "Inter-Regular.ttf")


def _bundled_font_path() -> str:
    """Path of the bundled UI font (frozen: extracted <_MEIPASS>/assets)."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, _BUNDLED_FONT)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _BUNDLED_FONT)


def _load_bundled_font() -> str:
    """Register the bundled UI font (Inter, private family name
    "LlamaCPPLauncher" — see the module comment); return its family name
    or ""."""
    log = logging.getLogger("font")
    path = _bundled_font_path()
    if not os.path.exists(path):
        log.warning("bundled font missing: %s — falling back to system fonts", path)
        return ""
    fid = QFontDatabase.addApplicationFont(path)
    if fid < 0:
        log.warning("bundled font failed to load: %s", path)
        return ""
    fams = QFontDatabase.applicationFontFamilies(fid)
    log.info("bundled font %r loaded (id=%d, families=%s)",
             os.path.basename(path), fid, fams)
    return fams[0] if fams else ""


def _font_digits_healthy(font: QFont) -> bool:
    """True when every ASCII digit advances like a digit (not a wide glyph)."""
    fm = QFontMetrics(font)
    em = max(1, fm.height())
    return all(fm.horizontalAdvance(ch) / em < _DIGIT_MAX_ADVANCE_EM
               for ch in _DIGIT_PROBE)


_AUTO = object()


def _pick_healthy_font(app: QApplication,
                       healthy=_font_digits_healthy,
                       bundled_family=_AUTO) -> QFont:
    """Base font for the whole app: bundled face (private family name) first, then the probed
    system chain. `bundled_family` accepts an explicit name/"" for tests
    (``_AUTO`` = load the bundled font, the default in the app)."""
    log = logging.getLogger("font")
    if bundled_family is _AUTO:
        bundled_family = _load_bundled_font()
    size = app.font().pointSize()
    if size <= 0:
        size = 9
    try:
        installed = set(QFontDatabase.families())
    except Exception:  # offscreen/no font DB — log "?" instead of crashing
        installed = set()
    candidates = []
    if bundled_family:
        candidates.append(bundled_family)
    for fam in APP_FONT_CANDIDATES:
        if fam != bundled_family and fam not in candidates:
            candidates.append(fam)
    for fam in candidates:
        f = QFont(fam, size)
        resolved = QFontInfo(f).family()
        fm = QFontMetrics(f)
        em = max(1, fm.height())
        widths = [fm.horizontalAdvance(ch) / em for ch in _DIGIT_PROBE]
        ok = healthy(f)
        log.info(
            "font candidate %r installed=%s resolved=%r pointsize=%d "
            "digit-advance(em)=%s -> %s",
            fam, fam in installed if installed else "?", resolved, size,
            " ".join(f"{w:.2f}" for w in widths),
            "OK" if ok else "REJECTED (broken digit glyphs?)")
        if ok:
            f.setFamilies(list(dict.fromkeys([fam] + _FONT_CJK_FALLBACKS)))
            log.info("font selected: %r (resolved %r, size %d)", fam, resolved, size)
            return f
    log.warning(
        "font: no healthy candidate (all digit probes abnormal); "
        "falling back to %r anyway", candidates[0])
    f = QFont(candidates[0], size)
    f.setFamilies(list(dict.fromkeys([candidates[0]] + _FONT_CJK_FALLBACKS)))
    return f


def _app_icon_path():
    """Path of the bundled window icon (assets/icon.ico).

    The spec's `icon=` only writes the EXE's PE resource (file-explorer /
    shortcut / taskbar-fallback icon); Qt's *window* title-bar icon is set
    separately at runtime, so the same ico is also bundled as a data file
    (see llama_cpp_launcher.spec datas) and applied via setWindowIcon().
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'assets', 'icon.ico')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'icon.ico')


def _apply_app_icon(app: QApplication):
    """Set the app-wide window icon (title bar + all top-level dialogs)."""
    icon_path = _app_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
from ui.main_window import MainWindow
from core.defaults import _FALLBACK_DEFAULTS
from core.config import CONFIG_DIR, load_language
from core.i18n import set_language


def _setup_logging():
    """C7: write module logs to a rotating file.

    The exe is packaged console-less (PyInstaller console=False), so logger
    output goes nowhere by default — without this, every logger.warning in
    core/ and ui/ is invisible and there is no trace for troubleshooting.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            CONFIG_DIR / "launcher.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    except OSError:
        handler = logging.StreamHandler()  # unwritable config dir: at least stderr
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _log_uncaught(exc_type, exc_value, exc_tb):
    """Route uncaught exceptions to the log file.

    Exceptions raised inside Qt event handlers / slots are printed to
    stderr and *swallowed by the event loop* — with a console-less exe
    they would be invisible. This hook writes them to launcher.log so a
    misbehaving close path (or any slot) leaves a trace.
    """
    logging.getLogger("uncaught").exception(
        "uncaught %s: %s", exc_type.__name__, exc_value,
        exc_info=(exc_type, exc_value, exc_tb))


def _log_exit_state(app: QApplication):
    """Log what the app looked like when exec() returned.

    quitOnLastWindowClosed fires only when no WA_QuitOnClose top-level
    window is VISIBLE any more — so a lingering visible window (or a
    still-running thread) is exactly what keeps a "closed" app alive.

    Must never raise: this is an exit diagnostic, and a failure here
    would turn a clean shutdown into an unhandled-exception dialog
    (PyQt6 6.11 does not expose QThread.allThreads(), which crashed the
    old implementation on every exit — threads are enumerated from the
    GC instead, and the whole body is guarded).
    """
    try:
        from PyQt6.QtCore import QThread
        visible = [
            f"{type(w).__name__}#{w.objectName() or '?'}"
            for w in app.topLevelWidgets()
            if w.isVisible()
        ]
        threads, seen = [], set()
        for obj in gc.get_objects():
            if not isinstance(obj, QThread):
                continue
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            try:
                if obj.isCurrentThread() or not obj.isRunning():
                    continue
            except RuntimeError:  # C++ part already destroyed
                continue
            threads.append(obj.objectName() or type(obj).__name__)
        logging.getLogger("shutdown").info(
            "exec returned; visible top-levels=%s running threads=%s",
            visible or "none", threads or "none")
    except Exception:
        logging.getLogger("shutdown").exception("exit-state logging failed")


def main():
    _setup_logging()
    set_language(load_language())
    sys.excepthook = _log_uncaught

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Base font before any widget is built (see the APP_FONT_CANDIDATES
    # comment): the bundled Inter TTF (private family name "LlamaCPPLauncher"
    # — immune to name-squatted faces in the machine's font store) is the
    # primary face, and every candidate is probed + logged to launcher.log
    # (logger "font") for diagnostics.
    app.setFont(_pick_healthy_font(app))
    app.aboutToQuit.connect(
        lambda: logging.getLogger("shutdown").info("aboutToQuit"))
    # Window title-bar icon: PyInstaller's spec icon only covers the EXE
    # resource, not Qt's runtime window icon — apply it app-wide.
    _apply_app_icon(app)
    # The window is shown immediately with fallback defaults; the live
    # llama-server --help / --version results are fetched on a background
    # thread and merged in asynchronously (plan A10).
    window = MainWindow(
        work_dir=_get_work_dir(),
        defaults=dict(_FALLBACK_DEFAULTS),
    )
    window.show()
    rc = app.exec()
    _log_exit_state(app)
    sys.exit(rc)


if __name__ == "__main__":
    main()
