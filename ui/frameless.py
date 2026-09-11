"""E12: frameless window infrastructure — one window style for the whole app.

The native OS title bar (bright blue on this Windows setup) clashed with
the app theme, so every top-level window is frameless and draws its own
chrome:

- ``TitleBar``        — title strip: app icon, title, optional
  minimize / maximize-restore / close buttons. Since E13 it can also
  host a ``QMenuBar`` in its row (the main window's integrated chrome
  row: icon + title + menu + window buttons) and takes a custom
  ``height`` (main window 44, dialogs 38). Drag =
  ``QWindow.startSystemMove()`` (native feel, Aero Snap works),
  double-click = toggle maximize.
- ``FramelessDialog`` — QDialog base: translucent top level, rounded
  card with border + drop shadow, TitleBar (close only) and a ready
  ``content_layout``. Optionally resizable (edge-resize, see below).
- ``_ResizeFilter``   — QApplication-level event filter turning the
  outer 6px strip of every opted-in window into 8-direction resize
  handles (``startSystemResize``) with proper edge cursors. Windows opt
  in with the ``_e12_resize`` property (margin). A full-window
  *overlay* cannot do this: an ignored mouse event propagates to the
  receiver's parent, not to the sibling underneath, so an overlay
  swallows every click in the window — a filter returns False and the
  event reaches its target untouched.
- ``install_frameless`` — flags + edge-resize opt-in for a top-level
  window (the main window builds its own title bar into the menu-widget
  slot; since E13 it is translucent and paints its own rounded card +
  drop shadow in ``MainWindow.paintEvent``).

All chrome styling lives in ``MainWindow._THEME_TEMPLATE`` under the
``frameless*`` / ``titleBar*`` object names (app-level sheet), so light /
dark switching restyles the chrome live.
"""
import os
import sys

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.i18n import t

# Translucent margin around a dialog card — room for the drop shadow.
_SHADOW_PAD = 16

# Default width of the frameless edge/corner resize strip (window
# property ``_e12_resize`` on every resizable frameless window).
# E13.1: windows with a transparent shadow band pass a margin that covers
# the whole band (see install_frameless(resize_margin=...) and
# FramelessDialog), so the resize cursor/grip sits exactly at the visible
# card edge instead of in the shadow air outside it.
RESIZE_MARGIN = 6


def app_icon() -> QIcon:
    """Bundled window icon (same resolution as main._app_icon_path())."""
    if getattr(sys, "frozen", False):
        path = os.path.join(sys._MEIPASS, "assets", "icon.ico")
    else:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), os.pardir,
            "assets", "icon.ico",
        )
    return QIcon(path) if os.path.exists(path) else QIcon()


