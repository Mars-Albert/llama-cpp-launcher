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


from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication


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
