import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _get_work_dir():
    """Return the directory containing the exe in frozen mode, otherwise the script directory."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


from PyQt6.QtWidgets import QApplication
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


def main():
    _setup_logging()
    set_language(load_language())

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # The window is shown immediately with fallback defaults; the live
    # llama-server --help / --version results are fetched on a background
    # thread and merged in asynchronously (plan A10).
    window = MainWindow(
        work_dir=_get_work_dir(),
        defaults=dict(_FALLBACK_DEFAULTS),
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
