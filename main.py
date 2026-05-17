import sys
import os

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from core.defaults import get_default_params, get_chat_templates, fetch_help_text
from core.config import _refresh_defaults, load_language
from core.i18n import set_language


def main():
    set_language(load_language())

    help_text = fetch_help_text()
    _refresh_defaults(help_text)
    defaults = get_default_params(help_text=help_text)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow(
        work_dir=os.path.dirname(os.path.abspath(__file__)),
        defaults=defaults,
        chat_templates=get_chat_templates(help_text=help_text),
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