class TitleBar(QWidget):
    """Custom title strip. Buttons are optional (dialogs: close only).

    The owning window is passed explicitly (it is usually not the
    parent at construction time) and drives the min / max-restore /
    close actions and the double-click maximize toggle.
    """

    _MIN_GLYPH = "\u2212"     # −
    _MAX_GLYPH = "\u25a1"     # □
    _RESTORE_GLYPH = "\u2750"  # ❐
    _CLOSE_GLYPH = "\u2715"   # ✕

    def __init__(self, title, icon: QIcon = None, window=None,
                 min_btn: bool = False, max_btn: bool = False,
                 menu_bar=None, height: int = 38):
        super().__init__()
        self.setObjectName("titleBar")
        self.setFixedHeight(height)
        # Paints the (transparent) stylesheet background explicitly —
        # plain QWidgets otherwise ignore the QSS background rules.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # NB: the owning window is deliberately NOT stored — a strong
        # _win reference would close a Python ref cycle (window holds
        # the title bar, title bar holds window) that this PyQt6 build
        # hard-crashes on when GC breaks it after the window dies.
        # self.window() resolves it lazily through the C++ parent chain.
        self._max_btn = None
        # Qt6 dropped the windowStateChange signal — watch the window's
        # events for state flips from the WM (Win+Up, Aero Snap) so the
        # max/restore glyph stays correct (C++-level filter reference
        # only; removed automatically when either side is destroyed).
        if window is not None:
            window.installEventFilter(self)

        # E13: the main window hosts its QMenuBar in this row (a single
        # integrated chrome row instead of a title strip + menu strip).
        # All menu behaviour (icons, checkables, shortcuts, popups) is
        # the native QMenuBar's; the owner sets the objectName for QSS.
        self._menu_bar = menu_bar

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(10, 0, 6, 0)
        self._row.setSpacing(8)
        if icon is not None and not icon.isNull():
            icon_lbl = QLabel()
            icon_lbl.setObjectName("titleBarIcon")
            icon_lbl.setPixmap(icon.pixmap(20, 20))
            self._row.addWidget(icon_lbl)
        self._title = QLabel(title)
        self._title.setObjectName("titleBarTitle")
        self._row.addWidget(self._title)
        if menu_bar is not None:
            menu_bar.setNativeMenuBar(False)
            self._row.addWidget(
                menu_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self._row.addStretch(1)

        if min_btn:
            self._row.addWidget(self._make_button(
                "titleBarMinBtn", self._MIN_GLYPH, t("最小化"),
                self._minimize))
        if max_btn:
            self._max_btn = self._make_button(
                "titleBarMaxBtn", self._MAX_GLYPH, t("最大化"),
                self.toggle_maximize)
            self._row.addWidget(self._max_btn)
        self._row.addWidget(self._make_button(
            "titleBarCloseBtn", self._CLOSE_GLYPH, t("关闭"), self._close))

    # ------------------------------------------------------------ actions
    def _window(self):
        return self.window()

    def _make_button(self, name, glyph, tip, slot):
        b = QPushButton(glyph)
        b.setObjectName(name)
        # E13: Windows-11-style controls (wide, flat, rounded)
        b.setFixedSize(40, 30)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def _minimize(self):
        w = self._window()
        if w is not None and w is not self:
            w.showMinimized()

    def _close(self):
        w = self._window()
        if w is not None and w is not self:
            w.close()

    def toggle_maximize(self):
        w = self._window()
        if w is None or w is self:
            return
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()
        self.refresh_max_state()

    def refresh_max_state(self):
        """Sync the max/restore glyph + tooltip with the window state
        (also called when the WM changes the state, e.g. Win+Up)."""
        if self._max_btn is None:
            return
        w = self._window()
        maximized = w is not None and w is not self and w.isMaximized()
        self._max_btn.setText(self._RESTORE_GLYPH if maximized else self._MAX_GLYPH)
        self._max_btn.setToolTip(t("还原") if maximized else t("最大化"))

    def eventFilter(self, obj, event):
        if (obj is self._window()
                and event.type() == QEvent.Type.WindowStateChange):
            self.refresh_max_state()
        return super().eventFilter(obj, event)

    def set_title(self, title: str):
        self._title.setText(title)

    def retranslate_ui(self):
        """Live language switch: button tooltips."""
        if self._max_btn is not None:
            self.refresh_max_state()
        for name in ("titleBarMinBtn", "titleBarCloseBtn"):
            b = self.findChild(QPushButton, name)
            if b is not None:
                b.setToolTip(t("最小化") if name == "titleBarMinBtn" else t("关闭"))

    # -------------------------------------------------------- dragging
    def mousePressEvent(self, event):
        # Native-feel drag of the whole window (also enables Aero Snap).
        if event.button() == Qt.MouseButton.LeftButton:
            w = self._window()
            if w is not None and w is not self:
                handle = w.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._max_btn is not None):
            self.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# Pure-int edge flags — PyQt6 enums are not ints (``int(QE)`` and
# ``int |= Qt.Edge`` both raise), so the calculation stays in ints via
# ``.value``; Qt.Edge(edge) converts back at the startSystemResize() call.
_L = Qt.Edge.LeftEdge.value
_R = Qt.Edge.RightEdge.value
_T = Qt.Edge.TopEdge.value
_B = Qt.Edge.BottomEdge.value

