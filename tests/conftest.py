"""Shared pytest fixtures for the llama-cpp-launcher test suite."""
import gc

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _destroy_hidden_windows():
    """Release hidden top-level widgets after each test.

    PyQt6 keeps C++ widgets alive as long as a Python wrapper reference
    exists — w.close() only hides the window, and deleteLater() on widgets
    with a parent is ignored. Dead test frames can keep wrappers alive in
    cycles, so force a collection after each test: that drops the wrappers,
    frees the C++ windows (menus/popups cascade with them), and keeps the
    next QApplication.setStyleSheet() (theme apply) from re-polishing
    zombie windows and growing quadratically slow.
    """
    yield
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    app.processEvents()
