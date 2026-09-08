import html as html_mod
import re
import shutil
import socket
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QPlainTextEdit, QComboBox, QInputDialog,
    QMessageBox, QFileDialog, QStatusBar,
    QCheckBox, QGroupBox, QTabWidget, QTextEdit,
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QToolButton
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import (QAction, QFont, QTextOption, QIcon, QPixmap, QPainter,
                         QColor, QTextCursor, QTextDocument, QKeySequence, QShortcut)

from core.config import (
    ConfigManager, save_scan_path, load_scan_path, save_language,
    get_server_path, save_server_path, load_server_path,
    save_ui_prefs, load_ui_prefs,
    load_theme, save_theme,
    load_last_preset, save_last_preset,
    LOGS_DIR, LAST_RUN_LOG,
)
from core.constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
    LOG_MAX_BLOCK_COUNT, UNDO_HISTORY_MAX, PREVIEW_TIMER_MS, UNDO_DEBOUNCE_MS,
    VERSION_CHECK_TIMEOUT_S,
)
from ui.log_parser import colorize_log_line, parse_log_line, line_level
from ui.command_builder import CommandBuilder, quote_arg
from ui.runtime_info import build_info_html, empty_info_html
from core.runner import ServerRunner
from core.i18n import t, get_language, set_language
from ui.model_browser import ModelBrowser
from ui.basic_panel import BasicPanel
from ui.advanced_panel import AdvancedPanel
from ui.gguf_inspector import GGUFInspectorDialog


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
        self._applying_values = False
        self._pending_webui_url = None
        self._log_tail = ""
        # B2: log lines are parsed immediately but rendered into this buffer;
        # a 100ms timer flushes the buffer with a single insertHtml, so
        # verbose logs no longer trigger one Qt layout pass per line.
        # E3: each entry is (level|None, html) — level None = always visible
        # (banners). _log_records mirrors the visible document and powers the
        # level-filter rebuild; it is capped at LOG_MAX_BLOCK_COUNT like the
        # document itself.
        self._log_html: list[tuple] = []
        self._log_records: list[tuple] = []
        self._log_flush_timer = QTimer()
        # E3: full (un-truncated) log of the current server run
        self._run_log_file = None
        self._run_log_failed = False
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.timeout.connect(self._flush_log_buffer)
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

    def init_ui(self):
        self.setWindowTitle("🦙 llama.cpp Launcher")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self._apply_theme()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # E2: kept as an instance attribute so closeEvent can persist its sizes
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._create_left_panel()
        self.splitter.addWidget(left_panel)

        right_panel = self._create_right_panel()
        self.splitter.addWidget(right_panel)

        self.splitter.setSizes([280, 920])
        main_layout.addWidget(self.splitter)

        self._create_menu_bar()
        self._create_status_bar()

    def _create_left_panel(self):
        widget = QWidget()
        # C8: no setFixedWidth — the QSplitter handle must stay draggable.
        # Initial 280px comes from splitter.setSizes(); min/max keep the
        # drag range sane.
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

        self.preset_group = QGroupBox(t("预设管理"))
        preset_layout = QVBoxLayout(self.preset_group)
        preset_layout.setContentsMargins(6, 20, 6, 6)

        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._show_preset_created_hint)
        self._refresh_presets()
        preset_layout.addWidget(self.preset_combo)

        preset_btns = QHBoxLayout()
        self.btn_load = QPushButton(t("加载"))
        self.btn_save = QPushButton(t("保存"))
        self.btn_delete = QPushButton(t("删除"))
        self.btn_load.clicked.connect(self._load_preset)
        self.btn_save.clicked.connect(self._save_preset)
        self.btn_delete.clicked.connect(self._delete_preset)
        preset_btns.addWidget(self.btn_load)
        preset_btns.addWidget(self.btn_save)
        preset_btns.addWidget(self.btn_delete)
        preset_layout.addLayout(preset_btns)

        preset_io = QHBoxLayout()
        self.btn_import = QPushButton(t("导入"))
        self.btn_export = QPushButton(t("导出"))
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
        layout.addWidget(self.stacked)

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
        self.btn_start = QPushButton(t("▶ 启动服务"))
        self.btn_start.setFixedHeight(40)
        self.btn_start.setObjectName("startBtn")
        self.btn_stop = QPushButton(t("■ 停止服务"))
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setObjectName("stopBtn")
        self.btn_copy_cmd = QPushButton(t("📋 复制命令"))
        self.btn_copy_cmd.setFixedHeight(40)
        self.btn_webui = QPushButton(t("🌐 打开WebUI"))
        self.btn_webui.setFixedHeight(40)


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

        self.version_label = QLabel(t("🔍 检测中..."))
        self.version_label.setStyleSheet("color: #6b7280; font-size: 12px;")
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
        """)
        self.log_output.document().setMaximumBlockCount(LOG_MAX_BLOCK_COUNT)

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
        for b in (self.btn_log_search_prev, self.btn_log_search_next, self.btn_log_search_close):
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
        for lvl, tip in (("D", t("调试")), ("I", t("信息")), ("W", t("警告")), ("E", t("错误"))):
            box = QCheckBox(lvl)
            box.setChecked(True)
            box.setToolTip(tip)
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
        """)
        self.info_display.setHtml(empty_info_html())

        self.tab_widget.addTab(log_tab, t("📄 日志输出"))
        self.tab_widget.addTab(self.info_display, t("📊 运行信息"))
        layout.addWidget(self.tab_widget, 1)

        return widget

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
        self._retry_pending_splitter(8)
        if not self.preview_timer.isActive():
            self.preview_timer.start(PREVIEW_TIMER_MS)
            self._update_cmd_preview()

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
            QMessageBox.warning(self, t("警告"), t("请选择一个模型文件"))
            return False

        model_path = v["model"]
        # A8: llama-server resolves relative paths against the process work_dir
        # (the exe directory in frozen mode), so the existence check must use
        # the same base rather than the launcher's CWD.
        model_file = Path(model_path)
        if not model_file.is_absolute():
            model_file = self.work_dir / model_file
        if not model_file.exists():
            QMessageBox.warning(self, t("警告"), t("模型文件不存在:\n{model_path}", model_path=model_path))
            return False

        host = v.get('host', '127.0.0.1')
        port = v.get("port", 8080)
        # A7: probe the host that will actually be bound. 0.0.0.0/:: accept
        # loopback connections, so 127.0.0.1 is the right probe target then.
        check_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        if self._is_port_in_use(port, check_host):
            reply = QMessageBox.question(
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
            QMessageBox.warning(self, t("WebUI未启用"), t("当前配置已关闭WebUI (--no-webui)，请在设置中启用后再打开。"))
            return
        if not self.runner.is_running:
            reply = QMessageBox.question(
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
        QMessageBox.critical(self, t("错误"), msg)
        self.statusBar().showMessage(t("❌ 启动失败: {msg}", msg=msg[:80]))

    def _append_log(self, text):
        # QProcess 的读取块不保证按行对齐，最后一个元素可能是未写完的半行，
        # 先挂起拼到下一个块，否则跨块的一行会被切成两半解析
        text = self._log_tail + text
        self._log_tail = ""
        if not text:
            return
        lines = text.split("\n")
        self._log_tail = lines.pop()
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
        # E3: banners go through the record system (level None = always
        # visible) so they survive level-filter rebuilds
        self._log_html.append((None, html))
        self._flush_log_buffer()

    def _flush_log_buffer(self):
        if not self._log_html:
            return
        if self._log_filter_active():
            # Re-render the whole (filtered) document from the records;
            # the pending batch is merged in by the rebuild
            self._rebuild_log_view()
            return
        batch, self._log_html = self._log_html, []
        self._log_records.extend(batch)
        if len(self._log_records) > LOG_MAX_BLOCK_COUNT:
            del self._log_records[:len(self._log_records) - LOG_MAX_BLOCK_COUNT]
        html = "<br>".join(h for _, h in batch)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html)
        if self.chk_auto_scroll.isChecked():
            self._log_scroll_to_bottom()

    # ---------- E3: level filter / search / full run log ----------

    def _log_filter_active(self):
        return not all(b.isChecked() for b in self._log_level_boxes.values())

    def _on_log_level_toggled(self):
        # Always rebuild from the records: the fast path only appends new
        # lines, so it cannot restore lines an earlier filter hid
        self._rebuild_log_view()

    def _log_level_visible(self, level, enabled):
        # F (fatal) lines follow the E (error) filter
        return level is None or level in enabled or (level == "F" and "E" in enabled)

    def _rebuild_log_view(self):
        if self._log_html:
            self._log_records.extend(self._log_html)
            self._log_html = []
            if len(self._log_records) > LOG_MAX_BLOCK_COUNT:
                del self._log_records[:len(self._log_records) - LOG_MAX_BLOCK_COUNT]
        enabled = {lvl for lvl, b in self._log_level_boxes.items() if b.isChecked()}
        html = "<br>".join(
            h for lvl, h in self._log_records if self._log_level_visible(lvl, enabled)
        )
        stick = self.chk_auto_scroll.isChecked() and self._log_at_bottom()
        self.log_output.clear()
        if html:
            cursor = self.log_output.textCursor()
            cursor.insertHtml(html)
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
        # E3: Shift+Enter in the search box searches backwards
        if obj is self.log_search_edit and event.type() == event.Type.KeyPress:
            if event.key() == event.Key.Key_Return and (event.modifiers() & event.Modifier.ShiftModifier):
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
        # 进程结束时最后一个块可能没有换行，把挂起的半行补显出来
        if self._log_tail:
            line = self._log_tail
            self._log_tail = ""
            self._append_log_line(line)
            self._flush_log_buffer()  # final line shows up immediately on stop/error

    def _parse_log_line(self, line):
        if parse_log_line(line, self._runtime_info):
            self._update_info_display()


    def _update_info_display(self):
        self.info_display.setHtml(build_info_html(self._runtime_info))

    def _clear_log(self):
        self._log_html = []
        self._log_records = []
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
            QMessageBox.warning(self, t("错误"), str(e))

    @staticmethod
    def _count_log_lines(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def _ask_export_scope(self, full_lines, view_lines):
        """E3: choose between the visible (truncated) area and the full run log."""
        box = QMessageBox(self)
        box.setWindowTitle(t("导出日志"))
        box.setText(t("选择要导出的日志范围"))
        btn_view = box.addButton(
            t("仅显示区（最近 {n} 行）", n=view_lines), QMessageBox.ButtonRole.ActionRole)
        btn_full = box.addButton(
            t("完整日志（{n} 行）", n=full_lines), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(t("取消"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
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
        current_name = self.preset_combo.currentText()
        dlg = QDialog(self)
        dlg.setWindowTitle(t("保存预设"))
        form = QFormLayout(dlg)
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
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            return
        presets = self.config.list_presets()
        exists = any(p["name"] == name for p in presets)
        if exists and name != current_name:
            reply = QMessageBox.question(
                self, t("预设已存在"),
                t("预设 '{name}' 已存在，是否覆盖？", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        elif exists and name == current_name:
            reply = QMessageBox.question(
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
            QMessageBox.warning(self, t("保存失败"),
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
        reply = QMessageBox.question(
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
            reply = QMessageBox.question(
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
            QMessageBox.warning(self, t("导入失败"), t("预设导入失败，请检查文件是否为有效的预设 JSON。"))

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
            QMessageBox.warning(self, t("导出失败"), t("预设导出失败，请检查目标路径是否可写。"))

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
        dialog = QDialog(self)
        dialog.setWindowTitle(t("llama-server 路径"))
        form = QFormLayout(dialog)
        resolved = get_server_path()
        explicit = load_server_path()
        # Prefill a dead explicit setting would just re-verify the same miss —
        # fall back to the currently resolved path in that case.
        prefill = explicit if (explicit and Path(explicit).is_file()) else \
            (resolved if resolved != "llama-server" else "")
        path_edit = QLineEdit(prefill)
        if not prefill:
            path_edit.setPlaceholderText(t("未在 PATH 中找到 llama-server，请手动选择"))
        row = QHBoxLayout()
        row.addWidget(path_edit, 1)
        browse_btn = QPushButton(t("浏览..."))

        def _browse():
            found, _ = QFileDialog.getOpenFileName(
                dialog, t("llama-server 路径"), path_edit.text() or "",
                "llama-server (llama-server*.exe);;Executables (*.exe);;All files (*.*)"
            )
            if found:
                path_edit.setText(found)

        browse_btn.clicked.connect(_browse)
        row.addWidget(browse_btn)
        form.addRow(t("llama-server 可执行文件路径:"), row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        path = str(Path(path_edit.text().strip()).expanduser())
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
            if QMessageBox.question(self, t("llama-server 路径"),
                                    t("路径验证失败，仍要保存吗？")) != QMessageBox.StandardButton.Yes:
                return
        save_server_path(path)
        self.statusBar().showMessage(t("llama-server 路径已设置: {path}", path=path), 8000)
        # Refresh version label + live defaults against the new binary (A10 flow)
        if hasattr(self, '_startup_worker') and self._startup_worker is not None and self._startup_worker.isRunning():
            self._startup_worker.wait(2000)
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
        if isinstance(geo, str) and geo:
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(geo.encode("ascii"))))
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
        adv_tab = prefs.get("adv_tab")
        if isinstance(adv_tab, int) and not isinstance(adv_tab, bool) \
                and 0 <= adv_tab < self.advanced_panel.tabs.count():
            self.advanced_panel.tabs.setCurrentIndex(adv_tab)
        bot_tab = prefs.get("bottom_tab")
        if isinstance(bot_tab, int) and not isinstance(bot_tab, bool) \
                and 0 <= bot_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(bot_tab)

    def _save_ui_state(self):
        # E2: persist for the next launch (written on close)
        import base64
        save_ui_prefs({
            "geometry": base64.b64encode(bytes(self.saveGeometry())).decode("ascii"),
            "splitter": [int(s) for s in self.splitter.sizes()],
            "mode": self.mode_combo.currentIndex(),
            "adv_tab": self.advanced_panel.tabs.currentIndex(),
            "bottom_tab": self.tab_widget.currentIndex(),
        })

    def closeEvent(self, event):
        if self.runner.is_running:
            self.runner.stop(blocking=True)
        self.model_browser.shutdown()
        if hasattr(self, '_startup_worker') and self._startup_worker is not None:
            self._startup_worker.quit()
            self._startup_worker.wait(2000)
        self._close_run_log()
        self._save_ui_state()
        event.accept()

    def _create_menu_bar(self):
        from PyQt6.QtGui import QActionGroup
        menubar = self.menuBar()

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

        # Language menu
        self.lang_menu = menubar.addMenu(t("语言"))
        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)

        self._action_zh = QAction(self._create_text_icon("中", QColor("#e74c3c")), t("中文"), self)
        self._action_zh.setCheckable(True)
        self._action_zh.setChecked(get_language() == "zh")
        self._action_zh.triggered.connect(lambda: self._switch_language("zh"))
        self._lang_group.addAction(self._action_zh)
        self.lang_menu.addAction(self._action_zh)

        self._action_en = QAction(self._create_text_icon("En", QColor("#3498db")), t("English"), self)
        self._action_en.setCheckable(True)
        self._action_en.setChecked(get_language() == "en")
        self._action_en.triggered.connect(lambda: self._switch_language("en"))
        self._lang_group.addAction(self._action_en)
        self.lang_menu.addAction(self._action_en)

        self.help_menu = menubar.addMenu(t("帮助"))
        # E5: theme toggle (checkable, persisted)
        self._theme_action = QAction(t("🌙 深色主题"), self)
        self._theme_action.setCheckable(True)
        self._theme_action.setChecked(self.theme == "dark")
        self._theme_action.triggered.connect(self._toggle_theme)
        self.help_menu.addAction(self._theme_action)
        self.help_menu.addSeparator()
        self._about_action = QAction(self._create_text_icon("?", QColor("#9b59b6")), t("关于"), self)
        self._about_action.triggered.connect(self._show_about)
        self.help_menu.addAction(self._about_action)

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
        msg = QMessageBox(self)
        msg.setWindowTitle(t("关于"))
        msg.setIcon(QMessageBox.Icon.Information)
        version_info = ""
        if getattr(self, "_server_version_line", ""):
            version_info = t("当前 llama-server: {line}",
                             line=self._server_version_line) + "<br><br>"
        msg.setText(
            "<b>🦙 llama.cpp Launcher</b><br><br>"
            + t("一个功能丰富的图形化 llama-server 启动器，帮助您轻松管理和运行 GGUF 格式的大语言模型。<br><br>")
            + version_info
            + t("<b>主要功能：</b><br>")
            + t("📦 <b>模型管理</b> — 自动扫描本地 GGUF 模型，显示文件大小，快速选择模型和多模态投影（mmproj）<br>")
            + t("⚙️ <b>基础/高级模式</b> — 基础模式提供常用参数快速调节，高级模式支持 100+ 参数精细调优<br>")
            + t("🎲 <b>采样控制</b> — 温度、Top-P、Top-K、Min-P、重复惩罚、DRY、Mirostat 等完整采样参数<br>")
            + t("🖥️ <b>GPU 优化</b> — 智能 GPU 层数分配、Flash Attention、KV Cache 卸载、多 GPU 张量分割<br>")
            + t("💬 <b>聊天模板</b> — 支持 Jinja 模板引擎，自动检测模型聊天格式，支持推理模式（Reasoning）<br>")
            + t("🌐 <b>服务管理</b> — 自定义主机/端口、API 密钥、SSL 加密、连续批处理、多槽位并发<br>")
            + t("💾 <b>预设系统</b> — 保存、加载、导入/导出参数预设，快速切换不同模型配置<br>")
            + t("📋 <b>命令预览</b> — 实时生成 llama-server 命令行，一键复制，方便脚本集成<br>")
            + t("📊 <b>运行监控</b> — 实时日志解析（兼容新旧 llama.cpp 格式）、硬件信息展示、运行时间统计<br>")
            + t("🔬 <b>GGUF 检查器</b> — 深度解析 GGUF 文件结构：元数据、张量信息、量化分布、逐层分析、文件名校验、诊断检查<br>")
            + t("🌐 <b>国际化</b> — 支持中文/英文界面实时切换，无需重启<br>")
            + "<br>"
            + t("<b>技术栈：</b> PyQt6 · Python · llama.cpp<br>")
            + t("默认参数自动从 llama-server --help 动态获取，确保与您的版本完全匹配。")
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _create_model_info_group(self):
        group = QGroupBox(t("📊 模型信息"))
        self.model_info_group = group
        layout = QGridLayout(group)
        layout.setContentsMargins(10, 20, 10, 8)
        layout.setSpacing(6)
        layout.setColumnStretch(1, 1)

        self.model_info_labels = {}
        self._model_info_label_widgets = {}
        info_items = [
            ("model_size", "📦 模型大小"),
            ("mmproj_size", "🖼️ 多模态投影"),
            ("total_size", "📁 权重总大小"),
            ("model_params", "🔢 模型参数量"),
            ("quant_type", "📐 量化类型"),
        ]
        for row_idx, (key, label_text) in enumerate(info_items):
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
        btn_row = len(info_items)
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
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
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
        box = QMessageBox(self)
        box.setWindowTitle(t("参数版本差异"))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(t("检测到 {n} 项参数与当前 llama-server 版本不匹配",
                     n=len(self._drift_missing) + len(self._drift_changed)))
        box.setDetailedText("\n".join(lines))
        box.exec()

    def _switch_language(self, lang):
        set_language(lang)
        save_language(lang)
        self._action_zh.setChecked(lang == "zh")
        self._action_en.setChecked(lang == "en")
        self.retranslate_ui()

    def retranslate_ui(self):
        # Left panel
        self.model_browser.retranslate_ui()
        self.preset_group.setTitle(t("预设管理"))
        self.btn_load.setText(t("加载"))
        self.btn_save.setText(t("保存"))
        self.btn_delete.setText(t("删除"))
        self.btn_import.setText(t("导入"))
        self.btn_export.setText(t("导出"))
        self.drift_button.setToolTip(t("参数与当前版本存在差异，点击查看完整列表"))
        # Model info labels
        self.model_info_group.setTitle(t("📊 模型信息"))
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
        for lvl, tip in (("D", t("调试")), ("I", t("信息")), ("W", t("警告")), ("E", t("错误"))):
            self._log_level_boxes[lvl].setToolTip(tip)
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
        self.lang_menu.setTitle(t("语言"))
        self.help_menu.setTitle(t("帮助"))
        self._theme_action.setText(t("🌙 深色主题"))
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
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage(t("就绪"))

    def _apply_theme(self):
        """E5: apply the current theme to the window and to the application
        (so top-level dialogs — GGUF inspector, path dialogs — follow it)."""
        qss = self._get_stylesheet(self.theme)
        self.setStyleSheet(qss)
        # Theme-aware sheet for the bottom tabs (their inline QSS would
        # otherwise override the app/window dark rules); init_ui() calls
        # _apply_theme() before the tab widget exists, hence the guard
        tabs = getattr(self, "tab_widget", None)
        if tabs is not None:
            tabs.setStyleSheet(self._bottom_tabs_qss(self.theme))
        app = QApplication.instance()
        # Skip the app-level apply when the sheet is already identical —
        # re-applying forces a full re-polish of every top-level window
        if app is not None and app.styleSheet() != qss:
            app.setStyleSheet(qss)

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
        qss = MainWindow._THEME_TEMPLATE
        for key, value in palette.items():
            qss = qss.replace("@@" + key + "@@", value)
        return qss

    _THEME_PALETTES = {
        "light": {
            "win_bg": "#f0f2f5", "text": "#1a1a2e", "field_bg": "#ffffff",
            "border": "#d0d4dc", "muted": "#666", "hover_bg": "#e8ecf0",
            "pressed_bg": "#d8dce0", "sub_border": "#b0b8c0",
            "sb_hover": "#8a9098", "combo_arrow": "#333",
            "slider_rim": "#ffffff", "tab_sel_bg": "#ffffff",
            "start_dis_bg": "#c8d8c8", "start_dis_fg": "#8a9a8a",
            "stop_dis_bg": "#d8c8c8", "stop_dis_fg": "#9a8a8a",
            "webui_dis_bg": "#c8d0d8", "webui_dis_fg": "#8a9098",
        },
        # Catppuccin-ish dark, harmonized with the always-dark log areas
        "dark": {
            "win_bg": "#1e1e2e", "text": "#cdd6f4", "field_bg": "#181825",
            "border": "#313244", "muted": "#7f849c", "hover_bg": "#2a2a3d",
            "pressed_bg": "#313244", "sub_border": "#45475a",
            "sb_hover": "#585b70", "combo_arrow": "#cdd6f4",
            "slider_rim": "#1e1e2e", "tab_sel_bg": "#1e1e2e",
            "start_dis_bg": "#2e3d34", "start_dis_fg": "#748a7c",
            "stop_dis_bg": "#3d2e2e", "stop_dis_fg": "#8a7474",
            "webui_dis_bg": "#2e333d", "webui_dis_fg": "#6b7280",
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
                padding: 8px 24px;
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
                padding: 8px 24px;
            }
            QPushButton#stopBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f87171, stop:1 #ef4444);
            }
            QPushButton#stopBtn:disabled {
                background: @@stop_dis_bg@@;
                color: @@stop_dis_fg@@;
            }
            QPushButton#webuiBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 20px;
            }
            QPushButton#webuiBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QPushButton#webuiBtn:disabled {
                background: @@webui_dis_bg@@;
                color: @@webui_dis_fg@@;
                border: 1px solid @@sub_border@@;
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
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid @@combo_arrow@@;
                margin-right: 4px;
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
            QStatusBar {
                background-color: @@field_bg@@;
                color: @@muted@@;
                border-top: 1px solid @@border@@;
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
        """

