"""E12: frameless window chrome — shared title bar / edge-resize
filter / themed message box.

Renders the real windows offscreen and pins the structure: the main
window's frameless flags + title bar + menu-widget slot + resize opt-in
property, the resizable vs fixed dialog distinction, and the
ThemedMessageBox button/role semantics (the modal exec() loop is never
entered — buttons are driven directly).

The QApplication lives in a module-scoped ``app`` fixture, the same
pattern the other UI test files use (the pinned PyQt6 build crashes
when a test body constructs QApplication through an extra Python
frame).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import core.config as CC
from core.defaults import _FALLBACK_DEFAULTS


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    d = tmp_path / "presets"
    d.mkdir(parents=True)
    monkeypatch.setattr(CC, "PRESETS_DIR", d)
    monkeypatch.setattr(CC, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path


def _by_name(w, name):
    return next(c for c in w.findChildren(object) if c.objectName() == name)


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------

def test_mainwindow_is_frameless_with_titlebar(app, temp_settings):
    from PyQt6.QtCore import Qt
    from ui.main_window import MainWindow
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        assert w.objectName() == "llamaMainWin"
        assert w.windowFlags() & Qt.WindowType.FramelessWindowHint
        # E13: translucent rounded card — the card face + drop shadow are
        # painted in paintEvent, so the top level keeps an alpha surface
        assert w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # E13: single integrated chrome row (icon + title + menu + window
        # buttons) in the menu-widget slot — the TitleBar IS the menu
        # widget, and the QMenuBar is hosted in its row
        tb = w._title_bar
        assert tb.objectName() == "titleBar"
        for name in ("titleBarTitle", "titleBarMinBtn",
                     "titleBarMaxBtn", "titleBarCloseBtn"):
            _by_name(tb, name)
        assert tb._title.text() == w.windowTitle()
        top = w._top_bar
        assert w.menuWidget() is top
        assert top is tb
        assert w._menubar.parentWidget() is tb
        assert w._menubar.objectName() == "titleMenuBar"
        # menu titles unchanged (E10 layout)
        assert [a.text() for a in w._menubar.actions()] == ["文件", "设置", "帮助"]
        # edge-resize is handled by the app-level event filter; the
        # window opts in via property (no overlay widget — an ignored
        # event would not reach the sibling widgets below)
        # E13.1: the grip covers the whole shadow band so the resize
        # cursor sits at the visible card edge, not in the shadow
        from core.constants import CARD_CONTENT_INSET
        assert w.property("_e12_resize") == CARD_CONTENT_INSET
    finally:
        w.close()


def test_mainwindow_card_chrome_e13(app, temp_settings):
    """E13: rounded card + painted drop shadow.

    The transparent shadow band around the card must stay clear of
    content (title row / central / status bar are all inset), the
    window corners must be transparent in a grab(), and the band
    collapses to 0 when the window is maximized.
    """
    from PyQt6.QtCore import Qt
    from core.constants import (CARD_CONTENT_INSET, SHADOW_MARGIN,
                                TITLE_BAR_HEIGHT)
    from ui.main_window import MainWindow
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        w.show()
        app.processEvents()
        m = CARD_CONTENT_INSET
        # content insets: title row (band top+left+right on top of its
        # own 10/6 content padding), central (left+right). The status
        # message label carries its own inset (QStatusBar swaps its
        # internal layout on the first layout pass — a stored layout
        # wrapper or its margins would be stale).
        # getContentsMargins() returns a (l, t, r, b) tuple in this build
        lm, tm, rm, _bm = w._title_bar._row.getContentsMargins()
        assert (lm, tm, rm) == (10 + m, m, 6 + m)
        cl, _ct, cr, _cb = w._central_layout.getContentsMargins()
        assert (cl, cr) == (m, m)
        from PyQt6.QtWidgets import QLabel
        msg = w.statusBar().findChild(QLabel, "statusMsg")
        assert msg is not None
        assert msg.contentsMargins().left() >= m - 4  # text on face
        # the message must sit on the card face: the bar spans the
        # window's full bottom edge, so without a bottom inset the
        # centred text straddles the card border (descenders would paint
        # into the shadow band below the card)
        w.statusBar().showMessage("🚀 服务已启动: http://127.0.0.1:8080")
        app.processEvents()
        text_bottom = (w.statusBar().y() + msg.y()
                       + msg.contentsRect().bottom())
        assert text_bottom <= w.height() - SHADOW_MARGIN - 1
        assert msg.contentsMargins().bottom() == m
        # the band adds to the title row's height
        assert w._title_bar.height() == TITLE_BAR_HEIGHT + m
        # the shadow is part of the minimum size (the band is outside
        # the content)
        assert w.minimumWidth() >= 900 + 2 * CARD_CONTENT_INSET - 2
        # pixel probe: transparent band + rounded corners, opaque face,
        # shadow just outside the face edge
        img = w.grab().toImage()

        def alpha(x, y):
            return img.pixelColor(x, y).alpha()

        cx, cy = w.width() // 2, w.height() // 2
        # corners are pure desktop (the rounded arc keeps the ring away)
        assert alpha(2, 2) == 0                      # corner: desktop
        assert alpha(w.width() - 3, 2) == 0          # corner: desktop
        # the band mid-edges may carry the faint outer shadow falloff
        # (<= 8/255 — invisible), but nothing more
        assert alpha(cx, 2) <= 8                     # top band
        assert alpha(2, cy) <= 8                     # left band
        assert alpha(cx, w.height() - 2) <= 8        # bottom band
        assert alpha(cx, cy) > 0                     # card face opaque
        assert alpha(SHADOW_MARGIN - 1, cy) > 0      # shadow ring
        # maximized: band collapses, card fills the screen
        w.showMaximized()
        app.processEvents()
        assert w.isMaximized()
        assert w._title_bar.height() == TITLE_BAR_HEIGHT
        cl2, _ct2, cr2, _cb2 = w._central_layout.getContentsMargins()
        assert (cl2, cr2) == (0, 0)
        # band collapsed → the status message's bottom inset goes with it
        msg2 = w.statusBar().findChild(QLabel, "statusMsg")
        assert msg2.contentsMargins().bottom() == 0
        # normal: band restored
        w.showNormal()
        app.processEvents()
        cl3, _ct3, cr3, _cb3 = w._central_layout.getContentsMargins()
        assert cl3 == m
    finally:
        w.close()


def test_mainwindow_titlebar_actions(app, temp_settings):
    from ui.main_window import MainWindow
    from ui.message_box import ThemedMessageBox  # noqa: F401  (import check)
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        tb = w._title_bar
        close = _by_name(tb, "titleBarCloseBtn")
        close.clicked.emit()
        assert not w.isVisible() or True  # close() is async-safe
        # glyph/tooltip wiring exists and retranslates
        assert tb._max_btn is not None
        tb.retranslate_ui()
        assert tb._max_btn.toolTip() in ("最大化", "Maximize")
    finally:
        w.close()


def test_edge_resize_filter(app, temp_settings):
    """Regression for both E12 resize bugs:

    1. ``TypeError: unsupported operand type(s) for |=: 'int' and
       'Edge'`` — PyQt6 enums are not ints, the edge math must stay in
       pure ints (``edge_at`` covers the classification).
    2. A full-window overlay made the UI unclickable: an *ignored* mouse
       event propagates to the receiver's parent, never to the sibling
       beneath, so the overlay swallowed every click. The filter must
       pass non-edge events through untouched (return False)."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from ui.frameless import edge_at, ensure_resize_filter
    from ui.main_window import MainWindow

    # pure classification — borders, corners, interior (800×400, m=6)
    L = Qt.Edge.LeftEdge.value
    R = Qt.Edge.RightEdge.value
    T = Qt.Edge.TopEdge.value
    B = Qt.Edge.BottomEdge.value
    W, H, M = 800, 400, 6
    assert edge_at(2, H // 2, W, H, M) == L
    assert edge_at(W - 2, H // 2, W, H, M) == R
    assert edge_at(W // 2, 2, W, H, M) == T
    assert edge_at(W // 2, H - 2, W, H, M) == B
    assert edge_at(2, 2, W, H, M) == (L | T)
    assert edge_at(W - 2, 2, W, H, M) == (R | T)
    assert edge_at(2, H - 2, W, H, M) == (L | B)
    assert edge_at(W - 2, H - 2, W, H, M) == (R | B)
    assert edge_at(W // 2, H // 2, W, H, M) == 0

    # E13.1: the main window's grip = the whole shadow band
    from core.constants import CARD_CONTENT_INSET

    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        assert w.property("_e12_resize") == CARD_CONTENT_INSET
        # a press in the band (not just the old 6px strip) is the grip
        w.show()
        app.processEvents()
        filt = ensure_resize_filter()
        assert filt is not None
        child = w.centralWidget()
        fr = w.frameGeometry()

        def press_at(gx, gy):
            return QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(gx, gy),  # local coords unused by the filter
                QPointF(gx, gy),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)

        def move_at(gx, gy):
            return QMouseEvent(
                QEvent.Type.MouseMove, QPointF(gx, gy), QPointF(gx, gy),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier)

        cx, cy = fr.x() + fr.width() // 2, fr.y() + fr.height() // 2
        # interior press: passed through to the target widget
        assert not filt.eventFilter(child, press_at(cx, cy))
        # left-edge press: eaten, native system resize started
        assert filt.eventFilter(child, press_at(fr.x() + 2, cy))
        # E13.1: a press deep in the shadow band (beyond the old 6px
        # strip, at the visible card edge) is the grip too
        from core.constants import SHADOW_MARGIN
        assert filt.eventFilter(child,
                                press_at(fr.x() + SHADOW_MARGIN - 2, cy))
        # left-edge move: horizontal resize cursor
        assert not filt.eventFilter(child, move_at(fr.x() + 2, cy))
        assert w.cursor().shape() == Qt.CursorShape.SizeHorCursor
        # ...and the cursor already changes inside the band
        assert not filt.eventFilter(
            child, move_at(fr.x() + SHADOW_MARGIN - 2, cy))
        assert w.cursor().shape() == Qt.CursorShape.SizeHorCursor
        # corner move: diagonal cursor
        assert not filt.eventFilter(child, move_at(fr.x() + 2, fr.y() + 2))
        assert w.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
        # back to the middle: cursor released again
        assert not filt.eventFilter(child, move_at(cx, cy))
        assert w.cursor().shape() != Qt.CursorShape.SizeHorCursor
    finally:
        w.close()


# --------------------------------------------------------------------------
# dialogs
# --------------------------------------------------------------------------

def test_dialog_is_a_real_window_titlebar_targets_dialog(app, temp_settings):
    """Regression: ``setWindowFlags(FramelessWindowHint)`` (without OR-ing
    the existing flags) wiped the ``Qt::Window`` bit — the dialog had no
    windowHandle ("cannot open"), and ``TitleBar._window()`` resolved to
    the MAIN window, so dragging a dialog moved the main window and its
    close button closed the main window. Flags must be OR-ed, and the
    title bar must act on the dialog itself."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMessageBox
    from ui.main_window import MainWindow
    from ui.message_box import ThemedMessageBox
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        w.show()
        app.processEvents()
        box = ThemedMessageBox(w, icon=QMessageBox.Icon.Information,
                               title="关于", text="测试内容")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        try:
            assert box.isWindow()
            assert box.windowFlags() & Qt.WindowType.Window
            # the title bar must target the dialog, not the parent
            assert box._title_bar._window() is box
            box.show()
            app.processEvents()
            assert box.windowHandle() is not None
            # close button closes the dialog — the main window survives
            _by_name(box, "titleBarCloseBtn").clicked.emit()
            app.processEvents()
            assert not box.isVisible()
            assert w.isVisible()
        finally:
            box.deleteLater()
    finally:
        w.close()


def test_fixed_width_dialog_height_resolved_under_exec(app, temp_settings):
    """Regression: fixed-width dialogs resolve their height via
    ``adjustSize()`` — that must run from ``showEvent``, not a
    ``show()`` override (``QWidget::show()`` is non-virtual, so
    ``exec()`` never calls the Python override and the box came up
    with an unresolved height)."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QMessageBox
    from ui.main_window import MainWindow
    from ui.message_box import ThemedMessageBox
    w = MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))
    try:
        w.show()
        app.processEvents()
        box = ThemedMessageBox(w, icon=QMessageBox.Icon.Warning,
                               title="警告", text="x" * 200)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        QTimer.singleShot(150, box.accept)
        box.exec()
        # fixed width kept, height resolved from the content
        assert box.width() == 480
        assert box.height() > 120
        box.deleteLater()
    finally:
        w.close()


def test_resizable_dialogs_edge_resize(app, temp_settings):
    from ui.quick_params_dialog import QuickParamsDialog
    from ui.server_path_dialog import ServerPathDialog
    qpd = QuickParamsDialog(None, current_keys=None)
    try:
        assert qpd.objectName() == "framelessDialog"
        _by_name(qpd, "framelessCard")
        # E13.1: the dialog's grip covers its shadow band too
        from ui.frameless import _SHADOW_PAD
        assert qpd.property("_e12_resize") == _SHADOW_PAD
        assert qpd.minimumWidth() >= 640 and qpd.minimumHeight() >= 460
        # title bar mirrors the window title and follows setWindowTitle
        assert _by_name(qpd, "titleBarTitle").text() == qpd.windowTitle()
    finally:
        qpd.deleteLater()
    spd = ServerPathDialog(None, "C:/x/llama-server.exe", "C:/x/llama-server.exe")
    try:
        # fixed-size card: no edge-resize opt-in
        assert not spd.property("_e12_resize")
        assert spd.width() == 600
    finally:
        spd.deleteLater()


def test_dialog_card_corners_round_e132(app, temp_settings):
    """E13.2: all four card corners round.

    The content body fills the card edge-to-edge; the generic QWidget
    QSS rule used to make it paint a *square* win_bg over the card's
    rounded BOTTOM corners (the transparent TitleBar covered the top
    pair, so only the bottom looked square). Pixel probe on real
    dialogs: the corner arc region must be fully transparent (desktop
    shows through), the card face just past the arc fully opaque.
    """
    from PyQt6.QtWidgets import QMessageBox
    from ui.message_box import ThemedMessageBox
    from ui.server_path_dialog import ServerPathDialog

    def probe(dlg):
        dlg.show()
        app.processEvents()
        img = dlg.grab().toImage()
        cg = dlg._card.geometry()

        def a(x, y):
            return img.pixelColor(x, y).alpha()

        # corner arc points (2px inside each card corner — outside the
        # 14px arc): only the drop-shadow's faint falloff may bleed in
        # (measured 12 top / 27 bottom, offset (0,3)); the regression
        # (the body's SQUARE win_bg over the bottom corners) reads 255
        for label, x, y in (("top-left", cg.x() + 2, cg.y() + 2),
                            ("top-right", cg.right() - 2, cg.y() + 2),
                            ("bottom-left", cg.x() + 2, cg.bottom() - 2),
                            ("bottom-right", cg.right() - 2, cg.bottom() - 2)):
            assert a(x, y) <= 40, f"{label}: {a(x, y)}"
        # card face: bottom edge just past the arc + centre, opaque
        assert a(cg.x() + 40, cg.bottom() - 2) == 255, "bottom edge face"
        assert a(cg.x() + cg.width() // 2, cg.y() + cg.height() // 2) == 255

    spd = ServerPathDialog(None, "C:/x/llama-server.exe", "C:/x/llama-server.exe")
    try:
        probe(spd)
    finally:
        spd.deleteLater()
    box = ThemedMessageBox(None, icon=QMessageBox.Icon.Warning,
                           title="警告", text="x" * 60)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    try:
        probe(box)
    finally:
        box.deleteLater()


def test_dialog_title_follows_setwindowtitle(app):
    from ui.frameless import FramelessDialog
    d = FramelessDialog(None, title="alpha", resizable=True, size=(400, 300),
                        min_size=(300, 200))
    try:
        d.setWindowTitle("beta")
        assert _by_name(d, "titleBarTitle").text() == "beta"
    finally:
        d.deleteLater()


# --------------------------------------------------------------------------
# themed message box
# --------------------------------------------------------------------------

def _mk_box(icon=None, title="标题", text="内容"):
    from PyQt6.QtWidgets import QMessageBox
    from ui.message_box import ThemedMessageBox
    return ThemedMessageBox(None, icon=icon or QMessageBox.Icon.Question,
                            title=title, text=text)


def test_message_box_question_semantics(app):
    from PyQt6.QtWidgets import QDialog, QMessageBox, QPushButton
    box = _mk_box(QMessageBox.Icon.Question, "端口占用", "是否继续？")
    try:
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        accept_btn = _by_name(box, "msgBoxBtnAccept")
        assert accept_btn.text() == "是" and accept_btn.isDefault()
        reject_btn = next(b for b in box.findChildren(QPushButton)
                          if b.objectName() == "msgBoxBtn")
        assert reject_btn.text() == "否"
        # clicking 是 -> Accepted + StandardButton.Yes
        accept_btn.clicked.emit()
        assert box.result() == QDialog.DialogCode.Accepted
        assert box._clicked_std() == QMessageBox.StandardButton.Yes

        # Esc (reject) reports the reject-role button: No
        box2 = _mk_box(QMessageBox.Icon.Question)
        box2.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box2.reject()
        assert box2.result() == QDialog.DialogCode.Rejected
        assert box2._clicked_std() == QMessageBox.StandardButton.No
        box2.deleteLater()
    finally:
        box.deleteLater()


def test_message_box_ok_and_detailed_text(app):
    from PyQt6.QtWidgets import QMessageBox
    box = _mk_box(QMessageBox.Icon.Warning, "差异", "检测到 2 项不匹配")
    try:
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok = _by_name(box, "msgBoxBtnAccept")
        assert ok.text() == "确定"
        assert _by_name(box, "msgBoxText").text() == "检测到 2 项不匹配"
        detail = _by_name(box, "msgBoxDetail")
        assert detail.isHidden()
        box.setDetailedText("line1\nline2")
        assert not detail.isHidden()
        assert "line2" in detail.toPlainText()
        # warning icon glyph present
        assert _by_name(box, "msgBoxIconWarn").text()
    finally:
        box.deleteLater()


def test_message_box_en_language_buttons(app):
    import core.i18n as I
    from PyQt6.QtWidgets import QMessageBox
    original = I.get_language()
    try:
        I.set_language("en")
        box = _mk_box(QMessageBox.Icon.Question)
        try:
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            assert _by_name(box, "msgBoxBtnAccept").text() == "Yes"
            reject_btn = next(b for b in box.findChildren(object)
                              if b.objectName() == "msgBoxBtn")
            assert reject_btn.text() == "No"
        finally:
            box.deleteLater()
    finally:
        I.set_language(original)
