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


from PyQt6.QtGui import QFont, QFontInfo, QFontMetrics, QIcon
from PyQt6.QtWidgets import QApplication

# The app-wide base font is picked at runtime from a list of
# guaranteed-present Windows families (Segoe UI ships with every Windows
# Vista+ install) instead of inheriting whatever the system's default UI
# font resolves to. On some machines a font face with the right family name
# is corrupted or substituted and scrambles the Latin DIGIT glyphs —
# 0→O, 4→×, 5→6, 8→≠, 9→女 — while letters stay normal, so spinbox values
# rendered as mojibake (reported 2026-09, still broken on v1.8.3 where the
# family was pinned statically: the broken face IS what the name resolves
# to on that machine — a third-party "font beautification" file apparently
# registers under several family names at once, shadowing the real faces,
# while the BOLD face and other files — Consolas preview, Segoe UI Symbol —
# stay healthy). Each candidate is therefore probed: in a healthy
# face the ASCII digits advance ~0.3–0.6em per glyph, while a face whose
# digit code points map to CJK/symbol glyphs advances ~1em for them.
# The probe rejects broken faces; every probe result (installed?, resolved
# family, per-digit advance) is logged to launcher.log (logger "font") so
# a report machine can be diagnosed from its log alone.
APP_FONT_CANDIDATES = ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Arial", "Tahoma", "Verdana"]
_DIGIT_PROBE = "0123456789"
_DIGIT_MAX_ADVANCE_EM = 0.75


def _font_digits_healthy(font: QFont) -> bool:
    """True when every ASCII digit advances like a digit (not a wide glyph)."""
    fm = QFontMetrics(font)
    em = max(1, fm.height())
    return all(fm.horizontalAdvance(ch) / em < _DIGIT_MAX_ADVANCE_EM
               for ch in _DIGIT_PROBE)


def _pick_healthy_font(app: QApplication,
                       healthy=_font_digits_healthy) -> QFont:
    """Base font for the whole app: first candidate with healthy digits."""
    log = logging.getLogger("font")
    size = app.font().pointSize()
    if size <= 0:
        size = 9
    try:
        from PyQt6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
    except Exception:  # offscreen/no font DB — log "?" instead of crashing
        installed = set()
    for fam in APP_FONT_CANDIDATES:
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
            f.setFamilies(list(dict.fromkeys(
                [fam] + APP_FONT_CANDIDATES)))  # CJK fallback chain
            log.info("font selected: %r (resolved %r, size %d)", fam, resolved, size)
            return f
    log.warning(
        "font: no healthy candidate (all digit probes abnormal); "
        "falling back to %r anyway", APP_FONT_CANDIDATES[0])
    f = QFont(APP_FONT_CANDIDATES[0], size)
    f.setFamilies(list(dict.fromkeys([APP_FONT_CANDIDATES[0]] + APP_FONT_CANDIDATES)))
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
    # Pin the base font family before any widget is built (see the
    # APP_FONT_CANDIDATES comment): a broken or substituted font face must
    # not decide how the digits render. The picker probes each candidate's
    # digit glyphs and logs everything to launcher.log (logger "font").
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