EDGE_CURSORS = {
    _L | _R: Qt.CursorShape.SizeHorCursor,
    _T | _B: Qt.CursorShape.SizeVerCursor,
    _L | _T: Qt.CursorShape.SizeFDiagCursor,
    _R | _B: Qt.CursorShape.SizeFDiagCursor,
    _R | _T: Qt.CursorShape.SizeBDiagCursor,
    _L | _B: Qt.CursorShape.SizeBDiagCursor,
    _L: Qt.CursorShape.SizeHorCursor,
    _R: Qt.CursorShape.SizeHorCursor,
    _T: Qt.CursorShape.SizeVerCursor,
    _B: Qt.CursorShape.SizeVerCursor,
}


def edge_at(x: int, y: int, width: int, height: int, margin: int) -> int:
    """Pure edge classification (window-local coords) -> int edge flag.

    0 = interior. Corners are the OR of both edges.
    """
    e = 0
    if x < margin:
        e |= _L
    elif x > width - margin:
        e |= _R
    if y < margin:
        e |= _T
    elif y > height - margin:
        e |= _B
    return e


class _ResizeFilter(QObject):
    """QApplication-level filter: routes frameless-window edge events.

    A full-window transparent *overlay* cannot do this — an ignored mouse
    event propagates to the receiver's **parent**, not to the sibling
    widget underneath, so an overlay would swallow every click in the
    whole window (the original E12 bug: dead UI after the first click).
    An event filter sees the event *before* delivery: inside the edge
    strip it starts a system resize and eats the press; everywhere else
    it returns False and the event reaches its target untouched.

    Windows opt in with the ``_e12_resize`` property (margin in px). The
    filter holds no Python reference to any window, so no GC cycle can
    form (this build of PyQt6 hard-crashes on QObject reference cycles).
    """

    def __init__(self):
        super().__init__()
        # window id() -> edge int that its window cursor currently shows
        self._edge_state = {}

    def eventFilter(self, obj, event) -> bool:
        et = event.type()
        if et not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove):
            return False
        if not isinstance(obj, QWidget):
            return False
        win = obj.window()
        if win is None:
            return False
        margin = win.property("_e12_resize")
        if not margin:
            return False
        if win.isMaximized():
            self._sync_cursor(win, 0)
            return False
        fr = win.frameGeometry()
        gp = event.globalPosition().toPoint()
        edge = edge_at(gp.x() - fr.x(), gp.y() - fr.y(),
                       fr.width(), fr.height(), margin)
        if et == QEvent.Type.MouseButtonPress:
            if edge and event.button() == Qt.MouseButton.LeftButton:
                handle = win.windowHandle()
                if handle is not None:
                    handle.startSystemResize(Qt.Edge(edge))
                return True
            return False
        self._sync_cursor(win, edge)
        return False

    def _sync_cursor(self, win, edge):
        if self._edge_state.get(id(win)) == edge:
            return
        self._edge_state[id(win)] = edge
        if edge:
            win.setCursor(EDGE_CURSORS[edge])
        else:
            win.unsetCursor()


_app_filter = None


def ensure_resize_filter():
    """Install the single app-level resize filter (idempotent)."""
    global _app_filter
    app = QApplication.instance()
    if app is None or _app_filter is not None:
        return _app_filter
    _app_filter = _ResizeFilter()
    app.installEventFilter(_app_filter)
    return _app_filter


