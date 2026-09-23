# -*- coding: utf-8 -*-
"""App base-font selection (runtime health probe).

The app's base font is chosen at startup from a list of guaranteed-present
Windows families, probing each candidate's DIGIT rendering: a healthy face
advances each ASCII digit by ~0.3–0.6em, while a corrupted/substituted face
whose digit code points map to CJK/symbol glyphs (a user's machine 2026-09:
0→O, 4→×, 5→6, 8→≠, 9→女) advances them by ~1em. The probe rejects broken
faces and logs every probe to launcher.log (logger "font"). Static family
pinning alone was not enough (v1.8.3): on the report machine the broken
face IS what the pinned family name resolves to.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def test_candidate_chain_starts_with_guaranteed_family():
    import main as main_mod
    # Segoe UI first (ships with every Windows Vista+), CJK fallbacks after
    assert main_mod.APP_FONT_CANDIDATES[0] == "Segoe UI"
    assert "Microsoft YaHei UI" in main_mod.APP_FONT_CANDIDATES
    assert "Microsoft YaHei" in main_mod.APP_FONT_CANDIDATES


def test_digit_probe_threshold_rejects_cjk_width():
    import main as main_mod
    # a digit advancing at CJK/symbol width (~1em) must be rejected;
    # normal digit widths (~0.5em) must pass
    assert main_mod._DIGIT_MAX_ADVANCE_EM < 1.0
    assert main_mod._DIGIT_MAX_ADVANCE_EM >= 0.5


def test_picker_rejects_broken_face_and_falls_to_next(app):
    import main as main_mod
    from PyQt6.QtGui import QFont

    def healthy(f: QFont) -> bool:
        # simulate: Segoe UI face is the broken one on the report machine
        return f.family() != "Segoe UI"

    font = main_mod._pick_healthy_font(app, healthy=healthy)
    assert font.family() == "Microsoft YaHei UI"


def test_picker_picks_first_healthy_candidate(app):
    import main as main_mod
    font = main_mod._pick_healthy_font(app, healthy=lambda f: True)
    assert font.family() == main_mod.APP_FONT_CANDIDATES[0]


def test_picker_falls_back_to_first_when_all_broken(app, caplog):
    import logging
    import main as main_mod

    with caplog.at_level(logging.WARNING, logger="font"):
        font = main_mod._pick_healthy_font(app, healthy=lambda f: False)
    assert font.family() == main_mod.APP_FONT_CANDIDATES[0]
    assert any("no healthy candidate" in r.message for r in caplog.records)


def test_picked_font_keeps_concrete_system_size(app):
    import main as main_mod
    font = main_mod._pick_healthy_font(app, healthy=lambda f: True)
    # a concrete size, never QFont's -1 ("inherit"): on a normal system
    # this is the system UI size (9pt+), else the 9pt fallback
    assert font.pointSize() > 0


def test_app_font_is_applied_in_main(app):
    # main() must actually call setFont(_pick_healthy_font(app)) — guard
    # against the helper existing but never being wired in
    import main as main_mod
    src = open(os.path.join(os.path.dirname(os.path.abspath(main_mod.__file__)),
                            "main.py"), encoding="utf-8").read()
    assert "app.setFont(_pick_healthy_font(app))" in src
