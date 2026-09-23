# -*- coding: utf-8 -*-
"""App base-font pinning.

The app's base font is pinned to Segoe UI (present on every Windows
Vista+ install) with a CJK fallback family list, instead of inheriting
whatever the system's default UI font resolves to. On some machines the
default UI font is substituted/corrupted and scrambles the Latin DIGIT
glyphs (0→O, 4→×, 5→6, 8→≠, 9→女) while letters stay normal — spinbox
values rendered as mojibake (reported 2026-09). These tests pin the
pinning so it cannot silently regress back to the system default.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def test_base_font_pins_guaranteed_family(app):
    import main as main_mod
    font = main_mod._app_base_font(app)
    assert font.family() == "Segoe UI"


def test_base_font_keeps_concrete_system_size(app):
    import main as main_mod
    font = main_mod._app_base_font(app)
    # a concrete size, never QFont's -1 ("inherit"): on a normal system
    # this is the system UI size (9pt+), else the 9pt fallback
    assert font.pointSize() > 0


def test_base_font_family_list_cjk_chain():
    import main as main_mod
    # Segoe UI first (Latin/digits), then the system CJK fonts so CJK
    # text falls back per character instead of tofu
    assert main_mod.APP_FONT_FAMILIES[0] == "Segoe UI"
    assert "Microsoft YaHei UI" in main_mod.APP_FONT_FAMILIES
    assert "Microsoft YaHei" in main_mod.APP_FONT_FAMILIES


def test_app_font_is_applied_in_main(app):
    # main() must actually call setFont(_app_base_font(app)) — guard
    # against the helper existing but never being wired in
    import main as main_mod
    src = open(os.path.join(os.path.dirname(os.path.abspath(main_mod.__file__)),
                            "main.py"), encoding="utf-8").read()
    assert "app.setFont(_app_base_font(app))" in src
