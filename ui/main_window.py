import html as html_mod
import logging
import platform
import re
import shutil
import socket
import subprocess
import webbrowser
from importlib.metadata import version as pkg_version
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QPlainTextEdit, QComboBox, QInputDialog,
    QMessageBox, QFileDialog, QStatusBar,
    QCheckBox, QGroupBox, QTabWidget, QTextEdit,
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QToolButton,
    QScrollArea, QFrame, QMenuBar
)
import heapq
from collections import deque

from PyQt6.QtCore import (Qt, QTimer, QThread, QEvent, pyqtSignal, QPoint,
                          QRect, QRectF, PYQT_VERSION_STR)
from PyQt6.QtGui import (QAction, QFont, QTextOption, QIcon, QPixmap, QPainter,
                         QColor, QPalette, QTextCursor, QTextDocument, QKeySequence,
                         QShortcut, QImage, QPolygon, QPen)

from core.config import (
    ConfigManager, save_scan_path, load_scan_path, save_language,
    get_server_path, save_server_path, load_server_path,
    save_ui_prefs, load_ui_prefs, save_ui_pref,
    load_theme, save_theme,
    load_last_preset, save_last_preset,
    CONFIG_DIR, LOGS_DIR, LAST_RUN_LOG,
)
from core.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
    SHADOW_MARGIN, CARD_RADIUS, CARD_CONTENT_INSET, TITLE_BAR_HEIGHT,
    TITLE_GRAB_MIN,
    LOG_MAX_BLOCK_COUNT, LOG_DOC_MAX_BLOCK_COUNT,
    UNDO_HISTORY_MAX, PREVIEW_TIMER_MS, UNDO_DEBOUNCE_MS,
    VERSION_CHECK_TIMEOUT_S,
)
from ui.log_parser import colorize_log_line, parse_log_line, line_level
from ui.command_builder import CommandBuilder, quote_arg
from ui.runtime_info import build_info_html, empty_info_html
from core.runner import ServerRunner
from core.params_schema import PARAMS_BY_KEY
from core.i18n import t, get_language, set_language
from ui.model_browser import ModelBrowser
from ui.basic_panel import BasicPanel, ElidingLabel
from ui.advanced_panel import AdvancedPanel
from ui.gguf_inspector import GGUFInspectorDialog
from ui.frameless import (TitleBar, FramelessDialog, install_frameless,
                          app_icon)
from ui.message_box import ThemedMessageBox

try:
    # Single source of truth for the launcher version (build_config.py is
    # rewritten by release CI to match the tag). The frozen exe bundles it
    # via hiddenimports in llama_cpp_launcher.spec; the fallback only hits
    # for exes built before it was bundled.
    from build_config import VERSION as APP_VERSION
except ImportError:
    APP_VERSION = "dev"


class _ThemedStatusBar(QStatusBar):
    """E13: status bar whose message lives in a layout-managed label.

    ``QStatusBar.showMessage()`` paints its built-in label at a fixed
    x=6 that ignores layout margins — under the rounded card that
    overlaps the transparent corner band (the text would float over the
    drop shadow). A label added through ``addWidget`` goes through the
    layout, and its contents-margins keep the text on the painted card
    face — which the bar's own rect does NOT follow: the bar spans the
    window's full bottom edge, so its outer ``SHADOW_MARGIN`` px on the
    left and the bottom are the transparent shadow band (left margin is
    fixed; the bottom one is synced to the band by ``set_band_inset``,
    called from ``MainWindow._set_card_inset`` — without it the
    vertically centred 12px text straddled the card's bottom border and
    painted its descenders into the band below the card).
    """

    # Left margin: the bar's own ~2px x offset plus this keeps the first
    # glyph on the card face AND clears the bottom-left corner arc (the
    # face edge recedes to x = SHADOW_MARGIN + CARD_RADIUS in the lowest
    # rows) — 15px is the tight value that clears both.
    _LEFT_MARGIN = 15

    def __init__(self, parent=None):
        super().__init__(parent)
        # The frameless window is edge-resized by the app-level filter;
        # the native grip would also paint square into the corner band.
        self.setSizeGripEnabled(False)
        self._msg_label = QLabel(self)
        self._msg_label.setObjectName("statusMsg")
        # Bottom margin = the shadow band (synced by set_band_inset): it
        # pushes the text up onto the card face's visible strip.
        self._msg_label.setContentsMargins(self._LEFT_MARGIN, 0, 0,
                                           CARD_CONTENT_INSET)
        self.addWidget(self._msg_label)
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self._msg_label.setText(""))

    def set_band_inset(self, band):
        """Sync the label's bottom margin to the band width *band*
        (CARD_CONTENT_INSET normally, 0 when maximised — the card then
        fills the window, so no inset is needed). The bar's height
        follows the label's sizeHint, so the text re-centres on the
        visible card strip in both states."""
        self._msg_label.setContentsMargins(self._LEFT_MARGIN, 0, 0, band)

    def showMessage(self, message, timeout=0):
        self._msg_label.setText(message)
        if timeout > 0:
            self._msg_timer.start(int(timeout))

    def currentMessage(self):
        # QStatusBar.currentMessage() reads the internal label we no
        # longer use — mirror our own so the public API stays truthful
        return self._msg_label.text()