class FramelessDialog(QDialog):
    """Themed frameless card dialog.

    Subclasses build their UI into ``content_layout`` (a vertical box on
    the card, below the title bar). ``size`` / ``min_size`` of 0 mean
    "leave to the layout" (fixed-width dialogs use ``size=(w, 0)`` with
    ``resizable=False``).
    """

    def __init__(self, parent, title: str, icon: QIcon = None,
                 resizable: bool = True, size=(0, 0), min_size=(0, 0),
                 shadow: bool = True):
        super().__init__(parent)
        self.setObjectName("framelessDialog")
        # OR, never replace: setWindowFlags(FramelessWindowHint) on its
        # own wipes the Qt::Window bit -> isWindow() False, no
        # windowHandle (the dialog "cannot open" as a window), and
        # every child's .window() walks the parent chain up to the
        # MAIN window, so the title bar's drag/close hit the parent.
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        # Shadow colour follows the theme the parent is showing (fall
        # back to the persisted setting for standalone use).
        theme = getattr(parent, "theme", None) if parent is not None else None
        if theme not in ("light", "dark"):
            from core.config import load_theme
            theme = load_theme()
        self._shadow_theme = theme

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW_PAD, _SHADOW_PAD, _SHADOW_PAD,
                                 _SHADOW_PAD + 8)

        self._card = QFrame()
        self._card.setObjectName("framelessCard")
        if shadow:
            shadow_effect = QGraphicsDropShadowEffect(self)
            shadow_effect.setBlurRadius(28)
            shadow_effect.setOffset(0, 3)
            shadow_effect.setColor(
                QColor(0, 0, 0, 150 if theme == "dark" else 70))
            self._card.setGraphicsEffect(shadow_effect)
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        self._title_bar = TitleBar(title, icon=icon, window=self,
                                   min_btn=False, max_btn=False)
        card_layout.addWidget(self._title_bar)

        body = QWidget()
        # E13.3: the body spans the card's full width, so its QSS
        # background (the generic QWidget rule — a plain
        # WA_StyledBackground QWidget picks it up) used to paint a
        # *square* win_bg over the card's rounded BOTTOM corners (top
        # corners were fine — the transparent TitleBar covers them). The
        # id rule makes it transparent: the card's own rounded win_bg
        # background shows through, so all four corners round correctly.
        # (A 4-value border-radius shorthand would be the alternative —
        # this Qt build silently ignores it, verified offscreen.)
        body.setObjectName("framelessBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.content_layout = QVBoxLayout(body)
        self.content_layout.setContentsMargins(18, 12, 18, 14)
        self.content_layout.setSpacing(10)
        card_layout.addWidget(body, 1)

        # Keep the title bar label in sync with setWindowTitle().
        self.windowTitleChanged.connect(self._title_bar.set_title)

        if resizable:
            if size[0] or size[1]:
                self.resize(*size)
            if min_size[0] or min_size[1]:
                self.setMinimumSize(*min_size)
            # E13.1: the resize grip covers the whole shadow band so the
            # cursor appears at the visible card edge, not in the shadow
            # outside it.
            self.setProperty("_e12_resize", _SHADOW_PAD)
            ensure_resize_filter()
        else:
            self.setFixedWidth(size[0] or 560)
            # Content is added by the subclass after __init__ returns,
            # so the height can only be resolved when the widget first
            # shows (showEvent — NOT a show() override: QWidget::show()
            # is non-virtual, so C++'s exec() never calls the Python
            # override, only the showEvent event reaches us).
            self._needs_adjust = True

    # ------------------------------------------------------------- window
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_needs_adjust", False):
            self.adjustSize()
            self._needs_adjust = False
        # Frameless windows get no WM placement — center on the parent.
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            pg = parent.frameGeometry()
            self.move(pg.center() - self.rect().center())

    def retranslate_ui(self):
        self._title_bar.retranslate_ui()


def install_frameless(window, resizable: bool = True, translucent: bool = True,
                      resize_margin: int = RESIZE_MARGIN):
    """Make a top-level window frameless and edge-resizable.

    The window must set its own objectName (for the QSS border) and
    build its own title bar; this only applies the flags and the resize
    overlay. Call before the window is first shown.

    ``translucent=True`` for rounded-card windows (the dialogs, and the
    main window since E13): the top level keeps a transparent background
    and paints its own rounded card + drop shadow (the dialog does it
    with a QSS card + QGraphicsDropShadowEffect, MainWindow paints its
    card in ``paintEvent`` and insets its content by the shadow band —
    see ``_set_card_inset``). The chrome strips that touch the window
    edges (title row, status bar) must carry a transparent QSS
    background so the painted card face shows through their rounded
    corners.

    ``resize_margin`` (E13.1): width of the edge/corner resize grip in
    window px. Windows with a transparent shadow band should pass a
    margin that covers the whole band, so the resize cursor appears
    exactly at the visible card edge instead of in the shadow outside
    it (the main window passes ``CARD_CONTENT_INSET``).
    """
    window.setWindowFlags(
        window.windowFlags() | Qt.WindowType.FramelessWindowHint)
    if translucent:
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    if resizable:
        window.setProperty("_e12_resize", resize_margin)
        ensure_resize_filter()
    return window
