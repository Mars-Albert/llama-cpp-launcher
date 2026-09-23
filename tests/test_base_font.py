# -*- coding: utf-8 -*-
"""App base-font selection: bundled Inter TTF first, probed system chain second.

The primary base font is the **bundled** assets/fonts/Inter-Regular.ttf
(OFL, registered at startup via QFontDatabase.addApplicationFont) — a file
inside the exe cannot be shadowed/corrupted by the machine's font store.
User report 2026-09/10: a machine scrambled the Latin DIGIT glyphs
(0→O, 4→×, 5→6, 8→≠, 9→女) while letters stayed normal; static family
pinning (v1.8.3) did not help because the broken face IS what the family
name resolves to there. As a second layer every candidate's digit glyphs
are probed (a healthy face advances digits ~0.3–0.6em; a face mapping
digits to wide CJK/symbol glyphs advances ~1em) and all probes are logged
to launcher.log (logger "font").
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_bundled_font_file_in_repo():
    import main as main_mod
    path = os.path.join(_repo_root(), "assets", "fonts", "Inter-Regular.ttf")
    assert os.path.exists(path), "bundled UI font TTF must be in the repo"
    with open(path, "rb") as f:
        magic = f.read(4)
    # valid TTF/OTF table header
    assert magic in (b"\x00\x01\x00\x00", b"true", b"OTTO"), magic
    assert os.path.getsize(path) > 100_000  # a real font, not a stub


def test_bundled_font_licence_shipped():
    lic = os.path.join(_repo_root(), "assets", "fonts", "OFL-Inter.txt")
    assert os.path.exists(lic), "OFL license must ship with the bundled font"


def test_load_bundled_font_returns_family(app):
    import main as main_mod
    fam = main_mod._load_bundled_font()
    assert fam, "bundled font must load and report a family"
    assert "inter" in fam.lower()


def test_bundled_font_path_dev():
    import main as main_mod
    p = main_mod._bundled_font_path()
    assert os.path.dirname(p) == os.path.join(
        os.path.dirname(os.path.abspath(main_mod.__file__)), "assets", "fonts")
    assert os.path.exists(p)


def test_bundled_font_path_frozen(tmp_path, monkeypatch):
    import sys
    import main as main_mod
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert main_mod._bundled_font_path() == str(
        tmp_path / "assets" / "fonts" / "Inter-Regular.ttf")


def test_spec_bundles_font_dir():
    # guard against regressing the spec datas entry: without it the frozen
    # font path never exists and the app silently falls back to system fonts
    spec = os.path.join(_repo_root(), "llama_cpp_launcher.spec")
    text = open(spec, encoding="utf-8").read()
    assert "('assets/fonts', 'assets/fonts')" in text


def test_system_chain_starts_with_guaranteed_family():
    import main as main_mod
    # system fallback chain (used when the bundled font is unavailable)
    assert main_mod.APP_FONT_CANDIDATES[0] == "Segoe UI"
    assert "Microsoft YaHei UI" in main_mod.APP_FONT_CANDIDATES


def test_digit_probe_threshold_rejects_cjk_width():
    import main as main_mod
    # a digit advancing at CJK/symbol width (~1em) must be rejected;
    # normal digit widths (~0.5em) must pass
    assert 0.5 <= main_mod._DIGIT_MAX_ADVANCE_EM < 1.0


def test_picker_prefers_bundled_family(app):
    import main as main_mod
    font = main_mod._pick_healthy_font(
        app, healthy=lambda f: True, bundled_family="InterBundled")
    assert font.family() == "InterBundled"


def test_picker_rejects_broken_face_and_falls_to_next(app):
    import main as main_mod
    from PyQt6.QtGui import QFont

    def healthy(f: QFont) -> bool:
        # simulate the report machine: every Segoe UI shadowed face broken
        return f.family() != "Segoe UI"

    font = main_mod._pick_healthy_font(
        app, healthy=healthy, bundled_family="")
    assert font.family() == "Microsoft YaHei UI"


def test_picker_picks_first_healthy_candidate(app):
    import main as main_mod
    font = main_mod._pick_healthy_font(
        app, healthy=lambda f: True, bundled_family="")
    assert font.family() == main_mod.APP_FONT_CANDIDATES[0]


def test_picker_falls_back_to_first_when_all_broken(app, caplog):
    import logging
    import main as main_mod

    with caplog.at_level(logging.WARNING, logger="font"):
        font = main_mod._pick_healthy_font(
            app, healthy=lambda f: False, bundled_family="")
    assert font.family() == main_mod.APP_FONT_CANDIDATES[0]
    assert any("no healthy candidate" in r.message for r in caplog.records)


def test_picked_font_keeps_concrete_system_size(app):
    import main as main_mod
    font = main_mod._pick_healthy_font(app, healthy=lambda f: True,
                                       bundled_family="")
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