def _ensure_arrow_image(direction: str, color: str) -> Path:
    """Return a cached PNG of a small triangle arrow in *color*.

    Qt Style Sheets cannot render the CSS border-triangle trick on
    ``QComboBox::down-arrow`` / ``QSpinBox::up-arrow`` subcontrols —
    once QSS takes over, native triangles are not drawn (borders draw a
    rectangle, and unstyled spinbox arrows are simply missing). So the
    arrows are real images, generated once per color and cached in
    CONFIG_DIR (same dir as logs/settings).

    ``direction`` is ``"up"`` or ``"down"``. The down triangle keeps the
    legacy ``combo_arrow_*.png`` filename so existing caches are reused.
    """
    hex_color = color.lstrip("#").lower()
    name = "combo_arrow" if direction == "down" else "spin_arrow_up"
    path = CONFIG_DIR / f"{name}_{hex_color}.png"
    if path.exists():
        return path
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    img = QImage(12, 8, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if direction == "down":
        painter.drawPolygon(QPolygon([QPoint(1, 1), QPoint(11, 1), QPoint(6, 7)]))
    else:
        painter.drawPolygon(QPolygon([QPoint(6, 1), QPoint(1, 7), QPoint(11, 7)]))
    painter.end()
    img.save(str(path))
    return path


def _ensure_check_image() -> Path:
    """Return a cached white checkmark PNG for checked checkboxes.

    Same limitation as the arrow images: once QSS styles
    ``QCheckBox::indicator``, the native checkmark is not drawn, so a
    checked box needs an explicit image. White works for both themes
    because the checked background is the same blue in each.
    """
    path = CONFIG_DIR / "checkbox_check_white.png"
    if path.exists():
        return path
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    img = QImage(12, 12, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline(QPolygon([QPoint(2, 6), QPoint(5, 9), QPoint(10, 2)]))
    painter.end()
    img.save(str(path))
    return path


# Always-dark scrollbar QSS shared by the log and runtime-info panels
# (those areas stay dark in both app themes; E3/E5). Previously this block
# was copy-pasted inline twice; keeping one copy so fixes land in both.
_DARK_SCROLLBAR_QSS = """
            QScrollBar:vertical {
                background: #1e1e2e;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #585b70;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6c7086;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QScrollBar:horizontal {
                background: #1e1e2e;
                height: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal {
                background: #585b70;
                border-radius: 5px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #6c7086;
            }
        """


# Workers still running when their window closes: module-level references
# keep the QThread objects alive — destroying a *running* QThread is
# undefined behaviour in Qt and crashes this PyQt6 build natively (access
# violation), and a queued signal event whose sender was destroyed is
# equally fatal. Each worker removes itself when run() returns. (Same
# pattern as _active_meta_workers below.)
_active_startup_workers: set = set()


class _StartupInfoWorker(QThread):
    """Fetch llama-server version and --help off the main thread (plan A10).

    The window is shown immediately with fallback defaults; when this worker
    finishes, the live-parsed defaults / chat templates are merged into the
    window via _apply_startup_defaults(), so startup no longer blocks on the
    subprocess.
    """
    version_ready = pyqtSignal(str, str, str)  # version_num, commit, raw_line
    version_failed = pyqtSignal(str)  # error_type: "not_found", "no_version", "error"
    defaults_ready = pyqtSignal(dict, list)  # defaults, chat_templates
    devices_ready = pyqtSignal(list)  # E8: list of device dicts (may be empty = CPU-only)

    def run(self):
        _active_startup_workers.add(self)
        try:
            self._run_body()
        finally:
            _active_startup_workers.discard(self)

    def _run_body(self):
        # E1: resolved path (settings > PATH > bare name)
        self.server_path = get_server_path()
        try:
            result = subprocess.run(
                [self.server_path, "--version"],
                capture_output=True,
                text=True,
                timeout=VERSION_CHECK_TIMEOUT_S,
                encoding="utf-8",
                errors="replace",
            )
            output = result.stdout + result.stderr
            version_line = ""
            for line in output.split("\n"):
                if "version:" in line.lower():
                    version_line = line.strip()
                    break
            if version_line:
                m = re.search(r"version:\s*(\d+)\s*\((\w+)\)", version_line)
                if m:
                    self.version_ready.emit(m.group(1), m.group(2), version_line)
                else:
                    # Newer format: "version: 0.4.0-dev (build 10825, commit 9e0e22059)"
                    m = re.search(
                        r"version:[^\n]*\(build\s*(\d+),\s*commit\s*(\w+)\)", version_line
                    )
                    if m:
                        self.version_ready.emit(m.group(1), m.group(2), version_line)
                    else:
                        self.version_ready.emit("", "", version_line)
            else:
                self.version_failed.emit("no_version")
        except FileNotFoundError:
            self.version_failed.emit("not_found")
            return  # no binary on PATH: --help would fail too
        except Exception:
            self.version_failed.emit("error")
        # --help (up to 10s, off the main thread)
        self._emit_defaults()

    def _emit_defaults(self):
        try:
            from core.defaults import fetch_help_text, get_default_params, get_chat_templates
            help_text = fetch_help_text(server_path=self.server_path)
            if help_text and help_text.strip():
                self.defaults_ready.emit(
                    get_default_params(help_text=help_text),
                    get_chat_templates(help_text=help_text),
                )
                # E8: probe the actual GPU devices (only when this build has
                # the flag; older versions skip silently)
                if "--list-devices" in help_text:
                    try:
                        from core.defaults import parse_device_list
                        probe = subprocess.run(
                            [self.server_path, "--list-devices"],
                            capture_output=True,
                            text=True,
                            timeout=30,
                            encoding="utf-8",
                            errors="replace",
                        )
                        self.devices_ready.emit(
                            parse_device_list(probe.stdout + probe.stderr))
                    except Exception:
                        self.devices_ready.emit([])
        except Exception:
            pass  # window keeps the fallback defaults


# Workers still parsing when the window closes: module-level references keep
# the QThread objects alive (destroying a running QThread crashes the
# process); each worker removes itself on finish.
_active_meta_workers: set = set()


class _ModelMetaWorker(QThread):
    """Parse GGUF header metadata off the main thread (model-info quick row).

    parse_gguf_metadata only reads the header + metadata KV section (the
    first few MB of the file), but on a slow disk that is still real IO, so
    it runs in a thread and lands via finished_ok/finished_err. The seq
    counter guards against fast model switching: results for a model the
    user already moved on from are dropped by the handlers.
    """
    finished_ok = pyqtSignal(int, object)   # seq, GGUFQuickInfo
    finished_err = pyqtSignal(int, str)     # seq, error message

    def __init__(self, seq, path, parent=None):
        super().__init__(parent)
        self._seq = seq
        self._path = path

    def run(self):
        try:
            from gguf.parser import parse_gguf_metadata
            info = parse_gguf_metadata(self._path)
            self.finished_ok.emit(self._seq, info)
        except Exception as e:
            self.finished_err.emit(self._seq, str(e))


class MainWindow(QMainWindow):
    def __init__(self, work_dir=None, defaults=None, chat_templates=None, theme=None):
        super().__init__()
        # E5: theme ("light"/"dark"), persisted in settings.json
        self.theme = theme if theme in ("light", "dark") else load_theme()
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        saved_scan_path = load_scan_path()
        if saved_scan_path and Path(saved_scan_path).exists():
            self.model_dir = Path(saved_scan_path)
        else:
            self.model_dir = self.work_dir
        self.defaults = defaults or {}
        self.cmd_builder = CommandBuilder(self.defaults)
        self._version_checked = False
        self.chat_templates = chat_templates or []
        self.config = ConfigManager(defaults=self.defaults)
        self.runner = ServerRunner()
        self.is_advanced = False
        self.params = dict(self.defaults)
        self.params_history = [dict(self.params)]
        self.max_history = UNDO_HISTORY_MAX
        self._last_saved = dict(self.params)
        self._pending_snapshot = False
        # Keys a startup-restored preset explicitly set; the live --help
        # defaults merge must not overwrite them (see _apply_startup_defaults)
        self._preset_protected_keys = set()
        # E14: first-show bookkeeping — showEvent re-applies the intended
        # window size there (pre-show resize/restoreGeometry is discarded
        # once the E11 content minimums land during construction; see the
        # showEvent / _restore_ui_state comments).
        self._first_show_done = False
        self._pending_geometry = None
        self._pending_geometry_raw = None
        self._applying_values = False
        self._pending_webui_url = None
        # QProcess 读取块不保证按行对齐：每个流（stdout/stderr）各挂起一个
        # 未写完的半行。两个流分开挂起，否则一个流的半行会被粘到另一个流
        # 的完整行上，把整行日志吞掉
        self._log_tails = {"out": "", "err": ""}
        # B2: log lines are parsed immediately but rendered into this buffer;
        # a 100ms timer flushes the buffer with a single insertHtml, so
        # verbose logs no longer trigger one Qt layout pass per line.
        # E3: each entry is (level|None, html) — level None = always visible
        # (banners). _log_records mirrors the visible document and powers the
        # level-filter rebuild; it is capped at LOG_MAX_BLOCK_COUNT like the
        # document itself.
        self._log_html: list[tuple] = []
        self._log_records: list[tuple] = []
        # Per-level history windows (see LOG_MAX_BLOCK_COUNT): a narrow filter
        # view reads from these, so a flood of hidden levels (-lv 5 debug,
        # prompt dumps) cannot evict the visible level's lines out of the
        # shared global window before the user ever sees them.
        # (seq, (level, html)); each deque caps at LOG_MAX_BLOCK_COUNT.
        self._log_seq = 0
        self._level_histories = {
            lvl: deque(maxlen=LOG_MAX_BLOCK_COUNT)
            for lvl in ("D", "I", "W", "E", "F", None)
        }
        # Visible document blocks per level, in stream order — a per-level
        # eviction drops the level's front block live instead of at the next
        # filter toggle (only populated while a filter is active).
        self._doc_blocks = {lvl: deque() for lvl in self._level_histories}
        self._log_flush_timer = QTimer()
        # E3: full (un-truncated) log of the current server run
        self._run_log_file = None
        self._run_log_failed = False
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.timeout.connect(self._flush_log_buffer)
        # E13: cached painted chrome (shadow + card face), keyed by
        # (width, height, theme) — see _chrome_pixmap()
        self._chrome_cache = None
        self.start_time = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_timer)
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self._update_cmd_preview)
        self.preview_timer.start(PREVIEW_TIMER_MS)
        self._undo_debounce = QTimer()
        self._undo_debounce.setSingleShot(True)
        self._undo_debounce.timeout.connect(self._flush_snapshot)
        self._runtime_info = {}
        self._current_state = None
        self._mode_switching = False
        self.init_ui()
        self._connect_signals()
        self._restore_ui_state()
        self._restore_last_preset()
        self._check_server_info()

    @staticmethod
    def _default_window_size():
        """E14: first-launch window size.

        Fixed comfortable default (WINDOW_WIDTH × WINDOW_HEIGHT); clamped to
        the primary screen's available area so the window still opens inside
        the screen on small laptops. Once the user closes the app, the saved
        geometry (_restore_ui_state) takes over and this is not revisited.
        """
        base_w, base_h = WINDOW_WIDTH, WINDOW_HEIGHT
        screen = QApplication.primaryScreen()
        if screen is None:
            return base_w, base_h
        avail = screen.availableGeometry()
        return min(base_w, avail.width()), min(base_h, avail.height())

    @staticmethod
    def _default_splitter_sizes(width):
        """E14: first-launch splitter sizes for a window of `width` px.

        Fixed 400px left panel — wide enough to read model names and keep
        the preset buttons unclipped, narrow enough that the parameter panel
        keeps the lion's share. The clamp keeps the right side ≥900px (its
        content minimum is ~850) and stays inside the left panel's 180–500
        limits; the right side gets the rest.
        """
        content = width - 2 * CARD_CONTENT_INSET
        left = max(300, min(400, content - 900))
        return [left, max(100, content - left)]

    def init_ui(self):
        self.setWindowTitle(f"🦙 llama.cpp Launcher v{APP_VERSION}")
        # E12: objectName drives the frameless chrome QSS (1px border on
        # the transparent top level) — see _THEME_TEMPLATE.
        self.setObjectName("llamaMainWin")
        # E14: default size (clamped to the screen, see _default_window_size).
        self._default_w, self._default_h = self._default_window_size()
        self.resize(self._default_w, self._default_h)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self._apply_theme()

        # E13: the transparent band around the card is part of the central
        # widget's rect (see _set_card_inset); the #centralArea rule keeps
        # its background transparent so the painted card face / drop shadow
        # shows through the band (the generic QWidget rule would otherwise
        # paint it opaque all the way to the window edge).
        central = QWidget()
        central.setObjectName("centralArea")
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self._central_layout = main_layout

        # E2: kept as an instance attribute so closeEvent can persist its sizes
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._create_left_panel()
        self.splitter.addWidget(left_panel)

        right_panel = self._create_right_panel()
        self.splitter.addWidget(right_panel)

        # E14: fixed 400px left panel (the old 280px squeezed both sides —
        # model names and the preset buttons clipped).
        self.splitter.setSizes(self._default_splitter_sizes(self._default_w))
        main_layout.addWidget(self.splitter)

        self._create_menu_bar()
        self._create_status_bar()
        # E12/E13: frameless window chrome — flags + edge-resize overlay.
        # Must run before the first show (flags recreate the platform
        # window). Since E13 the window is a translucent rounded card
        # with a painted drop shadow (like the dialogs): the content is
        # inset by the shadow band (see _set_card_inset / paintEvent).
        # E13.1: the resize grip covers the whole shadow band, so the
        # cursor/grip sits at the visible card edge (not in the shadow
        # "air" outside it).
        install_frameless(self, resizable=True, translucent=True,
                          resize_margin=CARD_CONTENT_INSET)
        # E13: watch our own WindowStateChange / Move events (card band
        # collapse + keep-on-screen clamping — see eventFilter)
        self.installEventFilter(self)
        self._set_card_inset(CARD_CONTENT_INSET)

        self._sync_panel_min()

    # ------------------------------------------------- E13: card chrome
    def _set_card_inset(self, m):
        """E13: switch the shadow band in/out (m px; 0 when maximized).

        The title row and the central area span the full window width —
        their *content* is inset by the band so the painted rounded card
        face (paintEvent) shows through their transparent edges, and the
        card's crisp 1px border is never covered (content starts one px
        inside the face edge). The status bar's message label carries its
        own inset (see _ThemedStatusBar) because QStatusBar swaps its
        internal layout on the first layout pass and would drop margins —
        its bottom one is synced here, since the bar sits at the window's
        very bottom and would otherwise span the shadow band below the
        card (the text would straddle the card's bottom border).
        """
        self._title_bar.setFixedHeight(TITLE_BAR_HEIGHT + m)
        self._title_bar._row.setContentsMargins(10 + m, m, 6 + m, 0)
        self._central_layout.setContentsMargins(m, 0, m, 0)
        sb = self.statusBar()
        if isinstance(sb, _ThemedStatusBar):
            sb.set_band_inset(m)

    def _on_card_state_changed(self):
        # Maximized / fullscreen: the band collapses and the card fills
        # the screen edge-to-edge (driven from eventFilter on
        # WindowStateChange, so Win+Up / Aero Snap flips are covered).
        full = self.isMaximized() or self.isFullScreen()
        self._set_card_inset(0 if full else CARD_CONTENT_INSET)
        self._chrome_cache = None
        self.update()

    def _clamp_to_screen(self):
        """E13: keep a frameless window grabbable after being dragged away.

        A frameless window has no caption for the WM to constrain, so the
        title-bar row can be dragged (or restored from a stale saved
        geometry) partially off-screen — past a point where nothing is
        left to grab. Keep at least TITLE_GRAB_MIN px of the top row and
        a 24 px sliver on the other sides visible. Maximized / fullscreen
        rects are WM-managed and skipped; a window larger than its screen
        has no valid clamp.
        """
        if self.isMaximized() or self.isFullScreen():
            return
        from PyQt6.QtGui import QGuiApplication
        screen = (QGuiApplication.screenAt(self.frameGeometry().center())
                  or QGuiApplication.primaryScreen())
        avail = screen.availableGeometry()
        g = self.frameGeometry()
        if g.width() > avail.width() or g.height() > avail.height():
            return
        sliver = 24
        new_left = min(max(g.left(), avail.left() + sliver - g.width()),
                       avail.right() - sliver)
        new_top = min(max(g.top(), avail.top() + sliver - g.height()),
                      avail.bottom() - sliver)
        # The top row is the only grab handle — it gets the strictest
        # clamp (applied last so it wins over the bottom sliver rule).
        new_top = max(new_top, avail.top() - (g.height() - TITLE_GRAB_MIN))
        if (new_left, new_top) != (g.left(), g.top()):
            self.move(new_left, new_top)

    def _chrome_pixmap(self):
        """E13: cached drop shadow + rounded card face for the current
        window size / theme. Rebuilt lazily on resize or theme switch.

        The shadow is a stack of expanding rounded-rect rings with a
        quadratic alpha falloff — a pre-rendered stand-in for a blur.
        It is deliberately NOT a QGraphicsDropShadowEffect: an effect
        re-renders the entire window subtree through the blur on every
        child update (i.e. on every verbose log flush). The cached
        pixmap makes steady-state painting one drawPixmap.
        """
        w, h = self.width(), self.height()
        key = (w, h, self.theme)
        if self._chrome_cache is not None and self._chrome_cache[0] == key:
            return self._chrome_cache[1]
        pal = MainWindow._THEME_PALETTES[self.theme]
        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = SHADOW_MARGIN
        card = QRectF(m, m, w - 2 * m, h - 2 * m)
        r = CARD_RADIUS
        # Drop shadow: rings fading out to ~0 at the band edge. The +2
        # bottom offset drops the shadow slightly below the card.
        # E13.1: the band is tighter (10px) so the profile is a touch
        # denser — one ring per px of band. E13.2: peak alpha reduced
        # (the 10px band made the same alpha read much darker) — a soft
        # hint of elevation, not a heavy drop. Peaks lowered further:
        # at 95/45 the shadow still read heavy against the card border.
        alpha0 = 60 if self.theme == "dark" else 28
        rings = m
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(rings, 0, -1):
            a = int(alpha0 * ((rings - i) / rings) ** 2)
            if a <= 0:
                continue
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(card.adjusted(-i, -i, i, i + 2),
                              r + i * 0.9, r + i * 0.9)
        # Card face, then a crisp 1px border just inside the face edge
        # (the 0.5 offset lands the 1px pen on whole pixels).
        p.setBrush(QColor(pal["win_bg"]))
        p.drawRoundedRect(card, r, r)
        p.setPen(QPen(QColor(pal["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), r - 0.5,
                          r - 0.5)
        p.end()
        self._chrome_cache = (key, pix)
        return pix

    def paintEvent(self, event):
        # E13: the transparent top level is painted by hand — shadow +
        # rounded card face. Children (title row, central, status bar)
        # paint their content on top; their edge strips are transparent
        # so the face shows through the rounded corners.
        p = QPainter(self)
        if self.isMaximized() or self.isFullScreen():
            # Band collapsed: the card fills the screen edge-to-edge
            # (square — the DWM rounds a maximized window's corners on
            # Windows 11, which is the look we want there).
            p.fillRect(self.rect(),
                       QColor(MainWindow._THEME_PALETTES[self.theme]["win_bg"]))
        else:
            p.drawPixmap(0, 0, self._chrome_pixmap())
        p.end()

    def _create_left_panel(self):
        widget = QWidget()
        # C8: no setFixedWidth — the QSplitter handle must stay draggable.
        # The initial width comes from _default_splitter_sizes() (E14, ~22%
        # of the content width); min/max keep the drag range sane.
        widget.setMinimumWidth(180)
        widget.setMaximumWidth(500)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self.model_browser = ModelBrowser(search_dir=self.model_dir)
        self.model_browser.model_selected.connect(self._on_model_selected)
        self.model_browser.mmproj_selected.connect(self._on_mmproj_selected)
        layout.addWidget(self.model_browser)

        layout.addWidget(self._create_model_info_group())

        self.preset_group = QGroupBox(t("📦 预设管理"))
        preset_layout = QVBoxLayout(self.preset_group)
        preset_layout.setContentsMargins(6, 20, 6, 6)

        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._show_preset_created_hint)
        self._refresh_presets()
        preset_layout.addWidget(self.preset_combo)

        preset_btns = QHBoxLayout()
        self.btn_load = QPushButton(t("⬇️ 加载"))
        self.btn_save = QPushButton(t("💾 保存"))
        self.btn_delete = QPushButton(t("🗑️ 删除"))
        self.btn_load.clicked.connect(self._load_preset)
        self.btn_save.clicked.connect(self._save_preset)
        self.btn_delete.clicked.connect(self._delete_preset)
        preset_btns.addWidget(self.btn_load)
        preset_btns.addWidget(self.btn_save)
        preset_btns.addWidget(self.btn_delete)
        preset_layout.addLayout(preset_btns)

        preset_io = QHBoxLayout()
        self.btn_import = QPushButton(t("📥 导入"))
        self.btn_export = QPushButton(t("📤 导出"))
        self.btn_import.clicked.connect(self._import_preset)
        self.btn_export.clicked.connect(self._export_preset)
        preset_io.addWidget(self.btn_import)
        preset_io.addWidget(self.btn_export)
        preset_layout.addLayout(preset_io)

        layout.addWidget(self.preset_group)
        layout.addStretch()
        return widget

    def _create_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        mode_bar = QHBoxLayout()
        self.mode_label = QLabel(t("模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([t("基础模式"), t("高级模式")])
        # This PyQt6 build computes the combo's sizeHint once, from the
        # items added first — setItemText (the live 中文/English switch in
        # retranslate_ui) never re-runs it. Built in Chinese (the shorter
        # text, 48px vs 156px) the combo kept its narrow width in English
        # mode and truncated "Basic Mode" to "Basic Mo…". Pin the minimum
        # width to the longest item across both languages: text width from
        # font metrics, non-text chrome (arrow + margins) measured off the
        # live sizeHint so it tracks the style/DPI.
        _fm = self.mode_combo.fontMetrics()
        _w_text = max(_fm.horizontalAdvance(s)
                      for s in ("基础模式", "高级模式", "Basic Mode", "Advanced Mode"))
        _w_now = max(_fm.horizontalAdvance(self.mode_combo.itemText(i))
                     for i in range(self.mode_combo.count()))
        self.mode_combo.setMinimumWidth(_w_text
                                        + max(0, self.mode_combo.sizeHint().width() - _w_now))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_bar.addWidget(self.mode_label)
        mode_bar.addWidget(self.mode_combo)
        mode_bar.addStretch()
        self.btn_undo = QPushButton(t("↩ 撤销"))
        self.btn_undo.setFixedHeight(28)
        self.btn_undo.clicked.connect(self._undo)
        self.btn_undo.setEnabled(False)
        mode_bar.addWidget(self.btn_undo)
        self.btn_reset = QPushButton(t("🔄 恢复默认"))
        self.btn_reset.setFixedHeight(28)
        self.btn_reset.clicked.connect(self._reset_to_defaults)
        mode_bar.addWidget(self.btn_reset)
        layout.addLayout(mode_bar)

        self.stacked = QWidget()
        self.stacked_layout = QVBoxLayout(self.stacked)
        self.stacked_layout.setContentsMargins(0, 0, 0, 0)

        self.basic_panel = BasicPanel(defaults=self.defaults)
        self.advanced_panel = AdvancedPanel(defaults=self.defaults, chat_templates=self.chat_templates)
        self.advanced_panel.hide()

        self.stacked_layout.addWidget(self.basic_panel)
        self.stacked_layout.addWidget(self.advanced_panel)

        # E11: the parameter area never scrolls vertically. The basic panel
        # carries a hard minimum height equal to its natural height (see
        # BasicPanel._rebuild_quick_toggles), so the window minimum
        # (computed in init_ui) always leaves room for the full panel and
        # rows can never be squashed into overlapping controls. The scroll
        # area is kept for the horizontal direction only: when the window
        # is very narrow (or the left pane is dragged wide), the fixed rows
        # scroll sideways instead of clipping.
        self.panel_scroll = QScrollArea()
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel_scroll.setWidget(self.stacked)
        layout.addWidget(self.panel_scroll)

        # E11 (option A): the viewport is resized *before* the panel's own
        # layout pass, so reacting here lets us re-wrap the quick-toggles
        # grid before any group could be squashed to make room for a new
        # grid row; the minimum re-sync itself is deferred to the next
        # event-loop pass (see _on_quick_wrap_changed).
        self.panel_scroll.viewport().installEventFilter(self)
        self.basic_panel.quick_wrap_changed.connect(self._on_quick_wrap_changed)

        self._update_panel_content_min()

        self.cmd_label = QLabel(t("📝 启动命令预览"))
        self.cmd_label.setStyleSheet("font-weight: bold; color: #7aa2f7; font-size: 13px;")
        layout.addWidget(self.cmd_label)

        self.cmd_preview = QPlainTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setFont(QFont("Consolas", 9))
        self.cmd_preview.setStyleSheet("background: #121212; color: #7ab0e0; border: 1px solid #444; border-radius: 4px; padding: 4px;")
        self.cmd_preview.setFixedHeight(80)
        self.cmd_preview.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.cmd_preview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cmd_preview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.cmd_preview)

        control_bar = QHBoxLayout()
        # One visual language for all four (objectName -> dedicated gradient
        # rule in _THEME_TEMPLATE): same font-size / weight / radius /
        # padding, semantic color per role (green=go, red=stop, slate=aux,
        # blue=service). The #webuiBtn rule used to exist in the QSS but was
        # never applied because no objectName was set — wired up now.
        self.btn_start = QPushButton(t("▶ 启动服务"))
        self.btn_start.setFixedHeight(40)
        self.btn_start.setObjectName("startBtn")
        self.btn_stop = QPushButton(t("■ 停止服务"))
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setObjectName("stopBtn")
        self.btn_copy_cmd = QPushButton(t("📋 复制命令"))
        self.btn_copy_cmd.setFixedHeight(40)
        self.btn_copy_cmd.setObjectName("copyBtn")
        self.btn_webui = QPushButton(t("🌐 打开WebUI"))
        self.btn_webui.setFixedHeight(40)
        self.btn_webui.setObjectName("webuiBtn")


        self.btn_start.clicked.connect(self._start_server)
        self.btn_stop.clicked.connect(self._stop_server)
        self.btn_copy_cmd.clicked.connect(self._copy_command)
        self.btn_webui.clicked.connect(self._open_webui)
        self.btn_stop.setEnabled(False)
        self.btn_webui.setEnabled(False)

        control_bar.addWidget(self.btn_start)
        control_bar.addWidget(self.btn_stop)
        control_bar.addWidget(self.btn_copy_cmd)
        control_bar.addWidget(self.btn_webui)
        control_bar.addStretch()

        # E11: eliding label — the full version string must not pin the
        # window minimum width (see basic_panel.ElidingLabel); the tooltip
        # keeps the full text.
        self.version_label = ElidingLabel(t("🔍 检测中..."))
        f = self.version_label.font()
        f.setPixelSize(12)
        self.version_label.setFont(f)
        pal = self.version_label.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor("#6b7280"))
        self.version_label.setPalette(pal)
        self.version_label.setToolTip(t("llama.cpp 版本信息"))
        self._version_base_tooltip = t("llama.cpp 版本信息")
        control_bar.addWidget(self.version_label)

        # E7: parameter-drift notice promoted from a tooltip to a clickable
        # button — the full drift list opens in a dialog on click
        self._drift_missing = []
        self._drift_changed = []
        self.drift_button = QToolButton()
        self.drift_button.setText("⚠️")
        self.drift_button.setToolTip(t("参数与当前版本存在差异，点击查看完整列表"))
        self.drift_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drift_button.clicked.connect(self._show_drift_dialog)
        self.drift_button.setVisible(False)
        control_bar.addWidget(self.drift_button)

        self.status_indicator = QLabel(t("⏸ 未运行"))
        self.status_indicator.setObjectName("statusStopped")
        self.status_indicator.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 13px;")
        control_bar.addWidget(self.status_indicator)

        self.run_time_label = QLabel(t("⏱ 运行: 00:00"))
        self.run_time_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        control_bar.addWidget(self.run_time_label)

        layout.addLayout(control_bar)

        self.tab_widget = QTabWidget()
        # The bottom log/info tabs carry their own QSS (the log area is always
        # dark in both themes); it must be theme-aware or it overrides the app
        # stylesheet with light colors in dark mode (E5 follow-up).
        self.tab_widget.setStyleSheet(self._bottom_tabs_qss(self.theme))

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 10))
        self.log_output.setStyleSheet("""
            QPlainTextEdit {
                background: #121212;
                color: #cdd6f4;
                border: none;
                padding: 4px;
            }
        """ + _DARK_SCROLLBAR_QSS)
        # Narrow filter views can hold one window per visible level
        self.log_output.document().setMaximumBlockCount(LOG_DOC_MAX_BLOCK_COUNT)

        log_tab = QWidget()
        log_tab_layout = QVBoxLayout(log_tab)
        log_tab_layout.setContentsMargins(0, 0, 0, 0)

        # E3: search bar (hidden until Ctrl+F / the search button)
        self.log_search_bar = QWidget()
        search_layout = QHBoxLayout(self.log_search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)
        self.log_search_edit = QLineEdit()
        self.log_search_edit.setPlaceholderText(t("🔍 搜索日志 (Ctrl+F)"))
        self.log_search_edit.setFixedWidth(240)
        self.btn_log_search_prev = QPushButton("▲")
        self.btn_log_search_next = QPushButton("▼")
        self.btn_log_search_close = QPushButton("✕")
        # objectName selects the #logSearchBtn QSS rule: the theme's generic
        # QPushButton padding (5px 14px) is wider than these 26px buttons,
        # so without zero padding Qt gives the text a zero-width content
        # rect and the ▲/▼/✕ glyphs never render (empty rounded boxes).
        for b in (self.btn_log_search_prev, self.btn_log_search_next, self.btn_log_search_close):
            b.setObjectName("logSearchBtn")
            b.setFixedHeight(24)
            b.setFixedWidth(26)
        self.btn_log_search_prev.setToolTip(t("上一个"))
        self.btn_log_search_next.setToolTip(t("下一个"))
        self.btn_log_search_close.setToolTip(t("关闭搜索"))
        self.btn_log_search_prev.clicked.connect(lambda: self._log_search_find(False))
        self.btn_log_search_next.clicked.connect(lambda: self._log_search_find(True))
        self.btn_log_search_close.clicked.connect(self._hide_log_search)
        self.log_search_edit.returnPressed.connect(lambda: self._log_search_find(True))
        QShortcut(QKeySequence.StandardKey.Cancel, self.log_search_edit, activated=self._hide_log_search)
        self.log_search_edit.installEventFilter(self)
        self.log_search_label = QLabel("")
        search_layout.addWidget(self.log_search_edit)
        search_layout.addWidget(self.btn_log_search_prev)
        search_layout.addWidget(self.btn_log_search_next)
        search_layout.addWidget(self.log_search_label)
        search_layout.addWidget(self.btn_log_search_close)
        search_layout.addStretch()
        self.log_search_bar.hide()

        log_toolbar = QHBoxLayout()
        # E3: log-level filter (F lines count as E)
        self._log_level_boxes = {}
        filter_box = QHBoxLayout()
        filter_box.setSpacing(8)
        for lvl, name in (("D", t("调试")), ("I", t("信息")), ("W", t("警告")), ("E", t("错误"))):
            box = QCheckBox(name)
            box.setChecked(True)
            box.setToolTip(name)
            box.toggled.connect(self._on_log_level_toggled)
            filter_box.addWidget(box)
            self._log_level_boxes[lvl] = box
        log_toolbar.addLayout(filter_box)
        log_toolbar.addStretch()
        self.btn_clear_log = QPushButton(t("🗑️ 清空"))
        self.btn_clear_log.setFixedHeight(28)
        self.btn_clear_log.clicked.connect(self._clear_log)
        self.btn_export_log = QPushButton(t("💾 导出"))
        self.btn_export_log.setFixedHeight(28)
        self.btn_export_log.clicked.connect(self._export_log)
        self.chk_auto_scroll = QCheckBox(t("📜 自动滚动"))
        self.chk_auto_scroll.setChecked(True)
        log_toolbar.addWidget(self.btn_clear_log)
        log_toolbar.addWidget(self.btn_export_log)
        log_toolbar.addWidget(self.chk_auto_scroll)
        log_tab_layout.addWidget(self.log_output)
        log_tab_layout.addWidget(self.log_search_bar)
        log_tab_layout.addLayout(log_toolbar)

        # E3: window-level Ctrl+F opens the log search (switches to log tab)
        self._log_search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self._log_search_shortcut.activated.connect(self._show_log_search)

        self.info_display = QTextEdit()
        self.info_display.setReadOnly(True)
        self.info_display.setFont(QFont("Consolas", 10))
        self.info_display.setStyleSheet("""
            QTextEdit {
                background: #121212;
                color: #cdd6f4;
                border: none;
                padding: 8px;
            }
        """ + _DARK_SCROLLBAR_QSS)
        self.info_display.setHtml(empty_info_html())

        self.tab_widget.addTab(log_tab, t("📄 日志输出"))
        self.tab_widget.addTab(self.info_display, t("📊 运行信息"))
        layout.addWidget(self.tab_widget, 1)

        return widget

    def _sync_panel_min(self):
        """E11: keep the scrollable parameter area — and the window
        minimum — in sync with the content's hard minimums.

        QScrollArea does not propagate its content's minimum *height* to
        its own (it just squashes widgetResizable content), so the scroll
        area is given an explicit minimum height equal to the basic
        panel's hard minimum height (which equals the panel's natural
        height — see BasicPanel._rebuild_quick_toggles). Together with the
        live window minimum (the static MIN_WINDOW_* floors can be below
        what the content needs on this font/DPI — the old 1100x700
        minimum was, which is exactly what let the window shrink into
        overlapping controls), the window can never be resized into a
        state that squashes the rows.
        """
        self._update_panel_content_min()
        # The panel's natural height depends on the resolved font, so re-pin
        # it from the live layout every time (construction-time value is an
        # approximation; after the first show it is the real one).
        self.basic_panel.resync_min_height()
        new_min = self.basic_panel.minimumHeight() + 2
        changed = new_min != self.panel_scroll.minimumHeight()
        self.panel_scroll.setMinimumHeight(new_min)
        hint = self.minimumSizeHint()
        # The window minimum height is computed directly as the sum of the
        # right column's children minimums (+ menu/status bars, central
        # margins) rather than from minimumSizeHint(): the hint
        # under-reports the scroll area's explicit minimum, and a QVBox
        # with a stretchy log-tab area squashes the scroll area (the
        # most-expandable child) before the window is tall enough for the
        # full panel.
        right = self.panel_scroll.parentWidget().layout()
        cm = self.centralWidget().layout().contentsMargins()
        min_h = (right.minimumSize().height()
                 # E12: the menu-widget slot now carries title bar + menu
                 # bar (self._top_bar); menuBar() is null once a menu
                 # widget is set.
                 + self._top_bar.sizeHint().height()
                 + self.statusBar().sizeHint().height()
                 + cm.top() + cm.bottom())
        # The window minimum WIDTH is computed the same way (explicitly, not
        # from hint.width()): the scroll area's own minimum includes the
        # quick-toggles grid's *current column count* minimum — a moving
        # target that self-locks the window wide (a 1-row grid keeps the
        # window wide enough to stay a 1-row grid, so the re-wrap that
        # would raise the height minimum never happens). The scroll area
        # contributes its fixed-content minimum instead; the grid re-wraps
        # as the viewport narrows (see BasicPanel._quick_cols) and the
        # re-wrap re-syncs this minimum.
        left_w = self.splitter.widget(0).minimumSize().width()
        right_w = 0
        for i in range(right.count()):
            item = right.itemAt(i)
            wdt = (self._panel_fixed_min_width
                   if item.widget() is self.panel_scroll
                   else item.minimumSize().width())
            right_w = max(right_w, wdt)
        # handleWidth() is -1 until the splitter's first layout — floor it
        # so the pre-layout sync cannot pin a too-small minimum.
        # E13: + the central area's left/right shadow-band insets.
        min_w = (left_w + max(self.splitter.handleWidth(), 10) + right_w
                 + 2 * CARD_CONTENT_INSET)
        self.setMinimumSize(
            max(MIN_WINDOW_WIDTH, min_w),
            max(MIN_WINDOW_HEIGHT, min_h, hint.height()),
        )
        if changed:
            # Qt's layout-minimum caches settle one event-loop pass after a
            # grid re-wrap (inside a resize cascade the just-rewrapped
            # layout still reports its previous minimum). Re-sync once more
            # so the window minimum sees the true content minimum; the
            # changed-flag makes this converge (no repeated resyncs).
            QTimer.singleShot(0, self._sync_panel_min)

    def _update_panel_content_min(self):
        """E11: hard minimum width for the scrollable panel content.

        It is the widest of the *fixed* groups (model / sampling / server),
        deliberately not the panel's full layout minimum: the quick-toggles
        grid wraps on its own (see BasicPanel._quick_cols) and its minimum
        depends on the current column count — a moving target that would
        freeze the window minimum at whatever width the grid last had. Below
        this width the fixed rows would clip at the group edges; with it,
        a horizontal scrollbar appears instead and nothing is clipped.
        """
        bp = self.basic_panel
        w = 0
        for group in (bp._model_group, bp._sampling_group, bp._server_group):
            w = max(w, group.minimumSizeHint().width())
        margins = bp.layout().contentsMargins()
        stacked_min = w + margins.left() + margins.right()
        self._panel_fixed_min_width = stacked_min
        self.stacked.setMinimumWidth(stacked_min)
        # The scroll area has no frame and no vertical scrollbar (E11), so
        # its viewport width equals its own width: the window minimum
        # (computed from this in _sync_panel_min) leaves a viewport that
        # already fits the panel — no horizontal scrollbar at the smallest
        # size.
        self.panel_scroll.setMinimumWidth(stacked_min)

    def _connect_signals(self):
        self.runner.log_output.connect(self._append_log)
        self.runner.state_changed.connect(self._on_state_changed)
        self.runner.error_occurred.connect(self._on_error)
        self.basic_panel.chk_webui.stateChanged.connect(self._update_webui_button)
        self.advanced_panel.adv_webui.stateChanged.connect(self._update_webui_button)
        self.basic_panel.ctx_spin.valueChanged.connect(self._update_model_info)
        self.advanced_panel.adv_ctx_size.valueChanged.connect(self._update_model_info)
        self._update_cmd_preview()
        self.btn_webui.setEnabled(False)

    def _on_model_selected(self, path):
        if self.is_advanced:
            self.advanced_panel.adv_model.setText(path)
        else:
            idx = self.basic_panel.model_combo.findText(path)
            if idx == -1:
                self.basic_panel.model_combo.addItem(path)
            self.basic_panel.model_combo.setCurrentText(path)
        self._update_model_info()

    def _on_mmproj_selected(self, path):
        if self.is_advanced:
            self.advanced_panel.adv_mmproj.setText(path)
        else:
            idx = self.basic_panel.mmproj_combo.findText(path)
            if idx == -1:
                self.basic_panel.mmproj_combo.addItem(path)
            self.basic_panel.mmproj_combo.setCurrentText(path)
        self._update_model_info()

    def _on_mode_changed(self, index):
        target_advanced = (index == 1)
        if target_advanced == self.is_advanced:
            return
        self.preview_timer.stop()
        self._mode_switching = True
        self._save_current_to_params(force=True)
        self.is_advanced = target_advanced
        if self.is_advanced:
            self.basic_panel.hide()
            self.advanced_panel.show()
        else:
            self.advanced_panel.hide()
            self.basic_panel.show()
        self._apply_params_to_current()
        self._mode_switching = False
        self.preview_timer.start(PREVIEW_TIMER_MS)
        self._update_cmd_preview()

    def _save_current_to_params(self, force=False):
        if not force and (self._mode_switching or self._applying_values):
            return
        if self.is_advanced:
            self.params.update(self.advanced_panel.get_values())
        else:
            basic_vals = self.basic_panel.get_values()
            for k, v in basic_vals.items():
                self.params[k] = v

    def _save_params_snapshot(self):
        self._save_current_to_params()
        if self.params != self._last_saved:
            self.params_history.append(dict(self.params))
            if len(self.params_history) > self.max_history:
                self.params_history.pop(0)
            self._last_saved = dict(self.params)
            self.btn_undo.setEnabled(len(self.params_history) > 1)

    def _undo(self):
        if len(self.params_history) > 1:
            self.params_history.pop()
            self.params = dict(self.params_history[-1])
            self._apply_params_to_current()
            # Sync _last_saved and drop the pending flag; otherwise the 300ms debounce
            # snapshot treats the post-undo state as a new change, appends a duplicate
            # snapshot, and re-enables the undo button ("ghost step")
            self._last_saved = dict(self.params)
            self._pending_snapshot = False
            self.btn_undo.setEnabled(len(self.params_history) > 1)
            self.statusBar().showMessage(t("已撤销"), 2000)

    def _apply_params_to_current(self):
        # 应用期间屏蔽信号回读：set_values 逐个改控件时 valueChanged 会触发
        # _update_model_info → _get_current_values，读到半更新的控件状态并写回
        # params，把混合状态污染进 undo 历史
        self._applying_values = True
        try:
            if self.is_advanced:
                self.advanced_panel.set_values(self.params)
            else:
                self.basic_panel.set_values(self.params)
        finally:
            self._applying_values = False

    def _get_current_values(self):
        self._save_current_to_params()
        return dict(self.params)

    def _set_current_values(self, values):
        self.params.update(values)
        self._apply_params_to_current()

    def _build_args_from_params(self):
        return self.cmd_builder.build(self.params)

    def _update_cmd_preview(self):
        if self._mode_switching:
            return
        self._save_current_to_params()
        changed = self.params != self._last_saved
        if changed and not self._pending_snapshot:
            self._pending_snapshot = True
            self._undo_debounce.start(UNDO_DEBOUNCE_MS)
        args = self._build_args_from_params()
        # E1: show the real executable (configured path > PATH); cached, no IO per tick
        cmd_path = quote_arg(get_server_path())
        new_text = cmd_path + (" " + " ".join(quote_arg(a) for a in args) if args else "")
        # B1: only touch the widget when the text actually changed — rebuilding
        # the document on every 300ms tick forced pointless relayout/repaints
        if new_text != self.cmd_preview.toPlainText():
            self.cmd_preview.setPlainText(new_text)

    def hideEvent(self, event):
        # B1: a hidden window can't be interacted with — pause the poll
        self.preview_timer.stop()
        super().hideEvent(event)

    def _apply_pending_splitter(self):
        # E2: apply the saved left panel width to the splitter. The saved
        # (left, right) pair may not fit the current window width, so keep
        # the left width as-is (if within min/max) and let the right panel
        # take the remainder. Returns True if applied. Called from
        # showEvent (via _retry_pending_splitter) until the first layout
        # pass gives the splitter its real width.
        left = getattr(self, "_pending_splitter_left", None)
        if left is None:
            return False
        total = self.splitter.width()
        if total <= left + 100:
            return False
        self.splitter.setSizes([left, max(100, total - left)])
        # Verify Qt honored the request: in a narrow window the right
        # panel's layout minimum (its QTabWidget / log area) can squeeze
        # the left one back down to its minimum. In that case keep the
        # pending value and retry (the window may still be growing).
        actual = self.splitter.sizes()[0]
        if abs(actual - left) <= 20:
            self._pending_splitter_left = None
            return True
        return False

    def _retry_pending_splitter(self, tries):
        if getattr(self, "_pending_splitter_left", None) is None:
            return
        if self._apply_pending_splitter():
            return
        if tries > 0:
            QTimer.singleShot(16, lambda: self._retry_pending_splitter(tries - 1))

    def showEvent(self, event):
        super().showEvent(event)
        # E14: re-apply the intended size once, now that the window is
        # visible — a pre-show resize()/restoreGeometry() is silently
        # discarded once the E11 content minimums are applied during
        # construction, so without this the app opens at exactly its
        # minimum size (cramped on 1080p+ screens). Saved geometry wins
        # (and is re-clamped to the screen below); first launch gets the
        # default size + 400px left panel.
        if not self._first_show_done:
            self._first_show_done = True
            if self._pending_geometry is not None:
                # Synchronous at show time: the window (and the splitter's
                # width) are at final size immediately, so the saved-splitter
                # re-apply below lands on the right total.
                self.setGeometry(self._pending_geometry)
            elif self._pending_geometry_raw is not None:
                self.restoreGeometry(self._pending_geometry_raw)
            else:
                self.resize(self._default_w, self._default_h)
                self.splitter.setSizes(
                    self._default_splitter_sizes(self.width()))
        self._retry_pending_splitter(8)
        # E13: a stale saved geometry can restore the window off-screen
        # before the first Move event arrives — clamp once on show.
        self._clamp_to_screen()
        # E11: re-sync the hard minimums once the font/layout has settled
        # (the construction-time value is an approximation). The 0ms timer
        # catches the first full layout pass; direct call covers the rest.
        self._post_show_panel_resync()
        QTimer.singleShot(0, self._post_show_panel_resync)
        if not self.preview_timer.isActive():
            self.preview_timer.start(PREVIEW_TIMER_MS)
            self._update_cmd_preview()

    def _post_show_panel_resync(self):
        # E11: the grid's wrap depends on the resolved font (slot minimum
        # widths), so re-run the wrap decision and re-sync afterwards.
        self.basic_panel._arrange_quick_toggles()
        self._sync_panel_min()

    def _on_quick_wrap_changed(self, rows):
        """E11 (option A): the quick-toggles grid just re-wrapped (inside
        the viewport's resize event, before the panel's own layout pass),
        so re-syncing here — with the grid's explicit minimum already live —
        updates the window minimum in the same pass: the window grows if
        the new row no longer fits, and no group is ever squashed to make
        room for it."""
        self._sync_panel_min()

    def _flush_snapshot(self):
        self._save_current_to_params()
        if self.params != self._last_saved:
            self.params_history.append(dict(self.params))
            if len(self.params_history) > self.max_history:
                self.params_history.pop(0)
            self._last_saved = dict(self.params)
            self.btn_undo.setEnabled(len(self.params_history) > 1)
        self._pending_snapshot = False

    def _start_server(self):
        v = self._get_current_values()
        if not v.get("model"):
            ThemedMessageBox.warning(self, t("警告"), t("请选择一个模型文件"))
            return False

        model_path = v["model"]
        # A8: llama-server resolves relative paths against the process work_dir
        # (the exe directory in frozen mode), so the existence check must use
        # the same base rather than the launcher's CWD.
        model_file = Path(model_path)
        if not model_file.is_absolute():
            model_file = self.work_dir / model_file
        if not model_file.exists():
            ThemedMessageBox.warning(self, t("警告"), t("模型文件不存在:\n{model_path}", model_path=model_path))
            return False

        host = v.get('host', '127.0.0.1')
        port = v.get("port", 8080)
        # A7: probe the host that will actually be bound. 0.0.0.0/:: accept
        # loopback connections, so 127.0.0.1 is the right probe target then.
        check_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        if self._is_port_in_use(port, check_host):
            reply = ThemedMessageBox.question(
                self, t("端口占用"),
                t("端口 {port} 可能已被占用，是否继续？", port=port),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return False

        args = self._build_args_from_params()
        cmd_path = quote_arg(get_server_path())
        cmd_str = cmd_path + (" " + " ".join(quote_arg(a) for a in args) if args else "")
        timestamp = datetime.now().strftime('%H:%M:%S')
        # E3: banners go through the record system so they survive filter
        # rebuilds; the full run log captures the command + every line
        self._open_run_log(cmd_str)
        self._log_banner(f'<span style="color: #89b4fa;">[{timestamp}] {t("启动命令:")}</span>')
        self._log_banner(
            f'<span style="color: #a6e3a1;">  {html_mod.escape(cmd_str)}</span>'
        )
        self._log_banner("")

        self.runner.start(args, work_dir=str(self.work_dir))
        msg = t("🔄 正在启动服务: http://{host}:{port}", host=host, port=port)
        if host == "0.0.0.0":
            msg += t("  ⚠️ 监听所有网卡，局域网可访问")
        self.statusBar().showMessage(msg)
        return True

    def _stop_server(self):
        self.runner.stop()
        self._close_run_log()
        self.timer.stop()
        self.run_time_label.setText(t("⏱ 运行: 00:00"))

    def _copy_command(self):
        self._save_current_to_params()
        args = self._build_args_from_params()
        cmd_path = quote_arg(get_server_path())
        cmd = cmd_path + (" " + " ".join(quote_arg(a) for a in args) if args else "")
        QApplication.clipboard().setText(cmd)
        self.statusBar().showMessage(t("命令已复制到剪贴板"), 2000)

    def _open_webui(self):
        url = self._get_web_address()
        v = self._get_current_values()
        if not v.get("webui", True):
            ThemedMessageBox.warning(self, t("WebUI未启用"), t("当前配置已关闭WebUI (--no-webui)，请在设置中启用后再打开。"))
            return
        if not self.runner.is_running:
            reply = ThemedMessageBox.question(
                self, t("服务未运行"),
                t("服务尚未启动，是否先启动服务并打开 WebUI？\n\n地址: {url}", url=url),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._open_webui_on_ready(url)
            return
        webbrowser.open(url)
        self.statusBar().showMessage(t("已在浏览器中打开: {url}", url=url), 3000)

    def _open_webui_on_ready(self, url):
        self._pending_webui_url = url
        self.runner.server_ready.connect(self._on_server_ready_for_webui)
        if not self._start_server():
            # 启动被拦下（未选模型/文件不存在/端口冲突选否）时撤掉连接，
            # 否则下次正常启动会意外打开浏览器
            self._cancel_pending_webui()

    def _on_server_ready_for_webui(self):
        if self._pending_webui_url is None:
            return
        url = self._pending_webui_url
        self._cancel_pending_webui()
        webbrowser.open(url)
        self.statusBar().showMessage(t("已在浏览器中打开: {url}", url=url), 3000)

    def _cancel_pending_webui(self):
        self._pending_webui_url = None
        try:
            self.runner.server_ready.disconnect(self._on_server_ready_for_webui)
        except TypeError:
            pass

    def _on_state_changed(self, state):
        self._current_state = state
        if state == "starting":
            self.status_indicator.setText(t("🔄 启动中..."))
            self.status_indicator.setStyleSheet("color: #d97706; font-weight: bold; font-size: 13px;")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_webui.setEnabled(False)
        elif state == "running":
            self.status_indicator.setText(t("🟢 运行中"))
            self.status_indicator.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 13px;")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.start_time = datetime.now()
            self.timer.start(1000)
            self.statusBar().showMessage(t("🚀 服务已启动: {url}", url=self._get_web_address()))
            self._update_webui_button()
        elif state == "stopped":
            self._flush_log_tail()
            self._close_run_log()
            self._cancel_pending_webui()
            self.status_indicator.setText(t("⏸ 已停止"))
            self.status_indicator.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 13px;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_webui.setEnabled(False)
            self._reset_runtime_state()
            self.statusBar().showMessage(t("⏹ 服务已停止"))
        elif state == "error":
            self._flush_log_tail()
            self._close_run_log()
            self._cancel_pending_webui()
            self.status_indicator.setText(t("🔴 错误"))
            self.status_indicator.setStyleSheet("color: #dc2626; font-weight: bold; font-size: 13px;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_webui.setEnabled(False)
            self._reset_runtime_state()
            self.statusBar().showMessage(t("❌ 服务异常退出"))

    def _reset_runtime_state(self):
        self.timer.stop()
        self.start_time = None
        self._runtime_info = {}
        self.run_time_label.setText(t("⏱ 运行: 00:00"))
        self.info_display.setHtml(empty_info_html())

    def _get_web_address(self):
        v = self._get_current_values()
        host = v.get("host", "127.0.0.1")
        port = v.get("port", 8080)
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        return f"http://{display_host}:{port}"

    def _update_webui_button(self):
        v = self._get_current_values()
        if self.runner.is_ready and v.get("webui", True):
            self.btn_webui.setEnabled(True)
        else:
            self.btn_webui.setEnabled(False)

    def _on_error(self, msg):
        ThemedMessageBox.critical(self, t("错误"), msg)
        self.statusBar().showMessage(t("❌ 启动失败: {msg}", msg=msg[:80]))

    def _append_log(self, text, stream="out"):
        # QProcess 的读取块不保证按行对齐，最后一个元素可能是未写完的半行，
        # 按流挂起拼到下一个块，否则跨块的一行会被切成两半解析；跨流粘行
        # 会把两个逻辑行合成一行（后一行的级别前缀被吞掉）
        text = self._log_tails.get(stream, "") + text
        self._log_tails[stream] = ""
        if not text:
            return
        lines = text.split("\n")
        self._log_tails[stream] = lines.pop()
        for line in lines:
            self._append_log_line(line)
        # B2: schedule a batched render (auto-scroll happens in the flush)
        if self._log_html and not self._log_flush_timer.isActive():
            self._log_flush_timer.start(100)

    def _append_log_line(self, line):
        # B2: parse immediately (runtime info must stay fresh), but only buffer
        # the rendered HTML — the 100ms timer inserts it in one go.
        # E3: also record the level (for the filter) and mirror every line
        # into the full per-run log file.
        self._log_html.append((line_level(line), colorize_log_line(line)))
        self._parse_log_line(line.strip())
        self._run_log_write(line)

    def _log_banner(self, html):
        # E3: banners go through the record system (level None = shown only
        # in the unfiltered view, like other prefix-less lines) so they
        # survive level-filter rebuilds
        self._log_html.append((None, html))
        self._flush_log_buffer()

    def _ingest_log_record(self, rec):
        """Move one rendered (level, html) record into the histories: the
        shared global window (serves the all-on view) plus the record's own
        per-level window (serves the narrow filter views)."""
        self._log_records.append(rec)
        self._level_histories[rec[0]].append((self._log_seq, rec))
        self._log_seq += 1

    def _flush_log_buffer(self):
        if not self._log_html:
            return
        batch, self._log_html = self._log_html, []
        enabled = {lvl for lvl, b in self._log_level_boxes.items() if b.isChecked()}
        active = self._log_filter_active()
        # One block per line (appendHtml), never one giant <br>-joined block:
        # (1) a batch appended right after the previous one used to glue the
        #     last line of batch N to the first line of batch N+1;
        # (2) a single growing block defeats setMaximumBlockCount, so the
        #     document grew without bound and relayout cost grew with time.
        # The document already mirrors the (filtered) view — fully rebuilt on
        # every filter toggle — so only the batch's visible lines are
        # appended; a full clear+reinsert per 100 ms tick froze the UI in
        # verbose runs (O(visible records) per tick).
        for rec in batch:
            lvl = rec[0]
            # per-level front eviction: this line pushing the level past its
            # window means the level's oldest visible line leaves the
            # document right now (it is the front of that level's block
            # queue) instead of lingering until the next filter toggle
            evicted = len(self._level_histories[lvl]) == LOG_MAX_BLOCK_COUNT
            self._ingest_log_record(rec)
            if self._log_level_visible(lvl, enabled):
                self.log_output.appendHtml(rec[1])
                if active:
                    self._doc_blocks[lvl].append(
                        self.log_output.document().lastBlock()
                    )
                    if evicted:
                        self._drop_front_doc_block(lvl)
        if len(self._log_records) > LOG_MAX_BLOCK_COUNT:
            del self._log_records[:len(self._log_records) - LOG_MAX_BLOCK_COUNT]
            if not active:
                # All-on: the global window's front is the document's front,
                # so a front-trim keeps doc == global window in sync
                self._trim_log_document(enabled)
        if self.chk_auto_scroll.isChecked():
            self._log_scroll_to_bottom()

    def _drop_front_doc_block(self, lvl):
        dq = self._doc_blocks[lvl]
        while dq and not dq[0].isValid():
            dq.popleft()
        if not dq:
            return
        self._remove_doc_block(dq.popleft())

    def _remove_doc_block(self, block):
        """Remove one (middle or last) block, merging it out of the document
        without disturbing the others."""
        doc = self.log_output.document()
        second = block.next()
        if second.isValid():
            start, end = block.position(), second.position()
        else:
            prev = block.previous()
            if not prev.isValid():
                return  # the document's only block: keep it
            start = prev.position() + prev.length()
            end = block.position() + block.length()
        cur = QTextCursor(doc)
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()

    def _trim_log_document(self, enabled):
        """All-on view only: drop front blocks for records the shared global
        window already evicted, so they don't linger in the document until
        the next filter toggle (which would read as “toggling the switch
        makes log lines disappear”). Under an active filter the document is
        kept in sync per level instead (see _drop_front_doc_block)."""
        target = sum(
            1 for lvl, _ in self._log_records
            if self._log_level_visible(lvl, enabled)
        )
        doc = self.log_output.document()
        to_drop = doc.blockCount() - target
        if to_drop <= 0:
            return
        keep = QTextCursor.MoveMode.KeepAnchor
        for _ in range(to_drop):
            first = doc.firstBlock()
            second = first.next()
            if not second.isValid():
                break
            cur = QTextCursor(doc)
            cur.setPosition(first.position())
            cur.setPosition(second.position(), keep)
            cur.removeSelectedText()

    # ---------- E3: level filter / search / full run log ----------

    def _log_filter_active(self):
        return not all(b.isChecked() for b in self._log_level_boxes.values())

    def _on_log_level_toggled(self):
        # Always rebuild from the records: the fast path only appends new
        # lines, so it cannot restore lines an earlier filter hid
        self._rebuild_log_view()

    def _log_level_visible(self, level, enabled):
        # Non-level lines — the launcher banners and server lines without a
        # level prefix (blank lines, raw model I/O dumps) — are shown only in
        # the unfiltered view (all level boxes on). When a specific level
        # filter is active they are hidden so each category view stays clean;
        # "all unchecked" is also empty. F (fatal) lines follow E (error).
        if level is None:
            return len(enabled) == len(self._log_level_boxes)
        return level in enabled or (level == "F" and "E" in enabled)

    def _rebuild_log_view(self):
        """Full re-render of the (filtered) document. One-shot cost, only on
        filter toggles — steady-state flushing appends incrementally.

        All-on: re-render from the shared global window (unchanged).
        Narrow: merge the visible levels' own history windows in stream
        order — rendering from the shared window alone would show only the
        few visible lines that happen to sit inside its last-5000-lines
        slice, which a flood of hidden levels (debug at -lv 5, prompt
        dumps) can shrink to a single line.
        """
        if self._log_html:
            for rec in self._log_html:
                self._ingest_log_record(rec)
            self._log_html = []
        if len(self._log_records) > LOG_MAX_BLOCK_COUNT:
            del self._log_records[:len(self._log_records) - LOG_MAX_BLOCK_COUNT]
        enabled = {lvl for lvl, b in self._log_level_boxes.items() if b.isChecked()}
        active = self._log_filter_active()
        stick = self.chk_auto_scroll.isChecked() and self._log_at_bottom()
        self.log_output.clear()
        for lvl in self._doc_blocks:
            self._doc_blocks[lvl].clear()
        if active:
            # per-level deques are seq-ordered; k-way merge keeps stream order
            pools = [
                self._level_histories[lvl] for lvl in self._level_histories
                if self._log_level_visible(lvl, enabled)
            ]
            for _seq, rec in heapq.merge(*pools):
                lvl, h = rec
                self.log_output.appendHtml(h)
                self._doc_blocks[lvl].append(
                    self.log_output.document().lastBlock()
                )
        else:
            for lvl, h in self._log_records:
                self.log_output.appendHtml(h)
        if stick:
            self._log_scroll_to_bottom()

    def _log_at_bottom(self):
        sb = self.log_output.verticalScrollBar()
        return sb.value() >= sb.maximum() - 1

    def _log_scroll_to_bottom(self):
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _show_log_search(self):
        if self.tab_widget.currentIndex() != 0:
            self.tab_widget.setCurrentIndex(0)
        self.log_search_bar.show()
        self.log_search_edit.setFocus()
        self.log_search_edit.selectAll()

    def _hide_log_search(self):
        self.log_search_bar.hide()

    def _log_search_find(self, forward=True):
        text = self.log_search_edit.text()
        if not text:
            return
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        found = self.log_output.find(text, flags)
        if not found:
            # Wrap around: find() never crosses the start/end, so after a
            # miss retry from the opposite end (cursor is usually at the
            # end of the log right after new lines are appended)
            cursor = self.log_output.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.Start if forward
                else QTextCursor.MoveOperation.End
            )
            self.log_output.setTextCursor(cursor)
            found = self.log_output.find(text, flags)
        if found:
            self.log_search_label.setStyleSheet("")
            self.log_search_label.setText(t("{n} 处匹配", n=self._log_search_count(text)))
        else:
            self.log_search_label.setStyleSheet("color: #dc2626;")
            self.log_search_label.setText(t("未找到"))

    def _log_search_count(self, text):
        needle = text.lower()
        count = 0
        block = self.log_output.document().firstBlock()
        while block.isValid():
            count += block.text().lower().count(needle)
            block = block.next()
        return count

    def eventFilter(self, obj, event):
        # E13: window-state flips (Win+Up, Aero Snap, taskbar button) —
        # collapse / restore the card band and repaint the chrome.
        if obj is self and event.type() == QEvent.Type.WindowStateChange:
            self._on_card_state_changed()
        # E13: top-level position changes arrive as Move in this PyQt6
        # build — keep the title-bar row on-screen (frameless windows
        # have no caption for the WM to constrain).
        elif obj is self and event.type() == QEvent.Type.Move:
            self._clamp_to_screen()
        # E11 (option A): the panel viewport is resized before the panel's
        # own layout pass — re-wrapping the quick-toggles grid here (and
        # re-syncing the hard minimums via quick_wrap_changed) means an
        # extra grid row never has to borrow height from the other groups.
        if obj is self.panel_scroll.viewport() and \
                event.type() == QEvent.Type.Resize:
            self.basic_panel._arrange_quick_toggles()
        # E3: Shift+Enter in the search box searches backwards.
        # PyQt6 enums are class-scoped — QKeyEvent instances do not carry
        # Key/Modifier/Type (that PyQt5-style access raises AttributeError
        # on the first keypress in the search box).
        if obj is self.log_search_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and \
                    (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._log_search_find(False)
                return True
        return super().eventFilter(obj, event)

    def _open_run_log(self, command):
        self._close_run_log()
        self._run_log_failed = False
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            # Line-buffered: a crash must not lose the tail of the log —
            # the file exists for post-mortem inspection
            self._run_log_file = open(LAST_RUN_LOG, "w", encoding="utf-8", buffering=1)
            self._run_log_file.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] $ {command}\n")
        except OSError:
            self._run_log_file = None

    def _close_run_log(self):
        if self._run_log_file is not None:
            try:
                self._run_log_file.close()
            except OSError:
                pass
            self._run_log_file = None

    def _run_log_write(self, line):
        if self._run_log_file is None or self._run_log_failed:
            return
        try:
            self._run_log_file.write(line + "\n")
        except (OSError, ValueError):
            # Disk problems must never break the UI; stop mirroring for this run
            self._run_log_failed = True
            self._close_run_log()

    def _flush_log_tail(self):
        # 进程结束时各流最后一个块可能没有换行，把挂起的半行补显出来
        flushed = False
        for stream, line in list(self._log_tails.items()):
            if line:
                self._log_tails[stream] = ""
                self._append_log_line(line)
                flushed = True
        if flushed:
            self._flush_log_buffer()  # final line shows up immediately on stop/error

    def _parse_log_line(self, line):
        if parse_log_line(line, self._runtime_info):
            self._update_info_display()


    def _update_info_display(self):
        self.info_display.setHtml(build_info_html(self._runtime_info))

    def _clear_log(self):
        self._log_html = []
        self._log_records = []
        for lvl in self._level_histories:
            self._level_histories[lvl].clear()
            self._doc_blocks[lvl].clear()
        self.log_output.clear()

    def _export_log(self):
        self._flush_log_buffer()  # don't miss the last <100ms of lines
        source = "view"
        if LAST_RUN_LOG.exists() and LAST_RUN_LOG.stat().st_size > 0:
            full_lines = self._count_log_lines(LAST_RUN_LOG)
            view_lines = self.log_output.document().blockCount()
            if full_lines > view_lines:
                choice = self._ask_export_scope(full_lines, view_lines)
                if choice is None:
                    return
                source = choice
        path, _ = QFileDialog.getSaveFileName(self, t("导出日志"), "", "Text Files (*.txt)")
        if not path:
            return
        try:
            if source == "full":
                shutil.copyfile(LAST_RUN_LOG, path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.log_output.toPlainText())
            self.statusBar().showMessage(t("日志已导出: {path}", path=path), 3000)
        except (OSError, IOError) as e:
            ThemedMessageBox.warning(self, t("错误"), str(e))

    @staticmethod
    def _count_log_lines(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def _ask_export_scope(self, full_lines, view_lines):
        """E3: choose between the visible (truncated) area and the full run log."""
        box = ThemedMessageBox(self)
        box.setWindowTitle(t("导出日志"))
        box.setText(t("选择要导出的日志范围"))
        btn_view = box.addButton(
            t("仅显示区（最近 {n} 行）", n=view_lines), QMessageBox.ButtonRole.ActionRole)
        btn_full = box.addButton(
            t("完整日志（{n} 行）", n=full_lines), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(t("取消"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()  # don't leave a hidden top-level behind
        if clicked is btn_view:
            return "view"
        if clicked is btn_full:
            return "full"
        return None

    def _update_timer(self):
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            self.run_time_label.setText(t("⏱ 运行: {mins}:{secs}", mins=f"{mins:02d}", secs=f"{secs:02d}"))

    def _refresh_presets(self, select_name=None):
        # E6: keep the current selection where possible, attach the creation
        # time of each preset as a tooltip, and hint the selected one in the
        # status bar (the combo itself only shows names)
        presets = self.config.list_presets()
        names = [p["name"] for p in presets]
        prev = self.preset_combo.currentText()
        target = select_name if select_name in names else (prev if prev in names else "")
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        model = self.preset_combo.model()
        for i, p in enumerate(presets):
            self.preset_combo.addItem(p["name"])
            model.setData(
                model.index(i, 0),
                t("创建时间: {created}", created=self._format_created(p["created"])),
                Qt.ItemDataRole.ToolTipRole,
            )
        self.preset_combo.setCurrentIndex(
            names.index(target) if target else -1)
        self.preset_combo.blockSignals(False)
        self._show_preset_created_hint()

    @staticmethod
    def _format_created(iso_ts):
        try:
            return datetime.fromisoformat(iso_ts).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(iso_ts or "?")

    def _show_preset_created_hint(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        for p in self.config.list_presets():
            if p["name"] == name:
                self.statusBar().showMessage(
                    t("预设 {name} · 创建于 {created}",
                      name=name, created=self._format_created(p["created"])), 3000)
                break

    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        # C3: load_preset returns the merged params (ConfigManager holds no
        # state); it returns False (not None) on failure, so guard both
        params = self.config.load_preset(name)
        if not params:
            return
        if isinstance(params, dict):
            save_last_preset(name)  # remember for the next startup
            # A9: presets often travel between machines — clear machine-local
            # paths that do not exist here instead of starting with broken ones
            missing = []
            for key in ("model", "mmproj"):
                path_val = params.get(key) or ""
                if not path_val:
                    continue
                resolved = Path(path_val)
                if not resolved.is_absolute():
                    resolved = self.work_dir / resolved
                if not resolved.exists():
                    params[key] = ""
                    missing.append(key)
            self._set_current_values(params)
            self._update_cmd_preview()
            if missing:
                self.statusBar().showMessage(
                    t("预设 {name} 中 {keys} 在本机不存在，已清空相应字段",
                      name=name, keys=", ".join(missing)), 8000)
            else:
                self.statusBar().showMessage(t("已加载预设: {name}", name=name), 2000)

    def _restore_last_preset(self):
        """Restore the last loaded preset on startup (E9).

        Silently skipped when no preset was ever loaded, the preset was
        deleted, or loading fails — startup must never break on this. The
        restored state is re-baselined (like _apply_startup_defaults) so it
        is not an undoable step, and the keys the preset explicitly stored
        are protected from the live --help defaults merge that runs when the
        startup worker finishes.
        """
        try:
            name = load_last_preset()
            if not name:
                return
            if not any(p["name"] == name for p in self.config.list_presets()):
                # Stale pointer: the preset was deleted (or hand-edited away)
                save_last_preset("")
                return
            params = self.config.load_preset(name)
            if not isinstance(params, dict):
                return
            # A9: presets often travel between machines — clear machine-local
            # paths that do not exist here (same rule as _load_preset)
            for key in ("model", "mmproj"):
                path_val = params.get(key) or ""
                if not path_val:
                    continue
                resolved = Path(path_val)
                if not resolved.is_absolute():
                    resolved = self.work_dir / resolved
                if not resolved.exists():
                    params[key] = ""
            self._preset_protected_keys = (
                self.config.preset_stored_keys(name) or set())
            self._set_current_values(params)
            # Re-baseline BEFORE the preview tick so the restored preset is
            # the starting state, not an undoable step (plan A4 semantics)
            self.params_history[0] = dict(self.params)
            self._last_saved = dict(self.params)
            self._pending_snapshot = False
            self._undo_debounce.stop()
            self.btn_undo.setEnabled(False)
            self._update_cmd_preview()
            self._refresh_presets(select_name=name)
            self.statusBar().showMessage(t("已加载预设: {name}", name=name), 3000)
        except Exception:
            pass

    def _save_preset(self):
        # E6: save dialog with an optional "include model paths" switch
        # (E12: frameless themed card like every other dialog)
        current_name = self.preset_combo.currentText()
        dlg = FramelessDialog(self, title=t("保存预设"), icon=app_icon(),
                              resizable=False, size=(420, 0))
        form = QFormLayout()
        name_edit = QLineEdit(current_name)
        name_edit.setPlaceholderText(t("预设名称:"))
        chk_paths = QCheckBox(t("包含模型路径 (model/mmproj)"))
        chk_paths.setChecked(True)
        chk_paths.setToolTip(t("不勾选时预设不记录模型/mmproj 路径，便于在不同机器间共享"))
        form.addRow(t("预设名称:"), name_edit)
        form.addRow("", chk_paths)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("保存"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("取消"))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        dlg.content_layout.addLayout(form)
        result = dlg.exec()
        dlg.deleteLater()  # don't leave a hidden top-level behind
        if result != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            return
        presets = self.config.list_presets()
        exists = any(p["name"] == name for p in presets)
        if exists and name != current_name:
            reply = ThemedMessageBox.question(
                self, t("预设已存在"),
                t("预设 '{name}' 已存在，是否覆盖？", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        elif exists and name == current_name:
            reply = ThemedMessageBox.question(
                self, t("覆盖预设"),
                t("确定覆盖预设 '{name}'？", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        # C3: MainWindow.params is the single source of truth; the values dict
        # is passed straight to the JSON layer (no config.current copy)
        values = self._get_current_values()
        if not chk_paths.isChecked():
            # E6: portable preset without machine-local paths
            values.pop("model", None)
            values.pop("mmproj", None)
        if not self.config.save_preset(name, values):
            ThemedMessageBox.warning(self, t("保存失败"),
                                t("预设 '{name}' 保存失败，请检查预设目录权限。", name=name))
            return
        self._refresh_presets(select_name=name)
        idx = self.preset_combo.findText(name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        # A9: warn that API tokens are stored in plain text inside the JSON
        secret_keys = [k for k in ("api_key", "hf_token") if values.get(k)]
        if secret_keys:
            self.statusBar().showMessage(
                t("注意: 预设将以明文保存密钥 ({keys})，请注意不要分享该文件",
                  keys=", ".join(secret_keys)), 8000)
        else:
            self.statusBar().showMessage(t("已保存预设: {name}", name=name), 2000)

    def _delete_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        reply = ThemedMessageBox.question(
            self, t("删除预设"), t("确定删除预设 '{name}'?", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.delete_preset(name)
            if load_last_preset() == name:
                # Drop the stale startup-restore pointer now, not next launch
                save_last_preset("")
            self._refresh_presets()
            self.statusBar().showMessage(t("已删除预设: {name}", name=name), 2000)

    def _import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, t("导入预设"), "", "JSON Files (*.json)")
        if not path:
            return
        # import_preset names the preset after the file stem; confirm before overwriting
        # an existing preset with the same name (same logic as _save_preset)
        from core.config import _sanitize_preset_name
        dest_name = _sanitize_preset_name(Path(path).stem)
        if any(p["name"] == dest_name for p in self.config.list_presets()):
            reply = ThemedMessageBox.question(
                self, t("预设已存在"),
                t("预设 '{name}' 已存在，是否覆盖？", name=dest_name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        if self.config.import_preset(path):
            self._refresh_presets()
            idx = self.preset_combo.findText(dest_name)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
            self.statusBar().showMessage(t("预设已导入: {name}", name=dest_name), 2000)
        else:
            ThemedMessageBox.warning(self, t("导入失败"), t("预设导入失败，请检查文件是否为有效的预设 JSON。"))

    def _export_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("导出预设"), f"{name}.json", "JSON Files (*.json)")
        if not path:
            return
        if self.config.export_preset(name, path):
            self.statusBar().showMessage(t("预设已导出: {name}", name=name), 2000)
        else:
            ThemedMessageBox.warning(self, t("导出失败"), t("预设导出失败，请检查目标路径是否可写。"))

    def _is_port_in_use(self, port, host='127.0.0.1'):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def _set_scan_path(self):
        d = QFileDialog.getExistingDirectory(self, t("选择模型扫描目录"), str(self.model_dir))
        if d:
            self.model_dir = Path(d)
            self.model_browser.set_search_dir(d)
            save_scan_path(d)
            self.statusBar().showMessage(t("扫描路径已更改为: {path}", path=d), 3000)

    def _set_server_path(self):
        # E1: dialog to view/set the llama-server executable path.
        # Prefilled with the currently effective path (explicit setting first,
        # then the PATH-resolved one); empty only when nothing was found.
        resolved = get_server_path()
        explicit = load_server_path()
        # Prefill a dead explicit setting would just re-verify the same miss —
        # fall back to the currently resolved path in that case.
        prefill = explicit if (explicit and Path(explicit).is_file()) else \
            (resolved if resolved != "llama-server" else "")
        # Themed frameless card dialog (custom header + shadow + accent OK) —
        # the old plain native dialog had a clashing OS title bar on Windows.
        from ui.server_path_dialog import ServerPathDialog
        dialog = ServerPathDialog(self, prefill, resolved, self.theme)
        result = dialog.exec()
        dialog.deleteLater()  # don't leave a hidden top-level behind
        if result != QDialog.DialogCode.Accepted:
            return
        path = str(Path(dialog.path()).expanduser())
        if not path:
            return
        # Validate before saving: the binary must answer --version
        verified, detail = False, ""
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            verified = result.returncode == 0 and bool((result.stdout + result.stderr).strip())
        except FileNotFoundError:
            detail = "not found"
        except Exception as e:
            detail = str(e)
        if not verified:
            self.statusBar().showMessage(t("路径验证失败: {e}", e=detail or path), 8000)
            if ThemedMessageBox.question(self, t("llama-server 路径"),
                                    t("路径验证失败，仍要保存吗？")) != QMessageBox.StandardButton.Yes:
                return
        save_server_path(path)
        self.statusBar().showMessage(t("llama-server 路径已设置: {path}", path=path), 8000)
        # Refresh version label + live defaults against the new binary (A10 flow)
        old_worker = getattr(self, '_startup_worker', None)
        if old_worker is not None and old_worker.isRunning():
            old_worker.wait(2000)
            if old_worker.isRunning():
                # wait timed out: _check_server_info() drops the reference
                # below, so cut the signal links first — the worker itself
                # is kept alive by _active_startup_workers until run()
                # returns (destroying a running QThread crashes natively).
                old_worker.disconnect()
        self._check_server_info()

    def _restore_ui_state(self):
        # E2: restore window geometry, mode, tab positions, splitter ratio.
        # Each value is validated individually — a partial/corrupt prefs dict
        # degrades silently to the built-in defaults.
        prefs = load_ui_prefs()
        if not prefs:
            return
        import base64
        from PyQt6.QtCore import QByteArray
        geo = prefs.get("geometry")
        if isinstance(geo, (list, tuple)) and len(geo) == 4:
            # E14: plain [x, y, w, h] client-geometry numbers (what
            # _save_ui_state writes). Applied via setGeometry in showEvent —
            # deterministic on every platform, where the QByteArray
            # restoreGeometry form is unreliable (partially applied offscreen)
            # and a pre-show application is silently discarded once the E11
            # content minimums land during construction.
            try:
                x, y, w, h = (int(v) for v in geo)
                if 200 <= w <= 8000 and 150 <= h <= 8000:
                    self._pending_geometry = QRect(x, y, w, h)
            except (TypeError, ValueError):
                pass
        elif isinstance(geo, str) and geo:
            # legacy E2 format (base64 saveGeometry bytes): best effort —
            # pre-show restore plus a re-apply in showEvent. Kept so existing
            # settings keep working for one cycle until the close rewrites
            # them in the numeric format.
            try:
                raw = QByteArray(base64.b64decode(geo.encode("ascii")))
                self.restoreGeometry(raw)
                self._pending_geometry_raw = raw
            except Exception:
                pass
        sizes = prefs.get("splitter")
        if isinstance(sizes, (list, tuple)) and len(sizes) == 2:
            try:
                left, right = int(sizes[0]), int(sizes[1])
                # left panel min/max are 180/500 (see _create_left_panel);
                # store the saved left width and apply it — if the window is
                # not at final size yet (pre-show), showEvent reapplies it
                # once the real width is known (see _apply_pending_splitter)
                if 180 <= left <= 500 and right > 0:
                    # apply happens in showEvent (a setSizes before the first
                    # layout pass is silently ignored by Qt)
                    self._pending_splitter_left = left
            except (TypeError, ValueError):
                pass
        if isinstance(prefs.get("mode"), int) and not isinstance(prefs.get("mode"), bool) \
                and prefs["mode"] in (0, 1):
            self.mode_combo.setCurrentIndex(prefs["mode"])
        # adv_tab_key (stable tab key) wins over adv_tab (index) — the tab
        # order changed with the 9-tab semantic regrouping, so a saved index
        # from an older version can point at the wrong tab.
        tab_keys = self.advanced_panel.tab_keys()
        adv_tab_key = prefs.get("adv_tab_key")
        if isinstance(adv_tab_key, str) and adv_tab_key in tab_keys:
            self.advanced_panel.tabs.setCurrentIndex(tab_keys.index(adv_tab_key))
        else:
            adv_tab = prefs.get("adv_tab")
            if isinstance(adv_tab, int) and not isinstance(adv_tab, bool) \
                    and 0 <= adv_tab < self.advanced_panel.tabs.count():
                self.advanced_panel.tabs.setCurrentIndex(adv_tab)
        bot_tab = prefs.get("bottom_tab")
        if isinstance(bot_tab, int) and not isinstance(bot_tab, bool) \
                and 0 <= bot_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(bot_tab)
        # E10: user-configured quick toggles (validated/sanitized inside;
        # an all-invalid list degrades to the built-in default set)
        if prefs.get("quick_params") is not None:
            self.basic_panel.set_quick_params(prefs["quick_params"])

    def _customize_quick_toggles(self):
        # E10: 设置-menu entry for the quick-toggles group — the panel-level
        # gear button was dropped in favour of the menu as the single
        # customization entry point.
        from ui.quick_params_dialog import QuickParamsDialog
        dlg = QuickParamsDialog(self, self.basic_panel.get_quick_params())
        result = dlg.exec()
        dlg.deleteLater()  # don't leave a hidden top-level behind
        if result == QDialog.DialogCode.Accepted:
            keys = list(dlg.result_keys())
            self.basic_panel.set_quick_params(keys)
            save_ui_pref("quick_params", keys)  # persist immediately (E10)
            self._sync_panel_min()  # E11: more keys can grow the panel's min height
            QTimer.singleShot(0, self._sync_panel_min)  # ...and once more on the settled layout
            self._apply_params_to_current()

    def _save_ui_state(self):
        # E2: persist for the next launch (written on close)
        # E14: plain [x, y, w, h] client-geometry numbers — restoreGeometry's
        # QByteArray form was silently discarded pre-show (the window always
        # opened at its content minimum) and is unreliable offscreen.
        # While maximized the full-screen rect is not useful as a *normal*
        # window size, so the previously saved value (or nothing → the E14
        # screen-relative default on next launch) is kept.
        if self.isMaximized():
            prev = load_ui_prefs().get("geometry")
            geo = prev if (isinstance(prev, (list, tuple))
                           and len(prev) == 4) else None
        else:
            geo = [self.x(), self.y(), self.width(), self.height()]
        save_ui_prefs({
            "geometry": geo,
            "splitter": [int(s) for s in self.splitter.sizes()],
            "mode": self.mode_combo.currentIndex(),
            "adv_tab": self.advanced_panel.tabs.currentIndex(),
            "adv_tab_key": self.advanced_panel.current_tab_key(),
            "bottom_tab": self.tab_widget.currentIndex(),
            "quick_params": self.basic_panel.get_quick_params(),
        })

    def closeEvent(self, event):
        # Step-by-step trace: if a "closing" app hangs, the log shows
        # exactly which step it is in (or that it never got here).
        log = logging.getLogger("shutdown")
        # Snapshot what Qt still considers visible (widget level and
        # QWindow level — the two can disagree on Windows for
        # frameless/translucent windows; a stale "visible" top-level is
        # what defeats quitOnLastWindowClosed).
        from PyQt6.QtGui import QGuiApplication
        vis_w = [f"{type(w).__name__}#{w.objectName() or '?'}"
                 for w in QApplication.topLevelWidgets() if w.isVisible()]
        vis_q = [w.objectName() or type(w).__name__
                 for w in QGuiApplication.allWindows() if w.isVisible()]
        log.info("closeEvent: start; visible widgets=%s qwindows=%s",
                 vis_w or "none", vis_q or "none")
        if self.runner.is_running:
            self.runner.stop(blocking=True)
            log.info("closeEvent: server stopped")
        self.model_browser.shutdown()
        log.info("closeEvent: model browser stopped")
        if hasattr(self, '_startup_worker') and self._startup_worker is not None:
            self._startup_worker.quit()
            self._startup_worker.wait(2000)
            if self._startup_worker.isRunning():
                # wait timed out (a hung --version/--help probe): the worker
                # is kept alive by _active_startup_workers, so cut its signal
                # links to this window before the window is destroyed — a
                # late emit from a live sender into a dying window is a
                # native crash.
                self._startup_worker.disconnect()
            log.info("closeEvent: startup worker stopped")
        self._close_run_log()
        self._save_ui_state()
        log.info("closeEvent: done, accepting + explicit quit")
        # Single-window app: end the event loop deterministically instead
        # of relying on quitOnLastWindowClosed (its visible-window
        # accounting can desync on Windows once frameless/translucent
        # dialogs have been shown).
        QApplication.instance().quit()
        event.accept()

    def _create_menu_bar(self):
        from PyQt6.QtGui import QActionGroup
        # E12: standalone menu bar — it moves into the menu-widget slot
        # below the custom title bar (a frameless window has no system
        # menu bar area).
        menubar = QMenuBar()
        self._menubar = menubar

        self.file_menu = menubar.addMenu(t("文件"))

        self._scan_path_action = QAction(self._create_text_icon("P", QColor("#f39c12")), t("设置扫描路径..."), self)
        self._scan_path_action.setShortcut("Ctrl+P")
        self._scan_path_action.triggered.connect(self._set_scan_path)
        self.file_menu.addAction(self._scan_path_action)

        # E1: explicit llama-server path (takes priority over PATH)
        self._server_path_action = QAction(self._create_text_icon("S", QColor("#2980b9")), t("设置 llama-server 路径..."), self)
        self._server_path_action.triggered.connect(self._set_server_path)
        self.file_menu.addAction(self._server_path_action)

        self._refresh_action = QAction(self._create_text_icon("R", QColor("#27ae60")), t("刷新模型列表"), self)
        self._refresh_action.setShortcut("F5")
        self._refresh_action.triggered.connect(lambda: self.model_browser.scan_models())
        self.file_menu.addAction(self._refresh_action)

        self.file_menu.addSeparator()

        self._exit_action = QAction(self._create_text_icon("X", QColor("#e74c3c")), t("退出"), self)
        self._exit_action.setShortcut("Alt+F4")
        self._exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self._exit_action)

        # Settings menu (absorbs the old 语言 menu; theme moved out of 帮助)
        self.settings_menu = menubar.addMenu(t("设置"))
        # E10: customize which toggles the ⚡ 快捷开关 group shows
        self._quick_params_action = QAction(self._create_text_icon("Q", QColor("#f1c40f")), t("自定义快捷开关…"), self)
        self._quick_params_action.triggered.connect(self._customize_quick_toggles)
        self.settings_menu.addAction(self._quick_params_action)
        self.settings_menu.addSeparator()

        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)

        self._action_zh = QAction(self._create_text_icon("中", QColor("#e74c3c")), t("中文"), self)
        self._action_zh.setCheckable(True)
        self._action_zh.setChecked(get_language() == "zh")
        self._action_zh.triggered.connect(lambda: self._switch_language("zh"))
        self._lang_group.addAction(self._action_zh)
        self.settings_menu.addAction(self._action_zh)

        self._action_en = QAction(self._create_text_icon("En", QColor("#3498db")), t("English"), self)
        self._action_en.setCheckable(True)
        self._action_en.setChecked(get_language() == "en")
        self._action_en.triggered.connect(lambda: self._switch_language("en"))
        self._lang_group.addAction(self._action_en)
        self.settings_menu.addAction(self._action_en)
        self.settings_menu.addSeparator()

        # E5: theme toggle (checkable, persisted)
        self._theme_action = QAction(t("🌙 深色主题"), self)
        self._theme_action.setCheckable(True)
        self._theme_action.setChecked(self.theme == "dark")
        self._theme_action.triggered.connect(self._toggle_theme)
        self.settings_menu.addAction(self._theme_action)

        self.help_menu = menubar.addMenu(t("帮助"))
        self._about_action = QAction(self._create_text_icon("?", QColor("#9b59b6")), t("关于"), self)
        self._about_action.triggered.connect(self._show_about)
        self.help_menu.addAction(self._about_action)

        # E13: a single integrated chrome row in the QMainWindow
        # menu-widget slot — icon + title + menu + window buttons. The
        # QMenuBar keeps all its native behaviour (icons, checkables,
        # shortcuts, popups); it is just hosted in the title-bar row
        # instead of a separate strip below it.
        menubar.setObjectName("titleMenuBar")
        self._title_bar = TitleBar(
            self.windowTitle(), icon=app_icon(), window=self,
            min_btn=True, max_btn=True, menu_bar=menubar,
            height=TITLE_BAR_HEIGHT)
        self._top_bar = self._title_bar
        self.setMenuWidget(self._title_bar)

    def _create_text_icon(self, text, color, size=16):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.setPen(QColor("white"))
        font_size = 9 if len(text) <= 1 else (7 if len(text) <= 2 else 6)
        font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return QIcon(pixmap)

    def _reset_to_defaults(self):
        self._save_params_snapshot()
        current_model = self.params.get("model", "")
        current_mmproj = self.params.get("mmproj", "")
        self.params = dict(self.defaults)
        self.params["model"] = current_model
        self.params["mmproj"] = current_mmproj
        self._apply_params_to_current()
        self._save_params_snapshot()
        self._update_cmd_preview()
        self.statusBar().showMessage(t("已重置为默认值"), 2000)

    def _show_about(self):
        msg = ThemedMessageBox(self)
        msg.setWindowTitle(t("关于"))
        msg.setIcon(QMessageBox.Icon.Information)
        # Version block: launcher version (build_config), runtime
        # (Python / PyQt6), and the resolved llama-server binary + its
        # self-reported version (fetched asynchronously at startup).
        try:
            pyqt_ver = pkg_version("PyQt6")
        except Exception:
            pyqt_ver = PYQT_VERSION_STR
        try:
            server_path = get_server_path()
        except Exception:
            server_path = "llama-server"
        version_info = (
            t("版本: {v}", v=f"v{APP_VERSION}") + "<br>"
            + t("Python {p} · PyQt6 {q}",
                p=platform.python_version(), q=pyqt_ver) + "<br>"
            + t("llama-server: {path}", path=server_path) + "<br>"
        )
        if getattr(self, "_server_version_line", ""):
            version_info += t("当前 llama-server: {line}",
                              line=self._server_version_line) + "<br>"
        version_info += "<br>"
        msg.setText(
            f"<b>🦙 llama.cpp Launcher v{APP_VERSION}</b><br><br>"
            + t("一个功能丰富的图形化 llama-server 启动器，帮助您轻松管理和运行 GGUF 格式的大语言模型。<br><br>")
            + version_info
            + t("<b>主要功能：</b><br>")
            + t("📦 <b>模型管理</b> — 递归扫描并自动分类本地 GGUF 文件（模型 / mmproj / LoRA，含大小显示），自动匹配同名 mmproj；高级模式还支持 HuggingFace / Docker / URL 指定模型<br>")
            + t("🎛️ <b>基础 / 高级模式</b> — 基础模式滑杆快调常用参数；高级模式 {tabs} 个标签页覆盖 {n} 个 llama-server 参数，每个参数均带 \"?\" 说明<br>",
                tabs=len(AdvancedPanel._TAB_TITLES), n=len(PARAMS_BY_KEY))
            + t("🖥️ <b>GPU / 性能</b> — 启动时自动检测 GPU 设备（型号 / 显存），GPU 层卸载、Flash Attention、KV Cache 卸载、多 GPU 张量分割<br>")
            + t("🎲 <b>采样与投机解码</b> — 温度 / Top-P / Top-K / Min-P / 重复惩罚 / DRY / Mirostat 等完整采样参数；草稿模型、ngram、lookup cache 投机解码<br>")
            + t("🌐 <b>服务管理</b> — 主机 / 端口、API 密钥、SSL、CORS、连续批处理、多槽位、router 与 embedding / rerank 模式<br>")
            + t("🤖 <b>Agent / 工具与聊天</b> — 工具调用 / MCP 配置、聊天模板、推理（Reasoning）模式<br>")
            + t("💾 <b>预设系统</b> — 保存 / 加载 / 导入 / 导出参数预设，记录创建时间、可选包含模型路径，启动时自动恢复上次使用的预设<br>")
            + t("📋 <b>命令与日志</b> — 实时生成 llama-server 命令行一键复制；实时日志解析（兼容新旧格式）、Ctrl+F 搜索、级别过滤、完整日志导出<br>")
            + t("🔬 <b>GGUF 检查器</b> — 概览 / 统计 / 元数据 / 张量 / 分词器 / 文件名 / 诊断共 7 个标签页，导出 JSON / CSV / Markdown，并可对照当前启动配置给出诊断<br>")
            + t("🔗 <b>版本自适应</b> — 启动时从 llama-server --help 动态解析默认值与聊天模板，llama.cpp 升级自动跟随并提示参数差异<br>")
            + t("🎨 <b>界面体验</b> — 浅色 / 深色主题、中 / 英文界面实时切换、窗口状态记忆、参数修改可撤销<br>")
            + "<br>"
            + t("<b>技术栈：</b> PyQt6 · Python · llama.cpp<br>")
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        msg.deleteLater()  # don't leave a hidden top-level behind

    def _create_model_info_group(self):
        group = QGroupBox(t("📊 模型信息"))
        self.model_info_group = group
        layout = QGridLayout(group)
        layout.setContentsMargins(10, 20, 10, 8)
        layout.setSpacing(6)
        layout.setColumnStretch(1, 1)
        # 扫描状态行（"已扫描: N 个模型, M 个 mmproj"）放在模型信息区开头：
        # 标签本体仍在 ModelBrowser 里创建/更新，这里 addWidget 会自动把它
        # 从浏览器的布局里摘走并重设父级
        layout.addWidget(self.model_browser.status_label, 0, 0, 1, 2)

        # GGUF quick-metadata row state (arch · max ctx · chat template)
        self._model_meta = None          # GGUFQuickInfo for the current model
        self._model_meta_seq = 0         # in-flight parse guard
        self._model_meta_worker = None   # keep the running thread alive

        self.model_info_labels = {}
        self._model_info_label_widgets = {}
        info_items = [
            ("model_size", "📦 模型大小"),
            ("mmproj_size", "🖼️ 多模态投影"),
            ("total_size", "📁 权重总大小"),
            ("model_params", "🔢 模型参数量"),
            ("quant_type", "📐 量化类型"),
        ]
        for row_idx, (key, label_text) in enumerate(info_items, start=1):
            lbl = QLabel(t(label_text))
            self._model_info_label_widgets[key] = (lbl, label_text)
            lbl.setStyleSheet("color: #7aa2f7; font-weight: bold; font-size: 12px;")
            layout.addWidget(lbl, row_idx, 0)

            val = QLabel("—")
            val.setStyleSheet("color: #3b4261; font-size: 12px;")
            val.setWordWrap(True)
            layout.addWidget(val, row_idx, 1)
            self.model_info_labels[key] = val

        # GGUF Inspector button
        btn_row = len(info_items) + 1
        self.btn_gguf_inspect = QPushButton(t("🔍 GGUF"))
        self.btn_gguf_inspect.setToolTip(t("请先选择 .gguf 模型"))
        self.btn_gguf_inspect.setEnabled(False)
        self.btn_gguf_inspect.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 12px; font-weight: bold; } "
            "QPushButton:hover { background: #2563eb; } "
            "QPushButton:disabled { background: #94a3b8; color: #cbd5e1; }"
        )
        self.btn_gguf_inspect.clicked.connect(self._open_gguf_inspector)
        # GGUF quick metadata (arch · max ctx), parsed asynchronously;
        # fills the space left of the GGUF button. Eliding so the label
        # never widens the group (full text in the tooltip).
        self.model_meta_label = ElidingLabel("—")
        f = self.model_meta_label.font()
        f.setPixelSize(11)
        self.model_meta_label.setFont(f)
        # 文字样式与扫描状态行（#565f89 / 11px）保持一致
        self._set_meta_color("#565f89")
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self.model_meta_label)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_gguf_inspect)
        layout.addWidget(btn_container, btn_row, 0, 1, 2)

        return group

    def _update_model_info(self):
        if not hasattr(self, "basic_panel"):
            return
        v = self._get_current_values()
        model_path = v.get("model", "")
        mmproj_path = v.get("mmproj", "")

        model_size_str = "—"
        model_params_str = "—"
        quant_type_str = "—"
        model_size_bytes = 0
        if model_path and Path(model_path).exists():
            model_size_bytes = Path(model_path).stat().st_size
            if model_size_bytes > 1024 ** 3:
                model_size_str = f"{model_size_bytes / (1024 ** 3):.2f} GB"
            else:
                model_size_str = f"{model_size_bytes / (1024 ** 2):.0f} MB"
            model_params_str = self._estimate_params(model_size_bytes)
            quant_type_str = self._guess_quant_type(model_path)

        mmproj_size_str = "—"
        mmproj_bytes = 0
        if mmproj_path and Path(mmproj_path).exists():
            mmproj_bytes = Path(mmproj_path).stat().st_size
            if mmproj_bytes > 1024 ** 3:
                mmproj_size_str = f"{mmproj_bytes / (1024 ** 3):.2f} GB"
            else:
                mmproj_size_str = f"{mmproj_bytes / (1024 ** 2):.0f} MB"

        total_bytes = model_size_bytes + mmproj_bytes
        if total_bytes > 0:
            if total_bytes > 1024 ** 3:
                total_str = f"{total_bytes / (1024 ** 3):.2f} GB"
            else:
                total_str = f"{total_bytes / (1024 ** 2):.0f} MB"
        else:
            total_str = "—"

        self.model_info_labels["model_size"].setText(model_size_str)
        self.model_info_labels["mmproj_size"].setText(mmproj_size_str)
        self.model_info_labels["total_size"].setText(total_str)
        self.model_info_labels["model_params"].setText(model_params_str)
        self.model_info_labels["quant_type"].setText(quant_type_str)

        # Enable/disable GGUF inspector button
        has_model = bool(model_path and Path(model_path).exists())
        self.btn_gguf_inspect.setEnabled(has_model)
        if has_model:
            self.btn_gguf_inspect.setToolTip(t("打开 GGUF 详情查看器"))
        else:
            self.btn_gguf_inspect.setToolTip(t("请先选择 .gguf 模型"))

        self._update_model_meta(model_path)

    # ------------------------------------------------------------------
    # GGUF quick-metadata row (arch · max ctx)
    # ------------------------------------------------------------------

    def _set_meta_color(self, hexcolor):
        # ElidingLabel paints with the palette Text role, not QSS — see its
        # docstring. Idle/status gray (same as the scan-status row);
        # amber when ctx exceeds the model limit.
        # The colour also has to live in a widget-level stylesheet: the
        # app-level QWidget rule (theme text colour, 13px) re-polishes the
        # widget after show and clobbers whatever palette/font the code set
        # — an inline sheet wins that fight. The 11px pin keeps the row's
        # style identical to the scan-status row.
        self.model_meta_label.setStyleSheet(
            f"color: {hexcolor}; font-size: 11px;")
        pal = self.model_meta_label.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor(hexcolor))
        self.model_meta_label.setPalette(pal)

    def _update_model_meta(self, model_path):
        """Refresh the quick-metadata row for the selected model file.

        Always goes through the worker — even a cache hit only costs one
        event-loop hop, while a miss must never block the GUI thread on
        disk IO. The seq counter drops results for models the user already
        switched away from."""
        self._model_meta_seq += 1
        seq = self._model_meta_seq
        self._model_meta = None
        label = self.model_meta_label
        if not (model_path and Path(model_path).exists()):
            label.setText("—")
            label.setToolTip("")
            self._set_meta_color("#565f89")
            return
        label.setText(t("正在解析..."))
        label.setToolTip(str(model_path))
        self._set_meta_color("#565f89")
        worker = _ModelMetaWorker(seq, str(model_path), self)
        worker.finished_ok.connect(self._on_model_meta_ok)
        worker.finished_err.connect(self._on_model_meta_err)
        # 窗口关闭时仍在解析的 worker：模块级持引用，防止 QThread 对象在运行
        # 中被销毁（销毁运行中的 QThread 会直接崩进程），结束后自动清理
        worker.finished.connect(lambda: _active_meta_workers.discard(worker))
        _active_meta_workers.add(worker)
        self._model_meta_worker = worker
        worker.start()

    def _on_model_meta_ok(self, seq, info):
        if seq != self._model_meta_seq:
            return  # stale: user switched model while this was parsing
        self._model_meta = info
        self._render_model_meta()

    def _on_model_meta_err(self, seq, msg):
        if seq != self._model_meta_seq:
            return
        self._model_meta = None
        label = self.model_meta_label
        label.setText("—")
        label.setToolTip(t("GGUF 元数据解析失败: {err}", err=msg))
        self._set_meta_color("#565f89")

    def _render_model_meta(self):
        """(Re)build the quick-metadata row text + colour from _model_meta.

        Amber when the user-set context exceeds the model's limit — the
        server would clamp it at load, so flag it before launch."""
        label = self.model_meta_label
        info = self._model_meta
        if info is None:
            return
        parts = []
        if info.arch:
            parts.append(info.arch)
        if info.context_length:
            parts.append(t("最大上下文 {ctx}", ctx=f"{info.context_length:,}"))
        text = " · ".join(parts)
        label.setText(text)
        ctx = 0
        try:
            ctx = int(self.params.get("ctx_size") or 0)
        except (TypeError, ValueError):
            ctx = 0
        if info.context_length and ctx > info.context_length:
            label.setToolTip(
                text + "\n" + t(
                    "⚠ 当前设置的上下文 {ctx} 超过模型上限 {max}（启动后会被截断）",
                    ctx=f"{ctx:,}", max=f"{info.context_length:,}"))
            self._set_meta_color("#d97706")
        else:
            label.setToolTip(text)
            self._set_meta_color("#565f89")

    def _estimate_params(self, size_bytes):
        quant = self._guess_quant_type(self.params.get("model", ""))
        bits_map = {
            "IQ1": 2.0, "IQ2": 2.5, "IQ3": 3.5, "IQ4": 4.5,
            "Q2_K": 2.5, "Q3_K": 3.5, "Q4_0": 4.5,
            "Q4_K": 4.5, "Q5_0": 5.5, "Q5_K": 5.5,
            "Q6_K": 6.5, "Q8_0": 8.5,
            "F16": 16.0, "F32": 32.0,
            "BF16": 16.0,
        }
        bits = bits_map.get(quant, 4.5)
        params = size_bytes * 8 / bits
        if params < 1e9:
            return f"< 1B"
        if params < 2e9:
            return f"{params/1e9:.1f}B"
        if params < 10e9:
            return f"{params/1e9:.1f}B"
        return f"{params/1e9:.0f}B"

    def _guess_quant_type(self, path):
        name = Path(path).name.lower()
        quant_map = [
            ("iq1_", "IQ1"), ("iq2_", "IQ2"), ("iq3_", "IQ3"), ("iq4_", "IQ4"),
            ("q2_k", "Q2_K"), ("q3_k", "Q3_K"), ("q4_0", "Q4_0"),
            ("q4_k", "Q4_K"), ("q5_0", "Q5_0"), ("q5_k", "Q5_K"),
            ("q6_k", "Q6_K"), ("q8_0", "Q8_0"),
            ("f16", "F16"), ("f32", "F32"),
            ("bf16", "BF16"),
        ]
        for tag, label in quant_map:
            if tag in name:
                return label
        return t("未知")

    def _open_gguf_inspector(self):
        v = self._get_current_values()
        model_path = v.get("model", "")
        if not model_path or not Path(model_path).exists():
            return

        launcher_params = {
            "ctx_size": int(v.get("ctx_size", 0) or 0),
            "mmproj": v.get("mmproj", ""),
            "spec_type": v.get("spec_type", ""),
            "draft_tokens": int(v.get("draft_max", 0) or 0),
            "flash_attn": v.get("flash_attn", False),
        }
        dlg = GGUFInspectorDialog(model_path, launcher_params, parent=self)
        dlg.exec()
        dlg.deleteLater()  # don't leave a hidden top-level behind

    def _check_server_info(self):
        self._startup_worker = _StartupInfoWorker()
        self._startup_worker.version_ready.connect(self._on_version_result)
        self._startup_worker.version_failed.connect(self._on_version_failed)
        self._startup_worker.defaults_ready.connect(self._on_startup_defaults)
        self._startup_worker.devices_ready.connect(self._on_devices_ready)
        self._startup_worker.start()

    def _on_devices_ready(self, devices):
        # E8: show detected GPU devices next to the ngl / split-mode controls.
        # Deliberately no auto-filling of ngl — "auto" is already the right
        # llama.cpp default and the probe cannot know the model size.
        self._gpu_devices = devices or []
        self.basic_panel.set_gpu_info(self._gpu_devices)
        self.advanced_panel.set_gpu_info(self._gpu_devices)
        # E11: the GPU-info label appears late (the probe is async) and
        # grows the panel's natural height — defer the resync so it reads
        # the settled layout minimum (same reasoning as
        # _on_quick_wrap_changed).
        QTimer.singleShot(0, self._sync_panel_min)

    def _on_startup_defaults(self, defaults, chat_templates):
        """Live-parsed defaults arrive from the startup worker (plan A10)."""
        self._apply_startup_defaults(defaults, chat_templates)
        if self._version_checked:
            # Version is already known: refresh the drift tooltip against the
            # live defaults (the version handler ran against the fallback ones).
            self._validate_params()

    def _apply_startup_defaults(self, defaults, chat_templates):
        """Merge live startup defaults into the window (plan A10).

        Params the user has not changed adopt the live default value; values the
        user already edited are preserved. When no user-change snapshot has
        landed yet, the initial history entry and _last_saved are re-baselined
        so the sync itself does not show up as an undoable step (plan A4).
        """
        from core.config import refresh_defaults
        orig_defaults = self.defaults
        self.defaults = defaults
        self.cmd_builder.defaults = defaults
        self.config.set_defaults(defaults)
        self.chat_templates = chat_templates
        self.basic_panel.set_defaults(defaults)
        self.advanced_panel.set_defaults(defaults)
        self.advanced_panel.set_chat_templates(chat_templates)
        refresh_defaults(defaults)
        for key, value in defaults.items():
            # A preset restored at startup explicitly set these keys — keep
            # the user's values even when they equal the fallback default.
            if key in self._preset_protected_keys:
                continue
            # Launcher-hardcoded default: log_verbosity is intentionally 4
            # (trace) instead of the binary's 3 (info) so the runtime-info
            # panel keeps working after llama.cpp #23021 moved library INFO
            # lines behind the trace threshold — never adopt the live value.
            if key == "log_verbosity":
                continue
            if self.params.get(key, None) == orig_defaults.get(key, None):
                self.params[key] = value
        if len(self.params_history) == 1:
            self.params_history[0] = dict(self.params)
            self._last_saved = dict(self.params)
            self._pending_snapshot = False
        self._apply_params_to_current()
        self._update_cmd_preview()

    def _on_version_result(self, ver_num, commit, version_line):
        self._version_checked = True
        self._server_version_line = version_line or ""
        if ver_num:
            text = f"🔖 llama.cpp v{ver_num} ({commit})"
            tooltip = t("llama.cpp 版本: {ver}\n提交: {commit}", ver=ver_num, commit=commit)
        else:
            text = f"🔖 {version_line}"
            tooltip = t("llama.cpp 版本信息") + f"\n{version_line}"
        self.version_label.setText(text)
        self.version_label.setStyleSheet("color: #16a34a; font-size: 12px; font-weight: bold;")
        # Store the base separately: _validate_params() may run again once the
        # live --help defaults arrive, and must rebuild from this base instead
        # of appending to an already-augmented tooltip (duplication bug).
        self._version_base_tooltip = tooltip
        self.version_label.setToolTip(tooltip)
        self._validate_params()

    def _on_version_failed(self, error_type):
        if error_type == "not_found":
            self.version_label.setText(t("⚠️ 未找到 llama-server"))
            self.version_label.setStyleSheet("color: #dc2626; font-size: 12px; font-weight: bold;")
            self.version_label.setToolTip(t("无法找到 llama-server，请确保已添加到系统 PATH 环境变量"))
        else:
            self.version_label.setText(t("⚠️ 检测失败"))
            self.version_label.setStyleSheet("color: #d97706; font-size: 12px;")
            self.version_label.setToolTip(t("检测 llama-server 版本时出错"))

    def _validate_params(self):
        from core.defaults import _FALLBACK_DEFAULTS, USER_INPUT_PARAMS
        missing, changed = [], []
        try:
            # Reuse the defaults parsed at startup (self.defaults) instead of spawning a
            # third subprocess (llama-server --help) on the main thread, which can block
            # the UI for up to 10s (A1). C5: the skip set is now the shared
            # USER_INPUT_PARAMS constant in core.defaults (per-user paths/keys/free
            # text and machine-specific settings) rather than an inline 67-key tuple.
            current_defaults = self.defaults
            for key, fallback_val in _FALLBACK_DEFAULTS.items():
                if key in USER_INPUT_PARAMS:
                    continue
                if key not in current_defaults:
                    missing.append(key)
                elif current_defaults[key] != fallback_val:
                    changed.append((key, fallback_val, current_defaults[key]))
        except Exception:
            missing, changed = [], []
        self._drift_missing = missing
        self._drift_changed = changed
        try:
            # Rebuild from the stored base (not the live toolTip()) so repeated
            # calls do not stack duplicate status sections.
            if not missing and not changed:
                self.version_label.setToolTip(self._version_base_tooltip + "\n\n" + t("✅ 所有参数与当前版本匹配"))
                self.version_label.setStyleSheet("color: #16a34a; font-size: 12px; font-weight: bold;")
            else:
                tip = self._version_base_tooltip + "\n\n" + t("⚠️ 参数差异提示:\n")
                if missing:
                    tip += t("  以下参数在当前版本中不存在: {keys}", keys=', '.join(missing[:5])) + "\n"
                if changed:
                    for key, old, new in changed[:5]:
                        tip += t("  {key}: 旧默认值 {old} → 新默认值 {new}", key=key, old=old, new=new) + "\n"
                if len(missing) > 5 or len(changed) > 5:
                    tip += t("  ... 等更多差异\n")
                tip += "\n" + t("建议点击「恢复默认」以适配当前版本")
                self.version_label.setToolTip(tip)
                self.version_label.setStyleSheet("color: #d97706; font-size: 12px; font-weight: bold;")
                self.drift_button.setVisible(True)
        except Exception:
            pass

    def _show_drift_dialog(self):
        # E7: full parameter-drift list (no 5-item truncation) in an
        # expandable message box
        if not self._drift_missing and not self._drift_changed:
            return
        lines = []
        if self._drift_missing:
            lines.append(t("以下参数在当前版本中不存在:"))
            lines.extend(f"  {k}" for k in self._drift_missing)
        if self._drift_changed:
            lines.append(t("以下参数的默认值已变化:"))
            lines.extend(
                t("  {key}: 旧默认值 {old} → 新默认值 {new}", key=k, old=o, new=n)
                for k, o, n in self._drift_changed)
        lines.append("")
        lines.append(t("建议点击「恢复默认」以适配当前版本"))
        box = ThemedMessageBox(self)
        box.setWindowTitle(t("参数版本差异"))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(t("检测到 {n} 项参数与当前 llama-server 版本不匹配",
                     n=len(self._drift_missing) + len(self._drift_changed)))
        box.setDetailedText("\n".join(lines))
        box.exec()
        box.deleteLater()  # don't leave a hidden top-level behind

    def _switch_language(self, lang):
        set_language(lang)
        save_language(lang)
        self._action_zh.setChecked(lang == "zh")
        self._action_en.setChecked(lang == "en")
        self.retranslate_ui()

    def retranslate_ui(self):
        # E12: title bar button tooltips
        self._title_bar.retranslate_ui()
        # Left panel
        self.model_browser.retranslate_ui()
        self.preset_group.setTitle(t("📦 预设管理"))
        self.btn_load.setText(t("⬇️ 加载"))
        self.btn_save.setText(t("💾 保存"))
        self.btn_delete.setText(t("🗑️ 删除"))
        self.btn_import.setText(t("📥 导入"))
        self.btn_export.setText(t("📤 导出"))
        self.drift_button.setToolTip(t("参数与当前版本存在差异，点击查看完整列表"))
        # Model info labels
        self.model_info_group.setTitle(t("📊 模型信息"))
        # 快速元数据行的文案随语言变化（arch/数值不变）
        self._render_model_meta()
        for key, (lbl, label_text) in self._model_info_label_widgets.items():
            lbl.setText(t(label_text))
        self.btn_gguf_inspect.setText(t("🔍 GGUF"))
        if self.btn_gguf_inspect.isEnabled():
            self.btn_gguf_inspect.setToolTip(t("打开 GGUF 详情查看器"))
        else:
            self.btn_gguf_inspect.setToolTip(t("请先选择 .gguf 模型"))

        # Right panel
        self.cmd_label.setText(t("📝 启动命令预览"))
        self.mode_label.setText(t("模式:"))
        self.mode_combo.setItemText(0, t("基础模式"))
        self.mode_combo.setItemText(1, t("高级模式"))
        self.btn_undo.setText(t("↩ 撤销"))
        self.btn_reset.setText(t("🔄 恢复默认"))
        self.btn_start.setText(t("▶ 启动服务"))
        self.btn_stop.setText(t("■ 停止服务"))
        self.btn_copy_cmd.setText(t("📋 复制命令"))
        self.btn_webui.setText(t("🌐 打开WebUI"))
        self.btn_clear_log.setText(t("🗑️ 清空"))
        self.btn_export_log.setText(t("💾 导出"))
        self.chk_auto_scroll.setText(t("📜 自动滚动"))
        # E3: log search + level filter
        self.log_search_edit.setPlaceholderText(t("🔍 搜索日志 (Ctrl+F)"))
        self.log_search_label.setText("")
        self.btn_log_search_prev.setToolTip(t("上一个"))
        self.btn_log_search_next.setToolTip(t("下一个"))
        self.btn_log_search_close.setToolTip(t("关闭搜索"))
        for lvl, name in (("D", t("调试")), ("I", t("信息")), ("W", t("警告")), ("E", t("错误"))):
            self._log_level_boxes[lvl].setText(name)
            self._log_level_boxes[lvl].setToolTip(name)
        self.tab_widget.setTabText(0, t("📄 日志输出"))
        self.tab_widget.setTabText(1, t("📊 运行信息"))

        # Version/status labels
        state = getattr(self, '_current_state', None)
        if state == "starting":
            self.status_indicator.setText(t("🔄 启动中..."))
        elif state == "running":
            self.status_indicator.setText(t("🟢 运行中"))
        elif state == "error":
            self.status_indicator.setText(t("🔴 错误"))
        else:
            self.status_indicator.setText(t("⏸ 已停止"))
        if not self.runner.is_running:
            self.run_time_label.setText(t("⏱ 运行: 00:00"))

        # Menus
        self.file_menu.setTitle(t("文件"))
        self._scan_path_action.setText(t("设置扫描路径..."))
        self._server_path_action.setText(t("设置 llama-server 路径..."))
        self._refresh_action.setText(t("刷新模型列表"))
        self._exit_action.setText(t("退出"))
        self.settings_menu.setTitle(t("设置"))
        self._quick_params_action.setText(t("自定义快捷开关…"))
        self._action_zh.setText(t("中文"))
        self._action_en.setText(t("English"))
        self._theme_action.setText(t("🌙 深色主题"))
        self.help_menu.setTitle(t("帮助"))
        self._about_action.setText(t("关于"))

        # Status bar
        if not self.runner.is_running:
            self.statusBar().showMessage(t("就绪"))

        # Info display
        if self._runtime_info:
            self._update_info_display()
        else:
            self.info_display.setHtml(empty_info_html())

        # Child panels
        self.basic_panel.retranslate_ui()
        self.advanced_panel.retranslate_ui()

    def _create_status_bar(self):
        # E13: _ThemedStatusBar — the built-in showMessage label paints at
        # a fixed x that ignores layout margins (it would float over the
        # rounded corner band); the subclass routes the message through a
        # layout-managed label (contents-margins keep the text on the card
        # face: left fixed, bottom synced to the shadow band by
        # _set_card_inset) and drops the native size grip.
        sb = _ThemedStatusBar(self)
        self.setStatusBar(sb)
        sb.showMessage(t("就绪"))

    def _apply_theme(self):
        """E5: apply the current theme application-wide.

        The sheet is applied at APPLICATION level only — deliberately NOT on
        the main window. A stylesheet set on a parent widget changes how Qt
        resolves styles for top-level child windows: with a window-level
        sheet, the QComboBox popup container (QComboBoxPrivateContainer)
        loses the global QWidget background rule and falls back to the
        default light palette — a white ring around the dropdown in dark
        mode. The app-level sheet covers the main window and every top-level
        dialog (GGUF inspector, path dialogs) alike.
        """
        qss = self._get_stylesheet(self.theme)
        # Theme-aware sheet for the bottom tabs (their inline QSS would
        # otherwise override the app dark rules); init_ui() calls
        # _apply_theme() before the tab widget exists, hence the guard
        tabs = getattr(self, "tab_widget", None)
        if tabs is not None:
            tabs.setStyleSheet(self._bottom_tabs_qss(self.theme))
        app = QApplication.instance()
        # Skip the app-level apply when the sheet is already identical —
        # re-applying forces a full re-polish of every top-level window
        if app is not None and app.styleSheet() != qss:
            app.setStyleSheet(qss)
        # E13: the painted card face + shadow use the theme colours
        self._chrome_cache = None
        self.update()

    def _toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self._theme_action.setChecked(self.theme == "dark")
        save_theme(self.theme)
        self._apply_theme()
        self.statusBar().showMessage(
            t("已切换到深色主题") if self.theme == "dark" else t("已切换到浅色主题"), 3000
        )

    @staticmethod
    def _bottom_tabs_qss(theme="light"):
        """Theme-aware QSS for the bottom log/info tab widget (E5 follow-up).

        The light string is the original pre-E5 sheet, kept verbatim so the
        light theme stays pixel-identical; dark mirrors it on the Catppuccin
        palette and blends with the always-dark log content (#121212).
        """
        if theme == "dark":
            return """
            QTabWidget::pane {
                border: 1px solid #313244;
                border-radius: 4px;
                background: #11111b;
            }
            QTabBar::tab {
                background: #1e1e2e;
                color: #a6adc8;
                padding: 6px 16px;
                margin-right: 2px;
                border: 1px solid #313244;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #11111b;
                color: #7aa2f7;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background: #2a2a3d;
            }
        """
        return """
            QTabWidget::pane {
                border: 1px solid #d0d4dc;
                border-radius: 4px;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #e8ecf0;
                color: #4a5568;
                padding: 6px 16px;
                margin-right: 2px;
                border: 1px solid #d0d4dc;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #2563eb;
                font-weight: bold;
            }
            QTabBar::tab:hover:!selected {
                background: #d8dce4;
            }
        """

    @staticmethod
    def _get_stylesheet(theme="light"):
        """E5: build the window QSS from a palette template.

        The QSS structure is shared; light/dark only differ in the @@tokens@@,
        which are replaced after the fact (QSS braces make str.format unsafe).
        """
        palette = MainWindow._THEME_PALETTES[theme]
        tokens = dict(palette)

        def _img(direction: str) -> str:
            # Qt QSS cannot draw CSS border-triangles on arrow subcontrols,
            # so every arrow is a generated PNG; forward slashes + quotes
            # keep Windows paths safe inside url().
            return 'url("{}")'.format(
                str(_ensure_arrow_image(direction, palette["combo_arrow"])).replace("\\", "/"))

        tokens["combo_arrow_img"] = _img("down")
        tokens["spin_up_img"] = _img("up")
        tokens["spin_down_img"] = _img("down")
        tokens["check_img"] = 'url("{}")'.format(
            str(_ensure_check_image()).replace("\\", "/"))
        qss = MainWindow._THEME_TEMPLATE
        for key, value in tokens.items():
            qss = qss.replace("@@" + key + "@@", value)
        return qss

    _THEME_PALETTES = {
        "light": {
            "win_bg": "#f0f2f5", "text": "#1a1a2e", "field_bg": "#ffffff",
            "border": "#d0d4dc", "muted": "#666", "hover_bg": "#e8ecf0",
            "pressed_bg": "#d8dce0", "sub_border": "#b0b8c0",
            "sb_hover": "#8a9098", "combo_arrow": "#333",
            "slider_rim": "#ffffff", "tab_sel_bg": "#ffffff",
            "table_alt": "#f2f5f9",
            "start_dis_bg": "#c8d8c8", "start_dis_fg": "#8a9a8a",
            "stop_dis_bg": "#d8c8c8", "stop_dis_fg": "#9a8a8a",
            "copy_dis_bg": "#c9cdd3", "copy_dis_fg": "#8a8f98",
            "webui_dis_bg": "#c8d0d8", "webui_dis_fg": "#8a9098",
            "warn": "#b45309",
        },
        # Catppuccin-ish dark, harmonized with the always-dark log areas
        "dark": {
            "win_bg": "#1e1e2e", "text": "#cdd6f4", "field_bg": "#181825",
            "border": "#313244", "muted": "#7f849c", "hover_bg": "#2a2a3d",
            "pressed_bg": "#313244", "sub_border": "#45475a",
            "sb_hover": "#585b70", "combo_arrow": "#cdd6f4",
            "slider_rim": "#1e1e2e", "tab_sel_bg": "#1e1e2e",
            "table_alt": "#1f1f2e",
            "start_dis_bg": "#2e3d34", "start_dis_fg": "#748a7c",
            "stop_dis_bg": "#3d2e2e", "stop_dis_fg": "#8a7474",
            "copy_dis_bg": "#2f3136", "copy_dis_fg": "#767c88",
            "webui_dis_bg": "#2e333d", "webui_dis_fg": "#6b7280",
            "warn": "#f59e0b",
        },
    }

    _THEME_TEMPLATE = """
            QMainWindow {
                background-color: @@win_bg@@;
            }
            QWidget {
                background-color: @@win_bg@@;
                color: @@text@@;
                font-size: 13px;
            }
            QPushButton#startBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22c55e, stop:1 #16a34a);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 22px;
            }
            QPushButton#startBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4ade80, stop:1 #22c55e);
            }
            QPushButton#startBtn:disabled {
                background: @@start_dis_bg@@;
                color: @@start_dis_fg@@;
            }
            QPushButton#stopBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ef4444, stop:1 #dc2626);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 22px;
            }
            QPushButton#stopBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f87171, stop:1 #ef4444);
            }
            QPushButton#stopBtn:disabled {
                background: @@stop_dis_bg@@;
                color: @@stop_dis_fg@@;
            }
            QPushButton#copyBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #94a3b8, stop:1 #64748b);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 22px;
            }
            QPushButton#copyBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #a9b7c6, stop:1 #718096);
            }
            QPushButton#copyBtn:disabled {
                background: @@copy_dis_bg@@;
                color: @@copy_dis_fg@@;
            }
            QPushButton#webuiBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 22px;
            }
            QPushButton#webuiBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QPushButton#webuiBtn:disabled {
                background: @@webui_dis_bg@@;
                color: @@webui_dis_fg@@;
            }
            QPlainTextEdit {
                background-color: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 8px;
                padding: 8px;
                selection-background-color: #3b82f6;
            }
            QComboBox, QDoubleSpinBox, QLineEdit, QTextEdit {
                background: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 4px 8px;
                selection-background-color: #3b82f6;
            }
            QTextEdit#inspectText {
                font-family: Consolas, monospace;
                font-size: 12px;
            }
            QSpinBox, QDoubleSpinBox {
                background: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 4px 8px;
                selection-background-color: #3b82f6;
                min-width: 60px;
            }
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
                border-color: #3b82f6;
            }
            QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
                border-color: #2563eb;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox::down-arrow {
                image: @@combo_arrow_img@@;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 22px;
                border-left: 1px solid @@border@@;
                border-bottom: 1px solid @@border@@;
                border-top-right-radius: 5px;
                background: @@field_bg@@;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 22px;
                border-left: 1px solid @@border@@;
                border-top: 1px solid @@border@@;
                border-bottom-right-radius: 5px;
                background: @@field_bg@@;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background: @@hover_bg@@;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                image: @@spin_up_img@@;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                image: @@spin_down_img@@;
            }
            QComboBox QAbstractItemView {
                background-color: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                selection-background-color: #3b82f6;
                padding: 4px;
            }
            QPushButton {
                background: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: @@hover_bg@@;
                border-color: #3b82f6;
            }
            QPushButton:pressed {
                background: @@pressed_bg@@;
            }
            QPushButton:disabled {
                background: @@field_bg@@;
                color: @@muted@@;
                border-color: @@border@@;
            }
            QToolButton#logSearchBtn,
            QPushButton#logSearchBtn {
                padding: 0px;
            }
            QToolButton {
                background: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QToolButton:hover {
                background: @@hover_bg@@;
                border-color: #3b82f6;
            }
            QToolButton:pressed {
                background: @@pressed_bg@@;
            }
            QToolButton:disabled {
                background: @@field_bg@@;
                color: @@muted@@;
                border-color: @@border@@;
            }
            QCheckBox {
                color: @@text@@;
                spacing: 6px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid @@sub_border@@;
                border-radius: 4px;
                background-color: @@field_bg@@;
            }
            QCheckBox::indicator:hover {
                border-color: #3b82f6;
            }
            QCheckBox::indicator:checked {
                background-color: #3b82f6;
                border-color: #2563eb;
                color: #ffffff;
                image: @@check_img@@;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid @@border@@;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 24px;
                color: @@text@@;
                background-color: @@field_bg@@;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 4px 8px;
                color: #2563eb;
                font-size: 13px;
            }
            QListWidget {
                background-color: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 2px;
            }
            QListWidget::item {
                padding: 4px 8px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: @@hover_bg@@;
            }
            QTableWidget, QTableView {
                background-color: @@field_bg@@;
                alternate-background-color: @@table_alt@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                gridline-color: @@border@@;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background-color: @@hover_bg@@;
                color: @@text@@;
                border: none;
                border-right: 1px solid @@border@@;
                border-bottom: 1px solid @@border@@;
                padding: 4px 8px;
                font-size: 12px;
                font-weight: bold;
            }
            QTableCornerButton::section {
                background-color: @@hover_bg@@;
                border: none;
                border-right: 1px solid @@border@@;
                border-bottom: 1px solid @@border@@;
            }
            QTabWidget::pane {
                border: 1px solid @@border@@;
                border-radius: 8px;
                background-color: @@field_bg@@;
            }
            QTabBar::tab {
                background: @@hover_bg@@;
                color: @@muted@@;
                padding: 8px 16px;
                border: 1px solid @@border@@;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: @@tab_sel_bg@@;
                color: #2563eb;
                border-bottom: 2px solid #2563eb;
            }
            QTabBar::tab:hover {
                background: @@win_bg@@;
                color: @@text@@;
            }
            QSplitter::handle {
                background-color: @@border@@;
                width: 3px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #3b82f6;
            }
            QMenuBar {
                background-color: @@field_bg@@;
                color: @@text@@;
                border-bottom: 1px solid @@border@@;
                padding: 2px;
            }
            QMenuBar::item:selected {
                background-color: @@hover_bg@@;
                border-radius: 4px;
            }
            QMenu {
                background-color: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QMenu::separator {
                height: 1px;
                background: @@border@@;
                margin: 4px 8px;
            }
            /* E13: sits on the painted card face — transparent, no divider */
            QStatusBar {
                background: transparent;
                color: @@muted@@;
                border: none;
                font-size: 12px;
            }
            QLabel {
                color: @@text@@;
                font-size: 13px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: @@hover_bg@@;
                border: 1px solid @@border@@;
                border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #60a5fa, stop:1 #3b82f6);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 18px;
                height: 18px;
                margin: -6px 0;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                border: 2px solid @@slider_rim@@;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QScrollBar:vertical {
                background: @@win_bg@@;
                width: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: @@sub_border@@;
                border-radius: 6px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: @@sb_hover@@;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QScrollBar:horizontal {
                background: @@win_bg@@;
                height: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: @@sub_border@@;
                border-radius: 6px;
                min-width: 24px;
            }
            QScrollBar::handle:horizontal:hover {
                background: @@sb_hover@@;
            }
            QProgressBar {
                background-color: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                text-align: center;
                min-height: 16px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #60a5fa, stop:1 #3b82f6);
                border-radius: 5px;
            }
            QToolTip {
                background-color: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 4px;
                padding: 4px 8px;
            }
            /* E12/E13: frameless window chrome (main window + all dialogs) */
            QMainWindow#llamaMainWin {
                /* E13: translucent top level — the rounded card + drop
                   shadow are painted in MainWindow.paintEvent, so the
                   top level itself must stay fully transparent. */
                background: transparent;
                border: none;
            }
            QDialog#framelessDialog {
                background: transparent;
            }
            QWidget#framelessCard {
                background-color: @@win_bg@@;
                border: 1px solid @@border@@;
                border-radius: 14px;
            }
            /* E13.3: the body fills the card edge-to-edge; its generic
               QWidget background must stay transparent so the card's
               rounded win_bg (incl. the bottom corners) shows through. */
            QWidget#framelessBody {
                background: transparent;
            }
            QWidget#titleBar {
                background: transparent;
            }
            QLabel#titleBarTitle {
                font-size: 13px;
                font-weight: bold;
                color: @@text@@;
            }
            /* E13: the menu is hosted in the title-bar row — flat pills */
            QMenuBar#titleMenuBar {
                background: transparent;
                border: none;
                padding: 0;
                color: @@muted@@;
            }
            QMenuBar#titleMenuBar::item {
                background: transparent;
                color: @@muted@@;
                padding: 5px 12px;
                border-radius: 7px;
            }
            QMenuBar#titleMenuBar::item:selected {
                background: @@hover_bg@@;
                color: @@text@@;
            }
            /* E13: Windows-11-style window controls */
            QPushButton#titleBarMinBtn, QPushButton#titleBarMaxBtn,
            QPushButton#titleBarCloseBtn {
                background: transparent;
                border: none;
                border-radius: 7px;
                color: @@muted@@;
                font-size: 10px;
                font-family: "Segoe UI Symbol", "Segoe UI";
                padding: 0px;
            }
            QPushButton#titleBarMinBtn:hover, QPushButton#titleBarMaxBtn:hover {
                background: @@hover_bg@@;
                color: @@text@@;
            }
            QPushButton#titleBarCloseBtn:hover {
                background: #e81123;
                color: #ffffff;
            }
            QPushButton#titleBarCloseBtn:pressed {
                background: #c50f1f;
            }
            /* E13: the status bar message sits on the painted card face */
            QLabel#statusMsg {
                background: transparent;
                color: @@muted@@;
                font-size: 12px;
            }
            /* E13: the shadow band around the card is part of the central
               widget's rect — it must paint nothing there */
            QWidget#centralArea {
                background: transparent;
            }
            /* E1: server-path dialog specifics */
            QLabel#serverPathDesc, QLabel#serverPathHintOk {
                color: @@muted@@;
                font-size: 12px;
            }
            QLabel#serverPathHintWarn {
                color: @@warn@@;
                font-size: 12px;
            }
            QLineEdit#serverPathEdit {
                background: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 6px 10px;
                font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
                font-size: 12px;
            }
            QLineEdit#serverPathEdit:focus {
                border: 1px solid #2563eb;
            }
            QPushButton#serverPathBrowse, QPushButton#serverPathCancel {
                background: @@hover_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 7px 18px;
            }
            QPushButton#serverPathBrowse:hover, QPushButton#serverPathCancel:hover {
                border-color: #3b82f6;
            }
            QPushButton#serverPathOk {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 7px 24px;
                font-weight: bold;
            }
            QPushButton#serverPathOk:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            /* E12: themed message box (ui/message_box.py) */
            QLabel#msgBoxText {
                color: @@text@@;
                font-size: 13px;
            }
            QLabel#msgBoxIconInfo { color: #3b82f6; font-size: 22px; font-weight: bold; }
            QLabel#msgBoxIconWarn { color: @@warn@@; font-size: 22px; font-weight: bold; }
            QLabel#msgBoxIconCritical { color: #e81123; font-size: 22px; font-weight: bold; }
            QLabel#msgBoxIconQuestion { color: @@muted@@; font-size: 22px; font-weight: bold; }
            QTextEdit#msgBoxDetail {
                background: @@field_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                font-size: 12px;
                padding: 6px;
            }
            QPushButton#msgBoxBtn {
                background: @@hover_bg@@;
                color: @@text@@;
                border: 1px solid @@border@@;
                border-radius: 6px;
                padding: 7px 18px;
            }
            QPushButton#msgBoxBtn:hover {
                border-color: #3b82f6;
            }
            QPushButton#msgBoxBtnAccept {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 7px 24px;
                font-weight: bold;
            }
            QPushButton#msgBoxBtnAccept:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
        """

