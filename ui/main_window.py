import html as html_mod
import os
import re
import shlex
import socket
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QPlainTextEdit, QComboBox, QInputDialog,
    QMessageBox, QFileDialog, QStatusBar,
    QCheckBox, QGroupBox, QTabWidget, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QTextOption, QIcon, QPixmap, QPainter, QColor

from core.config import ConfigManager, save_scan_path, load_scan_path, save_language
from core.defaults import _PRIO_REVERSE
from core.runner import ServerRunner
from core.i18n import t, get_language, set_language
from ui.model_browser import ModelBrowser
from ui.basic_panel import BasicPanel
from ui.advanced_panel import AdvancedPanel


def _compile_log_patterns():
    """Pre-compile all log parsing patterns for efficient per-line matching."""
    _re = lambda pat: re.compile(pat, re.IGNORECASE)
    patterns = []

    def _add(checks, regex, handler, exclude=None):
        patterns.append((
            tuple(checks) if isinstance(checks, (list, tuple)) else (checks,),
            tuple(exclude) if exclude else (),
            _re(regex) if isinstance(regex, str) else regex,
            handler,
        ))

    def _simple(checks, regex, key, transform, exclude=None):
        def handler(info, m):
            info[key] = transform(m)
            return True
        _add(checks, regex, handler, exclude)

    def _kv(checks, regex, key, exclude=None):
        _simple(checks, regex, key, lambda m: m.group(1).strip(), exclude)

    def _int_comma(checks, regex, key, exclude=None):
        _simple(checks, regex, key, lambda m: f"{int(m.group(1)):,}", exclude)

    # ========== NEW FORMAT (v9174+) ==========

    # --- GPU info (new: `- CUDA0 : NVIDIA GeForce RTX 5090 (32606 MiB, 30991 MiB free)`) ---
    def _handle_gpu_new(info, m):
        idx = m.group(1)
        name = m.group(2).strip()
        total = m.group(3).strip()
        free = m.group(4).strip()
        info[f"gpu{idx}_name"] = name
        info[f"gpu{idx}_vram"] = f"{total} MiB"
        info[f"gpu{idx}_free"] = f"{free} MiB"
        if "gpu_name" not in info:
            info["gpu_name"] = name
            info["gpu_vram"] = f"{total} MiB"
            info["free_vram"] = f"{free} MiB"
        return True
    _add("cuda", r"-\s+CUDA(\d+)\s+:\s+(.+?)\s+\(([\d,]+)\s*MiB,\s*([\d,]+)\s*MiB\s+free\)", _handle_gpu_new)

    def _handle_cpu_new(info, m):
        info["cpu_name"] = m.group(1).strip()
        info["cpu_ram"] = f"{m.group(2).strip()} MiB"
        return True
    _add("- cpu", r"-\s+CPU\s+:\s+(.+?)\s+\(([\d,]+)\s*MiB", _handle_cpu_new)

    # --- Threads (new: `srv init: using 19 threads for HTTP server`) ---
    def _handle_threads_http(info, m):
        info["threads_http"] = m.group(1)
        return True
    _add(["srv", "using", "threads for http"], r"using\s+(\d+)\s+threads\s+for\s+HTTP", _handle_threads_http)

    # --- Slots (new: `srv load_model: initializing slots, n_slots = 1`) ---
    _int_comma(["srv", "initializing slots"], r"n_slots\s*=\s*(\d+)", "n_slots")

    # --- Slot context (new: `slot load_model: id  0 | task -1 | new slot, n_ctx = 65536`) ---
    def _handle_slot_ctx(info, m):
        info["ctx_size"] = f"{int(m.group(1)):,}"
        info["n_slots"] = info.get("n_slots", "1")
        return True
    _add(["slot", "new slot"], r"n_ctx\s*=\s*(\d+)", _handle_slot_ctx)

    # --- Context warning (new: `llama_context: n_ctx_seq (65536) < n_ctx_train (262144)`) ---
    def _handle_ctx_warning(info, m):
        info["ctx_size_seq"] = f"{int(m.group(1)):,}"
        info["train_ctx"] = f"{int(m.group(2)):,}"
        return True
    _add(["llama_context", "n_ctx_seq", "n_ctx_train"], r"n_ctx_seq\s*\((\d+)\)\s*<\s*n_ctx_train\s*\((\d+)\)", _handle_ctx_warning)

    # --- Prompt cache (new: `srv load_model: use '--cache-ram 0' to disable the prompt cache`) ---
    def _handle_cache_hint(info, m):
        if "prompt_cache" not in info:
            info["prompt_cache"] = t("已启用")
        return True
    _add(["srv", "prompt cache"], r"disable the prompt cache", _handle_cache_hint)

    # --- Speculative decoding (new: `srv load_model: speculative decoding will use checkpoints`) ---
    _simple(["srv", "speculative decoding"], r"speculative decoding", "speculative_decoding",
            lambda m: t("已启用"))

    # --- Model loaded (new: `srv main: model loaded`) ---
    def _handle_model_loaded_new(info, m):
        info["status"] = t("🔄 模型加载完成")
        return True
    _add(["srv", "model loaded"], r"model loaded", _handle_model_loaded_new)

    # --- Thinking mode (new: chat template with <think> tag) ---
    def _handle_thinking_new(info, m):
        info["thinking_mode"] = t("已启用")
        return True
    _add(["chat template", "<think>"], r"<think>", _handle_thinking_new)

    # --- KV unified warning (new: `srv init: --cache-idle-slots requires --kv-unified, disabling`) ---
    def _handle_kv_unified_hint(info, m):
        info["kv_unified"] = t("需要 --kv-unified，已禁用")
        return True
    _add(["srv", "kv-unified", "disabling"], r"requires.*kv-unified.*disabling", _handle_kv_unified_hint)

    # --- Load hparams warnings (new: `load_hparams: Qwen-VL models require ...`) ---
    _kv(["load_hparams", "image", "tokens"], r"require.*?(\d+)\s*image\s*tokens", "vision_min_tokens")

    # ========== OLD FORMAT (legacy) ==========

    # --- GPU info (old: `Device 0: NVIDIA GeForce RTX 4090, compute capability 8.9, VRAM: 24564 MiB`) ---
    def _handle_device_old(info, m):
        info["gpu_name"] = m.group(1).strip()
        info["gpu_vram"] = f"{m.group(2).strip()} MiB"
        return True
    _add("device 0:", r"Device \d+: (.+?),.*?VRAM:\s*([\d,]+)\s*MiB", _handle_device_old)

    def _handle_compute_cap(info, m):
        info["gpu_compute_cap"] = m.group(1)
        return True
    _add("device 0:", r"compute capability\s+([\d.]+)", _handle_compute_cap)

    # --- System info (old) ---
    _kv("system_info:", r"n_threads\s*=\s*(\d+)", "n_threads")
    _kv("system_info:", r"n_threads_batch\s*=\s*(\d+)", "n_threads_batch")
    _kv("system_info:", r"total_threads\s*=\s*(\d+)", "total_threads")

    # --- Projected VRAM (old) ---
    def _handle_projected(info, m):
        info["projected_vram"] = f"{m.group(1).strip()} MiB"
        info["free_vram"] = f"{m.group(2).strip()} MiB"
        return True
    _add(["projected to use", "device memory"], r"use ([\d,]+)\s*MiB.*?vs\.\s*([\d,]+)\s*MiB", _handle_projected)

    # --- Model loading (old) ---
    def _handle_model_file_old(info, m):
        info["model_file"] = os.path.basename(m.group(1))
        return True
    _add(["loading model", ".gguf"], r"'([^']+\.gguf)'", _handle_model_file_old, exclude=["multimodal"])

    # Also match new format: `srv main: loading model` + path in args
    def _handle_loading_model_new(info, m):
        info["model_file"] = os.path.basename(m.group(1))
        return True
    _add(["srv", "loading model", ".gguf"], r"([\w/\\:. -]+\.gguf)", _handle_loading_model_new)

    # --- GGUF / model info (old: print_info format) ---
    _simple("file format", r"GGUF V(\d+)", "gguf_version", lambda m: f"V{m.group(1)}")
    _kv(["file type", "print_info"], r"file type\s*=\s*(.+)", "quant_type")
    _kv(["file size", "print_info"], r"file size\s*=\s*(.+)", "file_size")
    _kv(["model params", "print_info"], r"model params\s*=\s*(.+)", "model_params")
    _kv("general.name", r"general\.name\s+str\s+=\s+(.+)", "model_name")
    _simple(["arch", "print_info"], r"arch\s+=\s+(\w+)", "arch", lambda m: m.group(1))
    _int_comma(["n_vocab", "print_info"], r"n_vocab\s+=\s+(\d+)", "vocab_size")
    _int_comma(["n_ctx_train", "print_info"], r"n_ctx_train\s+=\s+(\d+)", "train_ctx")
    _int_comma(["n_embd", "print_info"], r"n_embd\s+=\s+(\d+)", "embed_dim",
               exclude=["n_embd_head", "n_embd_k_gqa", "n_embd_v_gqa", "n_embd_inp"])
    _kv(["n_layer", "print_info"], r"n_layer\s+=\s+(\d+)", "n_layers")
    _int_comma(["n_ff", "print_info"], r"n_ff\s+=\s+(\d+)", "n_ff")
    _int_comma(["n_swa", "print_info"], r"n_swa\s+=\s+(\d+)", "sliding_window")
    _simple(["vocab type", "print_info"], r"vocab type\s+=\s+(\w+)", "vocab_type", lambda m: m.group(1))
    _simple(["bos token", "print_info"], r"BOS token\s+=\s+(\d+)\s+'([^']*)'",
            "bos_token", lambda m: f"{m.group(1)} '{m.group(2)}'")
    _simple(["eos token", "print_info"], r"EOS token\s+=\s+(\d+)\s+'([^']*)'",
            "eos_token", lambda m: f"{m.group(1)} '{m.group(2)}'")
    _kv(["freq_base_train", "print_info"], r"freq_base_train\s+=\s+([\d.]+)", "freq_base")

    # --- Context (old) ---
    _int_comma(["n_batch", "llama_context"], r"n_batch\s+=\s+(\d+)", "n_batch")
    _int_comma(["n_ubatch", "llama_context"], r"n_ubatch\s+=\s+(\d+)", "n_ubatch")
    _kv(["freq_base", "llama_context"], r"freq_base\s+=\s+([\d.]+)", "freq_base_runtime")
    _int_comma(["n_ctx_seq", "llama_context"], r"n_ctx_seq\s+=\s+(\d+)", "ctx_size_seq")
    _int_comma(["n_seq_max", "llama_context"], r"n_seq_max\s+=\s+(\d+)", "n_slots")

    # --- Tensors / offload (old) ---
    def _handle_tensor_types(info, m):
        info.setdefault("tensor_types", {})[m.group(1)] = int(m.group(2))
        return True
    _add(["llama_model_loader", "- type", "tensors"], r"- type\s+(\w+):\s+(\d+)\s+tensors", _handle_tensor_types)

    def _handle_gpu_offload(info, m):
        info["gpu_offload"] = f"{m.group(1)}/{m.group(2)} " + t("层")
        return True
    _add(["offloaded", "layers", "load_tensors"], r"offloaded (\d+)/(\d+) layers", _handle_gpu_offload)

    # --- VRAM buffers (old) ---
    _kv(["model buffer size", "cuda"], r"CUDA\d+\s+model buffer size\s+=\s+(.+)", "model_vram")
    _kv("cpu_mapped model buffer size", r"CPU_Mapped model buffer size\s+=\s+(.+)", "cpu_buffer")

    def _handle_kv_buffer(info, m):
        prev_total = info.get("kv_cache_total", 0.0)
        if isinstance(prev_total, str):
            pm = re.search(r"([\d.]+)", prev_total)
            prev_total = float(pm.group(1)) if pm else 0.0
        curr_match = re.search(r"([\d.]+)", m.group(1))
        if curr_match:
            info["kv_cache_total"] = prev_total + float(curr_match.group(1))
            return True
        return False
    _add(["kv buffer size", "cuda"], r"CUDA\d+\s+KV buffer size\s+=\s+(.+)", _handle_kv_buffer)

    _kv(["compute buffer size", "cuda"], r"CUDA\d+\s+compute buffer size\s+=\s+(.+)", "compute_buffer",
         exclude=["host", "cpu"])

    # --- Graph (old) ---
    _kv(["graph nodes", "sched_reserve"], r"graph nodes\s+=\s+(\d+)", "graph_nodes")
    _kv(["graph splits", "sched_reserve"], r"graph splits\s+=\s+(\d+)", "graph_splits")

    # --- n_ctx (old) ---
    _int_comma(["n_ctx", "llama_context"], r"n_ctx\s+=\s+(\d+)", "ctx_size",
               exclude=["n_ctx_seq", "n_ctx_orig", "n_ctx_train"])

    # --- Prompt cache (old) ---
    _kv("prompt cache is enabled", r"size limit:\s+([\d,]+)\s*MiB", "prompt_cache")

    # --- Vision (old) ---
    def _handle_mmproj(info, m):
        info["mmproj_file"] = os.path.basename(m.group(1))
        return True
    _add("loaded multimodal model", r"'([^']+\.gguf)'", _handle_mmproj)
    _kv(["model size:", "mib", "load_hparams:"], r"model size:\s+([\d.]+)\s*MiB", "vision_model_size")
    _kv(["image_size:", "load_hparams:"], r"image_size:\s+(\d+)", "vision_image_size")

    # --- Thinking (old) ---
    def _handle_thinking_old(info, m):
        info["thinking_mode"] = t("已启用") if m.group(1) == "1" else t("已禁用")
        return True
    _add(["thinking", "chat template"], r"thinking\s*=\s*(\d+)", _handle_thinking_old)

    # --- Address (shared) ---
    def _handle_address(info, m):
        info["address"] = m.group(1)
        return True
    _add("server is listening on", r"http://([\d.]+:\d+)", _handle_address)

    return tuple(patterns)


# Pre-compiled at module level
_LOG_PATTERNS = _compile_log_patterns()


class _VersionCheckWorker(QThread):
    result_ready = pyqtSignal(str, str, str)  # version_num, commit, raw_line
    failed = pyqtSignal(str)  # error_type: "not_found", "no_version", "error"

    def run(self):
        try:
            result = subprocess.run(
                ["llama-server", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
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
                    self.result_ready.emit(m.group(1), m.group(2), version_line)
                else:
                    self.result_ready.emit("", "", version_line)
            else:
                self.failed.emit("no_version")
        except FileNotFoundError:
            self.failed.emit("not_found")
        except Exception:
            self.failed.emit("error")


class MainWindow(QMainWindow):
    def __init__(self, work_dir=None, defaults=None, chat_templates=None):
        super().__init__()
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        saved_scan_path = load_scan_path()
        if saved_scan_path and Path(saved_scan_path).exists():
            self.model_dir = Path(saved_scan_path)
        else:
            self.model_dir = self.work_dir
        self.defaults = defaults or {}
        self.chat_templates = chat_templates or []
        self.config = ConfigManager(defaults=self.defaults)
        self.runner = ServerRunner()
        self.is_advanced = False
        self.params = dict(self.defaults)
        self.params_history = [dict(self.params)]
        self.max_history = 20
        self._last_saved = dict(self.params)
        self._pending_snapshot = False
        self.start_time = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_timer)
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self._update_cmd_preview)
        self.preview_timer.start(300)
        self._undo_debounce = QTimer()
        self._undo_debounce.setSingleShot(True)
        self._undo_debounce.timeout.connect(self._flush_snapshot)
        self._runtime_info = {}
        self._current_state = None
        self._mode_switching = False
        self.init_ui()
        self._connect_signals()
        self._check_server_version()

    def init_ui(self):
        self.setWindowTitle("🦙 llama.cpp Launcher")
        self.resize(1360, 860)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(self._get_stylesheet())

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)

        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([280, 920])
        main_layout.addWidget(splitter)

        self._create_menu_bar()
        self._create_status_bar()

    def _create_left_panel(self):
        widget = QWidget()
        widget.setFixedWidth(280)
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

        cmd_label = QLabel(t("📝 启动命令预览"))
        cmd_label.setStyleSheet("font-weight: bold; color: #7aa2f7; font-size: 13px;")
        layout.addWidget(cmd_label)

        self.cmd_preview = QPlainTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setFont(QFont("Consolas", 9))
        self.cmd_preview.setStyleSheet("background: #121212; color: #7ab0e0; border: 1px solid #444; border-radius: 4px; padding: 4px;")
        self.cmd_preview.setFixedHeight(52)
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
        control_bar.addWidget(self.version_label)

        self.status_indicator = QLabel(t("⏸ 未运行"))
        self.status_indicator.setObjectName("statusStopped")
        self.status_indicator.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 13px;")
        control_bar.addWidget(self.status_indicator)

        self.run_time_label = QLabel(t("⏱ 运行: 00:00"))
        self.run_time_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        control_bar.addWidget(self.run_time_label)

        layout.addLayout(control_bar)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
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
        """)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 10))
        self.log_output.setStyleSheet("background: #121212; color: #cdd6f4; border: none; padding: 4px;")

        log_tab = QWidget()
        log_tab_layout = QVBoxLayout(log_tab)
        log_tab_layout.setContentsMargins(0, 0, 0, 0)

        log_toolbar = QHBoxLayout()
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
        log_tab_layout.addLayout(log_toolbar)
        log_tab_layout.addWidget(self.log_output)

        self.info_display = QTextEdit()
        self.info_display.setReadOnly(True)
        self.info_display.setFont(QFont("Consolas", 10))
        self.info_display.setStyleSheet("""
            background: #121212;
            color: #cdd6f4;
            border: none;
            padding: 8px;
        """)
        self.info_display.setHtml(self._get_empty_info_html())

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
        self.preview_timer.start(300)
        self._update_cmd_preview()

    def _save_current_to_params(self, force=False):
        if not force and self._mode_switching:
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
            self.btn_undo.setEnabled(len(self.params_history) > 1)
            self.statusBar().showMessage(t("已撤销"), 2000)

    def _apply_params_to_current(self):
        if self.is_advanced:
            self.advanced_panel.set_values(self.params)
        else:
            self.basic_panel.set_values(self.params)

    def _get_current_values(self):
        self._save_current_to_params()
        return dict(self.params)

    def _set_current_values(self, values):
        self.params.update(values)
        self._apply_params_to_current()

    def _is_default(self, key, v):
        return v.get(key) == self.defaults.get(key)

    def _build_args_from_params(self):
        return self._build_args_from_values(self.params)

    def _build_args_from_values(self, v):
        args = []
        args.extend(self._build_model_args(v))
        args.extend(self._build_context_args(v))
        args.extend(self._build_sampling_args(v))
        args.extend(self._build_performance_args(v))
        args.extend(self._build_server_args(v))
        args.extend(self._build_chat_args(v))
        args.extend(self._build_advanced_args(v))
        args.extend(self._build_extra_args(v))
        return args

    def _build_model_args(self, v):
        args = []
        if v.get("model"):
            args.extend(["-m", v["model"]])
        if v.get("mmproj"):
            args.extend(["--mmproj", v["mmproj"]])
        if v.get("lora"):
            args.extend(["--lora", ",".join(v["lora"])])
        if v.get("lora_scaled"):
            args.extend(["--lora-scaled", ",".join(v["lora_scaled"])])
        if v.get("control_vector"):
            args.extend(["--control-vector", ",".join(v["control_vector"])])
        if v.get("control_vector_scaled"):
            args.extend(["--control-vector-scaled", ",".join(v["control_vector_scaled"])])
        if v.get("control_vector_layer_range"):
            args.extend(["--control-vector-layer-range", v["control_vector_layer_range"]])
        if not self._is_default("mmproj_auto", v):
            if not v.get("mmproj_auto", True):
                args.append("--no-mmproj-auto")
        if not self._is_default("mmproj_offload", v):
            if not v.get("mmproj_offload", True):
                args.append("--no-mmproj-offload")
        if not self._is_default("image_min_tokens", v):
            img_min = v.get("image_min_tokens", 0)
            if img_min and img_min > 0:
                args.extend(["--image-min-tokens", str(img_min)])
        if not self._is_default("image_max_tokens", v):
            img_max = v.get("image_max_tokens", 0)
            if img_max and img_max > 0:
                args.extend(["--image-max-tokens", str(img_max)])
        if v.get("alias"):
            args.extend(["--alias", v["alias"]])
        if v.get("tags"):
            args.extend(["--tags", v["tags"]])
        if not self._is_default("n_gpu_layers", v):
            ngl = v.get("n_gpu_layers", "auto")
            if ngl:
                if ngl == "all":
                    args.extend(["-ngl", "999"])
                else:
                    try:
                        args.extend(["-ngl", str(int(ngl))])
                    except ValueError:
                        args.extend(["-ngl", "999"])
        return args

    def _build_context_args(self, v):
        args = []
        if not self._is_default("ctx_size", v):
            ctx = v.get("ctx_size", 0)
            if ctx and ctx > 0:
                args.extend(["-c", str(ctx)])
        if not self._is_default("batch_size", v):
            bs = v.get("batch_size", 0)
            if bs > 0:
                args.extend(["-b", str(bs)])
        if not self._is_default("ubatch_size", v):
            ubs = v.get("ubatch_size", 0)
            if ubs > 0:
                args.extend(["-ub", str(ubs)])
        if not self._is_default("n_predict", v):
            args.extend(["-n", str(v["n_predict"])])
        if not self._is_default("keep", v):
            keep = v.get("keep", 0)
            if keep > 0:
                args.extend(["--keep", str(keep)])
        if not self._is_default("cache_prompt", v):
            if not v.get("cache_prompt", True):
                args.append("--no-cache-prompt")
        if not self._is_default("cache_reuse", v):
            cr = v.get("cache_reuse", 0)
            if cr > 0:
                args.extend(["--cache-reuse", str(cr)])
        if not self._is_default("cache_ram", v):
            args.extend(["--cache-ram", str(v["cache_ram"])])
        if not self._is_default("context_shift", v):
            if v.get("context_shift"):
                args.append("--context-shift")
        if not self._is_default("kv_offload", v):
            if not v.get("kv_offload", True):
                args.append("--no-kv-offload")
        if not self._is_default("kv_unified", v):
            if not v.get("kv_unified", True):
                args.append("--no-kv-unified")
        if not self._is_default("cache_type_k", v):
            args.extend(["-ctk", v["cache_type_k"]])
        if not self._is_default("cache_type_v", v):
            args.extend(["-ctv", v["cache_type_v"]])
        if not self._is_default("swa_full", v):
            if v.get("swa_full"):
                args.append("--swa-full")
        if not self._is_default("escape", v):
            if not v.get("escape", True):
                args.append("--no-escape")
        if not self._is_default("defrag_thold", v):
            dt = v.get("defrag_thold", 0)
            if dt and dt > 0:
                args.extend(["--defrag-thold", str(dt)])
        if not self._is_default("cache_idle_slots", v):
            if not v.get("cache_idle_slots", True):
                args.append("--no-cache-idle-slots")
        if not self._is_default("ctx_checkpoints", v):
            args.extend(["-ctxcp", str(v["ctx_checkpoints"])])
        if not self._is_default("checkpoint_every_n_tokens", v):
            args.extend(["-cpent", str(v["checkpoint_every_n_tokens"])])
        return args

    def _build_sampling_args(self, v):
        args = []
        if not self._is_default("temp", v):
            args.extend(["--temp", f'{v["temp"]:.2f}'])
        if not self._is_default("top_k", v):
            args.extend(["--top-k", str(v["top_k"])])
        if not self._is_default("top_p", v):
            args.extend(["--top-p", f'{v["top_p"]:.2f}'])
        if not self._is_default("min_p", v):
            args.extend(["--min-p", f'{v["min_p"]:.2f}'])
        if not self._is_default("typical_p", v):
            args.extend(["--typical-p", f'{v["typical_p"]:.2f}'])
        if not self._is_default("top_n_sigma", v):
            args.extend(["--top-n-sigma", f'{v["top_n_sigma"]:.2f}'])
        if not self._is_default("xtc_probability", v):
            args.extend(["--xtc-probability", f'{v["xtc_probability"]:.2f}'])
        if not self._is_default("xtc_threshold", v):
            args.extend(["--xtc-threshold", f'{v["xtc_threshold"]:.2f}'])
        if not self._is_default("repeat_penalty", v):
            args.extend(["--repeat-penalty", f'{v["repeat_penalty"]:.2f}'])
        if not self._is_default("presence_penalty", v):
            args.extend(["--presence-penalty", f'{v["presence_penalty"]:.2f}'])
        if not self._is_default("frequency_penalty", v):
            args.extend(["--frequency-penalty", f'{v["frequency_penalty"]:.2f}'])
        if not self._is_default("dry_multiplier", v):
            args.extend(["--dry-multiplier", f'{v["dry_multiplier"]:.2f}'])
        if not self._is_default("dry_base", v):
            args.extend(["--dry-base", f'{v["dry_base"]:.2f}'])
        if not self._is_default("dry_allowed_length", v):
            args.extend(["--dry-allowed-length", str(v["dry_allowed_length"])])
        if not self._is_default("dry_penalty_last_n", v):
            args.extend(["--dry-penalty-last-n", str(v["dry_penalty_last_n"])])
        if not self._is_default("adaptive_target", v):
            at = v.get("adaptive_target", -1.0)
            if at >= 0:
                args.extend(["--adaptive-target", f'{at:.2f}'])
        if not self._is_default("adaptive_decay", v):
            ad = v.get("adaptive_decay", 0.9)
            if ad >= 0:
                args.extend(["--adaptive-decay", f'{ad:.2f}'])
        if not self._is_default("repeat_last_n", v):
            args.extend(["--repeat-last-n", str(v["repeat_last_n"])])
        if not self._is_default("seed", v):
            args.extend(["-s", str(v["seed"])])
        if not self._is_default("mirostat", v):
            args.extend(["--mirostat", str(v["mirostat"])])
        if not self._is_default("mirostat_lr", v):
            args.extend(["--mirostat-lr", f'{v["mirostat_lr"]:.2f}'])
        if not self._is_default("mirostat_ent", v):
            args.extend(["--mirostat-ent", f'{v["mirostat_ent"]:.2f}'])
        if not self._is_default("dynatemp_range", v):
            args.extend(["--dynatemp-range", f'{v["dynatemp_range"]:.2f}'])
        if not self._is_default("dynatemp_exp", v):
            args.extend(["--dynatemp-exp", f'{v["dynatemp_exp"]:.2f}'])
        if not self._is_default("grammar", v):
            gr = v.get("grammar", "")
            if gr:
                args.extend(["--grammar", gr])
        if not self._is_default("json_schema", v):
            js = v.get("json_schema", "")
            if js:
                args.extend(["--json-schema", js])
        if not self._is_default("ignore_eos", v):
            if v.get("ignore_eos"):
                args.append("--ignore-eos")
        if not self._is_default("backend_sampling", v):
            if v.get("backend_sampling"):
                args.append("--backend-sampling")
        if not self._is_default("samplers", v):
            samplers = v.get("samplers", "")
            if samplers:
                args.extend(["--samplers", samplers])
        if not self._is_default("sampler_seq", v):
            ss = v.get("sampler_seq", "")
            if ss:
                args.extend(["--sampling-seq", ss])
        if not self._is_default("logit_bias", v):
            lb = v.get("logit_bias", "")
            if lb:
                args.extend(["--logit-bias", lb])
        if not self._is_default("grammar_file", v):
            gf = v.get("grammar_file", "")
            if gf:
                args.extend(["--grammar-file", gf])
        if not self._is_default("json_schema_file", v):
            jsf = v.get("json_schema_file", "")
            if jsf:
                args.extend(["--json-schema-file", jsf])
        return args

    def _build_performance_args(self, v):
        args = []
        if not self._is_default("device", v):
            dev = v.get("device", "")
            if dev:
                args.extend(["--dev", dev])
        if not self._is_default("split_mode", v):
            sm = v.get("split_mode", "")
            if sm:
                args.extend(["-sm", sm])
        if not self._is_default("tensor_split", v):
            ts = v.get("tensor_split", "")
            if ts:
                args.extend(["-ts", ts])
        if not self._is_default("main_gpu", v):
            args.extend(["-mg", str(v["main_gpu"])])
        if not self._is_default("threads", v):
            args.extend(["-t", str(v["threads"])])
        if not self._is_default("threads_batch", v):
            args.extend(["-tb", str(v["threads_batch"])])
        if not self._is_default("threads_http", v):
            args.extend(["--threads-http", str(v["threads_http"])])
        if not self._is_default("prio", v):
            prio_val = v.get("prio", "normal")
            prio_num = _PRIO_REVERSE.get(str(prio_val), 0)
            args.extend(["--prio", str(prio_num)])
        if not self._is_default("prio_batch", v):
            prio_batch_val = v.get("prio_batch", "normal")
            prio_batch_num = _PRIO_REVERSE.get(str(prio_batch_val), 0)
            args.extend(["--prio-batch", str(prio_batch_num)])
        if not self._is_default("flash_attn", v):
            args.extend(["--flash-attn", v["flash_attn"]])
        if not self._is_default("mmap", v):
            if not v.get("mmap", True):
                args.append("--no-mmap")
        if not self._is_default("mlock", v):
            if v.get("mlock"):
                args.append("--mlock")
        if not self._is_default("no_host", v):
            if v.get("no_host"):
                args.append("--no-host")
        if not self._is_default("repack", v):
            if not v.get("repack", True):
                args.append("--no-repack")
        if not self._is_default("fit", v):
            args.extend(["--fit", v["fit"]])
        if not self._is_default("fit_target", v):
            args.extend(["-fitt", str(v["fit_target"])])
        if not self._is_default("fit_ctx", v):
            args.extend(["--fit-ctx", str(v["fit_ctx"])])
        if not self._is_default("check_tensors", v):
            if v.get("check_tensors"):
                args.append("--check-tensors")
        if not self._is_default("n_cpu_moe", v):
            ncmoe = v.get("n_cpu_moe", 0)
            if ncmoe and ncmoe > 0:
                args.extend(["--n-cpu-moe", str(ncmoe)])
        if not self._is_default("direct_io", v):
            if v.get("direct_io"):
                args.append("--direct-io")
        if not self._is_default("numa", v):
            numa = v.get("numa", "")
            if numa and numa != "disable":
                args.extend(["--numa", numa])
        if not self._is_default("warmup", v):
            if not v.get("warmup", True):
                args.append("--no-warmup")
        if not self._is_default("perf", v):
            if v.get("perf"):
                args.append("--perf")
        if not self._is_default("cpu_moe", v):
            if v.get("cpu_moe"):
                args.append("--cpu-moe")
        if not self._is_default("op_offload", v):
            if not v.get("op_offload", True):
                args.append("--no-op-offload")
        if not self._is_default("draft_model", v):
            dm = v.get("draft_model", "")
            if dm:
                args.extend(["--model-draft", dm])
        if not self._is_default("threads_draft", v):
            args.extend(["--threads-draft", str(v["threads_draft"])])
        if not self._is_default("threads_batch_draft", v):
            args.extend(["--threads-batch-draft", str(v["threads_batch_draft"])])
        if not self._is_default("ctx_size_draft", v):
            csd = v.get("ctx_size_draft", 0)
            if csd and csd > 0:
                args.extend(["--ctx-size-draft", str(csd)])
        if not self._is_default("device_draft", v):
            dd = v.get("device_draft", "")
            if dd:
                args.extend(["--device-draft", dd])
        if not self._is_default("n_gpu_layers_draft", v):
            ngld = v.get("n_gpu_layers_draft", "auto")
            if ngld:
                if ngld == "all":
                    args.extend(["--n-gpu-layers-draft", "999"])
                else:
                    try:
                        args.extend(["--n-gpu-layers-draft", str(int(ngld))])
                    except ValueError:
                        pass
        if not self._is_default("cpu_moe_draft", v):
            if v.get("cpu_moe_draft"):
                args.append("--cpu-moe-draft")
        if not self._is_default("n_cpu_moe_draft", v):
            ncmoe_d = v.get("n_cpu_moe_draft", 0)
            if ncmoe_d and ncmoe_d > 0:
                args.extend(["--n-cpu-moe-draft", str(ncmoe_d)])
        if not self._is_default("cache_type_k_draft", v):
            args.extend(["--cache-type-k-draft", v["cache_type_k_draft"]])
        if not self._is_default("cache_type_v_draft", v):
            args.extend(["--cache-type-v-draft", v["cache_type_v_draft"]])
        if not self._is_default("draft_max", v):
            args.extend(["--spec-draft-n-max", str(v["draft_max"])])
        if not self._is_default("draft_min", v):
            dm = v.get("draft_min", 0)
            if dm and dm > 0:
                args.extend(["--spec-draft-n-min", str(dm)])
        if not self._is_default("draft_p_min", v):
            args.extend(["--spec-draft-p-min", f'{v["draft_p_min"]:.2f}'])
        if not self._is_default("spec_type", v):
            st = v.get("spec_type", "none")
            if st and st != "none":
                args.extend(["--spec-type", st])
        if not self._is_default("spec_ngram_size_n", v):
            args.extend(["--spec-ngram-simple-size-n", str(v["spec_ngram_size_n"])])
        if not self._is_default("spec_ngram_size_m", v):
            args.extend(["--spec-ngram-simple-size-m", str(v["spec_ngram_size_m"])])
        if not self._is_default("spec_ngram_min_hits", v):
            args.extend(["--spec-ngram-simple-min-hits", str(v["spec_ngram_min_hits"])])
        return args

    def _build_server_args(self, v):
        args = []
        if not self._is_default("host", v):
            args.extend(["--host", v["host"]])
        if not self._is_default("port", v):
            args.extend(["--port", str(v["port"])])
        if not self._is_default("reuse_port", v):
            if v.get("reuse_port"):
                args.append("--reuse-port")
        if not self._is_default("api_key", v):
            ak = v.get("api_key", "")
            if ak:
                args.extend(["--api-key", ak])
        if not self._is_default("api_prefix", v):
            ap = v.get("api_prefix", "")
            if ap:
                args.extend(["--api-prefix", ap])
        if not self._is_default("path", v):
            pth = v.get("path", "")
            if pth:
                args.extend(["--path", pth])
        if not self._is_default("webui", v):
            if not v.get("webui", True):
                args.append("--no-webui")
        if not self._is_default("webui_config_file", v):
            wcf = v.get("webui_config_file", "")
            if wcf:
                args.extend(["--webui-config-file", wcf])
        if not self._is_default("webui_mcp_proxy", v):
            if v.get("webui_mcp_proxy"):
                args.append("--webui-mcp-proxy")
        if not self._is_default("tools", v):
            tools = v.get("tools", [])
            if tools:
                args.extend(["--tools", ",".join(tools)])
        if not self._is_default("cont_batching", v):
            if not v.get("cont_batching", True):
                args.append("--no-cont-batching")
        if not self._is_default("parallel", v):
            args.extend(["-np", str(v["parallel"])])
        if not self._is_default("timeout", v):
            args.extend(["-to", str(v["timeout"])])
        if not self._is_default("slot_prompt_similarity", v):
            args.extend(["-sps", f'{v["slot_prompt_similarity"]:.2f}'])
        if not self._is_default("slots", v):
            if not v.get("slots", True):
                args.append("--no-slots")
        if not self._is_default("metrics", v):
            if v.get("metrics"):
                args.append("--metrics")
        if not self._is_default("props", v):
            if v.get("props"):
                args.append("--props")
        if not self._is_default("ssl_key_file", v):
            skf = v.get("ssl_key_file", "")
            if skf:
                args.extend(["--ssl-key-file", skf])
        if not self._is_default("ssl_cert_file", v):
            scf = v.get("ssl_cert_file", "")
            if scf:
                args.extend(["--ssl-cert-file", scf])
        if not self._is_default("api_key_file", v):
            akf = v.get("api_key_file", "")
            if akf:
                args.extend(["--api-key-file", akf])
        if not self._is_default("webui_config", v):
            wc = v.get("webui_config", "")
            if wc:
                args.extend(["--webui-config", wc])
        if not self._is_default("slot_save_path", v):
            ssp = v.get("slot_save_path", "")
            if ssp:
                args.extend(["--slot-save-path", ssp])
        if not self._is_default("media_path", v):
            mp = v.get("media_path", "")
            if mp:
                args.extend(["--media-path", mp])
        if not self._is_default("lora_init_without_apply", v):
            if v.get("lora_init_without_apply"):
                args.append("--lora-init-without-apply")
        if not self._is_default("models_max", v):
            args.extend(["--models-max", str(v["models_max"])])
        if not self._is_default("models_autoload", v):
            if not v.get("models_autoload", True):
                args.append("--no-models-autoload")
        if not self._is_default("sleep_idle_seconds", v):
            args.extend(["--sleep-idle-seconds", str(v["sleep_idle_seconds"])])
        return args

    def _build_chat_args(self, v):
        args = []
        if not self._is_default("jinja", v):
            if not v.get("jinja", True):
                args.append("--no-jinja")
        if not self._is_default("chat_template", v):
            ct = v.get("chat_template", "")
            if ct:
                args.extend(["--chat-template", ct])
        if not self._is_default("chat_template_file", v):
            ctf = v.get("chat_template_file", "")
            if ctf:
                args.extend(["--chat-template-file", ctf])
        if not self._is_default("chat_template_kwargs", v):
            ctkw = v.get("chat_template_kwargs", "")
            if ctkw:
                args.extend(["--chat-template-kwargs", ctkw])
        if not self._is_default("skip_chat_parsing", v):
            if v.get("skip_chat_parsing"):
                args.append("--skip-chat-parsing")
        if not self._is_default("prefill_assistant", v):
            if not v.get("prefill_assistant", True):
                args.append("--no-prefill-assistant")
        if not self._is_default("reasoning", v):
            args.extend(["--reasoning", v["reasoning"]])
        if not self._is_default("reasoning_format", v):
            args.extend(["--reasoning-format", v["reasoning_format"]])
        if not self._is_default("reasoning_budget", v):
            args.extend(["--reasoning-budget", str(v["reasoning_budget"])])
        if not self._is_default("reasoning_budget_message", v):
            rbm = v.get("reasoning_budget_message", "")
            if rbm:
                args.extend(["--reasoning-budget-message", rbm])
        if not self._is_default("special", v):
            if v.get("special"):
                args.append("--special")
        if not self._is_default("reverse_prompt", v):
            rp2 = v.get("reverse_prompt", "")
            if rp2:
                args.extend(["-r", rp2])
        if not self._is_default("spm_infill", v):
            if v.get("spm_infill"):
                args.append("--spm-infill")
        return args

    def _build_advanced_args(self, v):
        args = []
        if not self._is_default("rope_scaling", v):
            rs = v.get("rope_scaling", "")
            if rs and rs != "none":
                args.extend(["--rope-scaling", rs])
        if not self._is_default("rope_scale", v):
            rsc = v.get("rope_scale", 0)
            if rsc > 0:
                args.extend(["--rope-scale", str(rsc)])
        if not self._is_default("rope_freq_base", v):
            rfb = v.get("rope_freq_base", 0)
            if rfb > 0:
                args.extend(["--rope-freq-base", str(rfb)])
        if not self._is_default("rope_freq_scale", v):
            rfs = v.get("rope_freq_scale", 0)
            if rfs > 0:
                args.extend(["--rope-freq-scale", str(rfs)])
        if not self._is_default("yarn_orig_ctx", v):
            yoc = v.get("yarn_orig_ctx", 0)
            if yoc > 0:
                args.extend(["--yarn-orig-ctx", str(yoc)])
        if not self._is_default("yarn_ext_factor", v):
            args.extend(["--yarn-ext-factor", f'{v["yarn_ext_factor"]:.2f}'])
        if not self._is_default("yarn_attn_factor", v):
            args.extend(["--yarn-attn-factor", f'{v["yarn_attn_factor"]:.2f}'])
        if not self._is_default("yarn_beta_slow", v):
            args.extend(["--yarn-beta-slow", f'{v["yarn_beta_slow"]:.2f}'])
        if not self._is_default("yarn_beta_fast", v):
            args.extend(["--yarn-beta-fast", f'{v["yarn_beta_fast"]:.2f}'])
        if not self._is_default("embedding", v):
            if v.get("embedding"):
                args.append("--embedding")
        if not self._is_default("rerank", v):
            if v.get("rerank"):
                args.append("--rerank")
        if not self._is_default("pooling", v):
            pl = v.get("pooling", "")
            if pl and pl != "none":
                args.extend(["--pooling", pl])
        if not self._is_default("verbose", v):
            if v.get("verbose"):
                args.append("--verbose")
        if not self._is_default("log_verbosity", v):
            args.extend(["--log-verbosity", str(v["log_verbosity"])])
        if not self._is_default("log_colors", v):
            args.extend(["--log-colors", v["log_colors"]])
        if not self._is_default("log_file", v):
            lf = v.get("log_file", "")
            if lf:
                args.extend(["--log-file", lf])
        if not self._is_default("offline", v):
            if v.get("offline"):
                args.append("--offline")
        if not self._is_default("log_prefix", v):
            if v.get("log_prefix"):
                args.append("--log-prefix")
        if not self._is_default("log_timestamps", v):
            if v.get("log_timestamps"):
                args.append("--log-timestamps")
        return args

    def _build_extra_args(self, v):
        extra = v.get("extra_args", "").strip()
        if extra:
            try:
                return shlex.split(extra, posix=(os.name != 'nt'))
            except ValueError:
                return extra.split()
        return []

    def _update_cmd_preview(self):
        if self._mode_switching:
            return
        self._save_current_to_params()
        changed = self.params != self._last_saved
        if changed and not self._pending_snapshot:
            self._pending_snapshot = True
            self._undo_debounce.start(800)
        args = self._build_args_from_params()
        if args:
            self.cmd_preview.setPlainText("llama-server " + " ".join(args))
        else:
            self.cmd_preview.setPlainText("llama-server")

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
            return

        model_path = v["model"]
        if not Path(model_path).exists():
            QMessageBox.warning(self, t("警告"), t("模型文件不存在:\n{model_path}", model_path=model_path))
            return

        port = v.get("port", 8080)
        if self._is_port_in_use(port):
            reply = QMessageBox.question(
                self, t("端口占用"),
                t("端口 {port} 可能已被占用，是否继续？", port=port),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        args = self._build_args_from_params()
        self.log_output.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {t('启动命令:')}")
        self.log_output.appendPlainText(f"  llama-server {' '.join(args)}")
        self.log_output.appendPlainText("")

        self.runner.start(args, work_dir=str(self.work_dir))
        host = v.get('host', '127.0.0.1')
        port = v.get('port', 8080)
        msg = t("🔄 正在启动服务: http://{host}:{port}", host=host, port=port)
        if host == "0.0.0.0":
            msg += t("  ⚠️ 监听所有网卡，局域网可访问")
        self.statusBar().showMessage(msg)

    def _stop_server(self):
        self.runner.stop()
        self.timer.stop()
        self.run_time_label.setText(t("⏱ 运行: 00:00"))

    def _copy_command(self):
        self._save_current_to_params()
        args = self._build_args_from_params()
        cmd = "llama-server " + " ".join(args)
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
                self._start_server()
                QTimer.singleShot(2000, lambda: webbrowser.open(url))
            return
        webbrowser.open(url)
        self.statusBar().showMessage(t("已在浏览器中打开: {url}", url=url), 3000)

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
            self.status_indicator.setText(t("⏸ 已停止"))
            self.status_indicator.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 13px;")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_webui.setEnabled(False)
            self._reset_runtime_state()
            self.statusBar().showMessage(t("⏹ 服务已停止"))
        elif state == "error":
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
        self.info_display.setHtml(self._get_empty_info_html())

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

    _MAX_LOG_LINES = 5000

    def _append_log(self, text):
        self.log_output.appendPlainText(text.rstrip())
        doc = self.log_output.document()
        if doc.blockCount() > self._MAX_LOG_LINES:
            cursor = self.log_output.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor,
                                doc.blockCount() - self._MAX_LOG_LINES)
            cursor.removeSelectedText()
        if self.chk_auto_scroll.isChecked():
            self.log_output.verticalScrollBar().setValue(
                self.log_output.verticalScrollBar().maximum()
            )
        for line in text.rstrip().split("\n"):
            self._parse_log_line(line.strip())

    def _parse_log_line(self, line):
        stripped = line.strip()
        lower = stripped.lower()
        info = self._runtime_info
        updated = False

        # Pre-compiled pattern matching
        for checks, exclude, regex, handler in _LOG_PATTERNS:
            if all(c in lower for c in checks) and not any(e in lower for e in exclude):
                m = regex.search(stripped)
                if m and handler(info, m):
                    updated = True

        # Special-case handlers
        if "system_info:" in lower or "system info:" in lower:
            updated = True
            if "openmp" in lower:
                info["openmp"] = t("是")
            if "repack" in lower:
                info["repack"] = t("是")

        if "kv_unified" in lower and "llama_context" in lower:
            updated = True
            if "true" in lower:
                info["kv_unified"] = t("已启用（多槽位共享缓存）")
            elif "false" in lower:
                info["kv_unified"] = t("已禁用（各槽位独立缓存）")

        if "flash_attn" in lower and "llama_context" in lower:
            updated = True
            if "enabled" in lower:
                info["flash_attn"] = t("已启用")
            elif "disabled" in lower:
                info["flash_attn"] = t("已禁用")
            elif "auto" in lower:
                info["flash_attn"] = t("自动（根据后端支持）")

        if "flash attention is enabled" in lower:
            info["flash_attn"] = t("已启用")
            updated = True

        if "has vision encoder" in lower:
            info["has_vision"] = True
            updated = True

        if "server is listening on" in lower:
            info["status"] = t("✅ 服务就绪")
            updated = True

        if "model loaded" in lower and "main:" in lower:
            info["status"] = t("🔄 模型加载完成")
            updated = True

        if updated:
            self._update_info_display()

    def _get_empty_info_html(self):
        return f"""
        <div style="color: #6c7086; font-size: 13px; padding: 30px; text-align: center;">
            <p style="font-size: 18px; margin-bottom: 12px;">🚀 {t("运行信息")}</p>
            <p>{t("启动服务后，此处将自动解析并显示：")}</p>
            <p style="margin-top: 8px;">{t("GPU 设备 · 模型详情 · 参数量 · 显存占用 · KV Cache · 视觉编码器 等关键信息")}</p>
        </div>
        """

    def _update_info_display(self):
        info = self._runtime_info

        categories = []

        items = []
        # Support multiple GPUs (new format) or single GPU (old format)
        gpu_indices = sorted(set(k[3:k.index('_')] for k in info if k.startswith('gpu') and k[3:4].isdigit() and '_' in k))
        if gpu_indices:
            for idx in gpu_indices:
                name = info.get(f"gpu{idx}_name", "")
                vram = info.get(f"gpu{idx}_vram", "")
                free = info.get(f"gpu{idx}_free", "")
                label = t("🖥️ GPU {idx} 设备", idx=idx)
                val = name
                if vram:
                    val += f" ({vram}"
                    if free:
                        val += t(", 空闲 {free}", free=free)
                    val += ")"
                items.append((label, val))
        elif info.get("gpu_name"):
            items.append((t("🖥️ GPU 设备"), info.get("gpu_name")))
        if info.get("gpu_compute_cap"):
            items.append((t("🔧 计算能力（CUDA 架构版本）"), info.get("gpu_compute_cap")))
        if not gpu_indices and info.get("gpu_vram"):
            items.append((t("📊 显卡显存（总可用显存）"), info.get("gpu_vram")))
        if info.get("cpu_name"):
            items.append((t("💻 CPU 设备"), info.get("cpu_name")))
        if info.get("cpu_ram"):
            items.append((t("📊 系统内存"), info.get("cpu_ram")))
        if items:
            categories.append((t("硬件信息"), items))

        items = []
        if info.get("address"):
            items.append((t("🌐 服务地址"), info.get("address")))
        if info.get("model_file"):
            items.append((t("📦 模型文件"), info.get("model_file")))
        if info.get("model_name"):
            items.append((t("🏷️ 模型名称"), info.get("model_name")))
        if info.get("quant_type"):
            items.append((t("📐 量化类型（量化格式）"), info.get("quant_type")))
        if info.get("file_size"):
            items.append((t("💾 文件大小（磁盘占用）"), info.get("file_size")))
        if info.get("gguf_version"):
            items.append((t("📄 GGUF 版本"), info.get("gguf_version")))
        if items:
            categories.append((t("模型信息"), items))

        items = []
        if info.get("model_params"):
            items.append((t("🔢 参数量（模型总参数）"), info.get("model_params")))
        if info.get("arch"):
            items.append((t("🏗️ 模型架构"), info.get("arch")))
        if info.get("n_layers"):
            items.append((t("📚 网络层数（Transformer 层数）"), info.get("n_layers")))
        if info.get("embed_dim"):
            items.append((t("📊 嵌入维度（向量维度大小）"), info.get("embed_dim")))
        if info.get("n_ff"):
            items.append((t("🔢 FFN 维度（前馈网络宽度）"), info.get("n_ff")))
        if info.get("vocab_size"):
            items.append((t("📚 词表大小（Token 数量）"), info.get("vocab_size")))
        if info.get("vocab_type"):
            items.append((t("🔤 词表类型（分词方式）"), info.get("vocab_type")))
        if info.get("tensor_types"):
            tensor_lines = []
            for qtype, qcount in sorted(info["tensor_types"].items()):
                tensor_lines.append(f"{qtype}: {qcount}")
            items.append((t("🎨 精度分布（各精度张量数量）"), " / ".join(tensor_lines)))
        if items:
            categories.append((t("模型架构"), items))

        items = []
        if info.get("train_ctx"):
            items.append((t("📏 训练上下文（模型最大支持长度）"), info.get("train_ctx")))
        if info.get("ctx_size_seq"):
            items.append((t("📐 运行上下文（实际使用长度）"), info.get("ctx_size_seq")))
        elif info.get("ctx_size"):
            items.append((t("📐 运行上下文（配置长度）"), info.get("ctx_size")))
        if info.get("n_batch"):
            items.append((t("📦 批处理大小（每次处理 Token 数）"), info.get("n_batch")))
        if info.get("n_ubatch"):
            items.append((t("📦 物理批处理（硬件实际批次）"), info.get("n_ubatch")))
        if info.get("sliding_window"):
            items.append((t("🪟 滑动窗口（SWA 窗口大小）"), info.get("sliding_window")))
        if info.get("freq_base"):
            items.append((t("📡 RoPE 频率（位置编码基频）"), info.get("freq_base")))
        if info.get("freq_base_runtime"):
            items.append((t("📡 运行 RoPE（实际使用基频）"), info.get("freq_base_runtime")))
        if info.get("n_slots"):
            items.append((t("🎰 槽位数（并发请求数）"), info.get("n_slots")))
        if info.get("thinking_mode"):
            items.append((t("🧠 推理模式（思维链/深度思考）"), info.get("thinking_mode")))
        if items:
            categories.append((t("运行参数"), items))

        items = []
        if info.get("gpu_offload"):
            items.append((t("🖥️ GPU 卸载（加载到 GPU 的层数）"), info.get("gpu_offload")))
        if info.get("model_vram"):
            items.append((t("📦 模型显存（模型权重占用）"), info.get("model_vram")))
        if info.get("cpu_buffer"):
            items.append((t("💻 CPU 缓冲（CPU 侧模型缓冲）"), info.get("cpu_buffer")))
        if info.get("projected_vram"):
            items.append((t("📊 预计显存（预估显存用量）"), info.get("projected_vram")))
        kv_total = info.get("kv_cache_total")
        if kv_total:
            if isinstance(kv_total, (int, float)):
                items.append((t("💾 KV Cache（键值缓存总量）"), f"{kv_total:.2f} MiB"))
            else:
                items.append((t("💾 KV Cache（键值缓存总量）"), kv_total))
        if info.get("compute_buffer"):
            items.append((t("🔲 计算缓冲（GPU 计算临时缓冲）"), info.get("compute_buffer")))
        if info.get("prompt_cache"):
            items.append((t("💬 Prompt 缓存（系统提示词缓存上限）"), info.get("prompt_cache")))
        if items:
            categories.append((t("显存占用"), items))

        items = []
        if info.get("flash_attn"):
            items.append((t("⚡ Flash Attention（高效注意力机制）"), info.get("flash_attn")))
        if info.get("kv_unified"):
            items.append((t("🔗 KV 统一（统一 KV 缓存）"), info.get("kv_unified")))
        if info.get("graph_nodes"):
            items.append((t("🔗 图节点数（计算图节点数量）"), info.get("graph_nodes")))
        if info.get("graph_splits"):
            items.append((t("✂️ 图分割数（CPU/GPU 切换次数）"), info.get("graph_splits")))
        if items:
            categories.append((t("性能优化"), items))

        items = []
        if info.get("n_threads") or info.get("n_threads_batch"):
            threads_str = t("推理={n} / 批处理={nb} / 总计={total}", n=info.get('n_threads', '?'), nb=info.get('n_threads_batch', '?'), total=info.get('total_threads', '?'))
            items.append((t("🔧 线程配置（CPU 线程数）"), threads_str))
        if info.get("threads_http"):
            items.append((t("🌐 HTTP 线程数"), info.get("threads_http")))
        if info.get("openmp"):
            items.append((t("🔗 OpenMP（并行计算加速）"), info.get("openmp")))
        if info.get("repack"):
            items.append((t("📦 Repack（权重重打包优化）"), info.get("repack")))
        if info.get("speculative_decoding"):
            items.append((t("🚀 推测解码（Speculative Decoding）"), info.get("speculative_decoding")))
        if items:
            categories.append((t("系统配置"), items))

        if info.get("has_vision") or info.get("vision_min_tokens"):
            items = []
            if info.get("has_vision"):
                items.append((t("👁️ 视觉编码器（多模态图像理解）"), t("已加载")))
            if info.get("mmproj_file"):
                items.append((t("📦 投影文件（视觉投影模型）"), info.get("mmproj_file")))
            if info.get("vision_model_size"):
                items.append((t("📊 视觉模型大小"), info.get("vision_model_size")))
            if info.get("vision_image_size"):
                items.append((t("🖼️ 图像尺寸（输入图像分辨率）"), info.get("vision_image_size")))
            if info.get("vision_min_tokens"):
                items.append((t("🔢 最小图像 Token 数"), info.get("vision_min_tokens")))
            if items:
                categories.append((t("视觉编码器"), items))

        def make_rows(items):
            rows = []
            for label, value in items:
                safe_value = html_mod.escape(str(value))
                safe_label = html_mod.escape(str(label))
                color = "#a6e3a1" if "✅" in str(value) else ("#7aa2f7" if value != "—" else "#6c7086")
                rows.append(f'<tr><td style="color: #7aa2f7; font-weight: bold; padding: 3px 12px 3px 0; white-space: nowrap; vertical-align: top; width: 1%;">{safe_label}</td><td style="color: {color}; padding: 3px 0; word-break: break-all;">{safe_value}</td></tr>')
            return ''.join(rows)

        def make_section_html(title, items):
            section = f'<tr><td colspan="2" style="color: #c9cbcf; font-weight: bold; font-size: 13px; padding: 8px 0 4px 0; border-bottom: 1px solid #45475a;">{html_mod.escape(title)}</td></tr>'
            section += make_rows(items)
            return section

        all_sections = []
        for title, items in categories:
            all_sections.append(make_section_html(title, items))

        html = f"""
        <table style="border-collapse: collapse; width: 100%; font-family: Consolas, 'Courier New', monospace; font-size: 12px;">
            {''.join(all_sections)}
        </table>
        """
        self.info_display.setHtml(html)

    def _clear_log(self):
        self.log_output.clear()

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, t("导出日志"), "", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_output.toPlainText())

    def _update_timer(self):
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            self.run_time_label.setText(t("⏱ 运行: {mins}:{secs}", mins=f"{mins:02d}", secs=f"{secs:02d}"))

    def _refresh_presets(self):
        self.preset_combo.clear()
        presets = self.config.list_presets()
        for p in presets:
            self.preset_combo.addItem(p["name"])

    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        if self.config.load_preset(name):
            self._set_current_values(self.config.current)
            self._update_cmd_preview()
            self.statusBar().showMessage(t("已加载预设: {name}", name=name), 2000)

    def _save_preset(self):
        current_name = self.preset_combo.currentText()
        name, ok = QInputDialog.getText(self, t("保存预设"), t("预设名称:"), text=current_name)
        if not ok or not name:
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
        values = self._get_current_values()
        for k, val in values.items():
            self.config.set(k, val)
        self.config.save_preset(name)
        self._refresh_presets()
        idx = self.preset_combo.findText(name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
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
            self._refresh_presets()
            self.statusBar().showMessage(t("已删除预设: {name}", name=name), 2000)

    def _import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, t("导入预设"), "", "JSON Files (*.json)")
        if path:
            self.config.import_preset(path)
            self._refresh_presets()
            self.statusBar().showMessage(t("预设已导入"), 2000)

    def _export_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("导出预设"), f"{name}.json", "JSON Files (*.json)")
        if path:
            self.config.export_preset(name, path)
            self.statusBar().showMessage(t("预设已导出"), 2000)

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

    def closeEvent(self, event):
        if self.runner.is_running:
            self.runner.stop(blocking=True)
        event.accept()

    def _create_menu_bar(self):
        from PyQt6.QtGui import QActionGroup
        menubar = self.menuBar()

        self.file_menu = menubar.addMenu(t("文件"))

        self._scan_path_action = QAction(self._create_text_icon("P", QColor("#f39c12")), t("设置扫描路径..."), self)
        self._scan_path_action.setShortcut("Ctrl+P")
        self._scan_path_action.triggered.connect(self._set_scan_path)
        self.file_menu.addAction(self._scan_path_action)

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
        msg.setText(
            "<b>🦙 llama.cpp Launcher</b><br><br>"
            + t("一个功能丰富的图形化 llama-server 启动器，帮助您轻松管理和运行 GGUF 格式的大语言模型。<br><br>")
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
            + t("🌐 <b>国际化</b> — 支持中文/英文界面实时切换，无需重启<br><br>")
            + t("<b>技术栈：</b> PyQt6 · Python · llama.cpp<br>")
            + t("默认参数自动从 llama-server --help 动态获取，确保与您的版本完全匹配。")
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _create_model_info_group(self):
        group = QGroupBox(t("📊 模型信息"))
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 20, 6, 6)
        layout.setSpacing(4)

        self.model_info_labels = {}
        self._model_info_label_widgets = {}
        info_items = [
            ("model_size", "📦 模型大小"),
            ("mmproj_size", "🖼️ 多模态投影"),
            ("total_size", "📁 权重总大小"),
            ("model_params", "🔢 模型参数量"),
            ("quant_type", "📐 量化类型"),
        ]
        for key, label_text in info_items:
            row = QHBoxLayout()
            lbl = QLabel(t(label_text))
            self._model_info_label_widgets[key] = (lbl, label_text)
            lbl.setStyleSheet("color: #7aa2f7; font-weight: bold; font-size: 12px; min-width: 100px;")
            row.addWidget(lbl)
            val = QLabel("—")
            val.setStyleSheet("color: #a9b1d6; font-size: 12px;")
            val.setWordWrap(True)
            row.addWidget(val)
            row.addStretch()
            layout.addLayout(row)
            self.model_info_labels[key] = val

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

    def _check_server_version(self):
        self._version_worker = _VersionCheckWorker()
        self._version_worker.result_ready.connect(self._on_version_result)
        self._version_worker.failed.connect(self._on_version_failed)
        self._version_worker.start()

    def _on_version_result(self, ver_num, commit, version_line):
        if ver_num:
            self.version_label.setText(f"🔖 llama.cpp v{ver_num} ({commit})")
            self.version_label.setStyleSheet("color: #16a34a; font-size: 12px; font-weight: bold;")
            self.version_label.setToolTip(t("llama.cpp 版本: {ver}\n提交: {commit}", ver=ver_num, commit=commit))
            self._validate_params()
        else:
            self.version_label.setText(f"🔖 {version_line}")
            self.version_label.setStyleSheet("color: #d97706; font-size: 12px;")

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
        from core.defaults import get_default_params, _FALLBACK_DEFAULTS
        try:
            current_defaults = get_default_params()
            missing = []
            changed = []
            for key, fallback_val in _FALLBACK_DEFAULTS.items():
                if key in ("model", "mmproj", "lora", "lora_scaled", "control_vector", "control_vector_scaled", "control_vector_layer_range", "alias", "tags", "extra_args", "tools", "grammar", "json_schema", "reverse_prompt", "api_key", "api_key_file", "device", "tensor_split", "chat_template", "chat_template_file", "chat_template_kwargs", "reasoning_budget_message", "log_file", "ssl_key_file", "ssl_cert_file", "webui_config_file", "webui_config", "path", "api_prefix", "samplers", "sampler_seq", "logit_bias", "grammar_file", "json_schema_file", "slot_save_path", "media_path", "draft_model", "device_draft"):
                    continue
                if key not in current_defaults:
                    missing.append(key)
                elif current_defaults[key] != fallback_val:
                    changed.append((key, fallback_val, current_defaults[key]))

            if not missing and not changed:
                self.version_label.setToolTip(self.version_label.toolTip() + "\n\n" + t("✅ 所有参数与当前版本匹配"))
            else:
                tip = self.version_label.toolTip() + "\n\n" + t("⚠️ 参数差异提示:\n")
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
        except Exception:
            pass

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
        # Model info labels
        for key, (lbl, label_text) in self._model_info_label_widgets.items():
            lbl.setText(t(label_text))

        # Right panel
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
        self._refresh_action.setText(t("刷新模型列表"))
        self._exit_action.setText(t("退出"))
        self.lang_menu.setTitle(t("语言"))
        self.help_menu.setTitle(t("帮助"))
        self._about_action.setText(t("关于"))

        # Status bar
        if not self.runner.is_running:
            self.statusBar().showMessage(t("就绪"))

        # Info display
        if self._runtime_info:
            self._update_info_display()
        else:
            self.info_display.setHtml(self._get_empty_info_html())

        # Child panels
        self.basic_panel.retranslate_ui()
        self.advanced_panel.retranslate_ui()

    def _create_status_bar(self):
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage(t("就绪"))

    @staticmethod
    def _get_stylesheet():
        return """
            QMainWindow {
                background-color: #f0f2f5;
            }
            QWidget {
                background-color: #f0f2f5;
                color: #1a1a2e;
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
                background: #c8d8c8;
                color: #8a9a8a;
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
                background: #d8c8c8;
                color: #9a8a8a;
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
                background: #c8d0d8;
                color: #8a9098;
                border: 1px solid #b0b8c0;
            }
            QPlainTextEdit {
                background-color: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
                border-radius: 8px;
                padding: 8px;
                selection-background-color: #3b82f6;
            }
            QComboBox, QDoubleSpinBox, QLineEdit, QTextEdit {
                background: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
                border-radius: 6px;
                padding: 4px 8px;
                selection-background-color: #3b82f6;
            }
            QSpinBox, QDoubleSpinBox {
                background: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
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
                border-top: 6px solid #333;
                margin-right: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
                border-radius: 6px;
                selection-background-color: #3b82f6;
                padding: 4px;
            }
            QPushButton {
                background: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #e8ecf0;
                border-color: #3b82f6;
            }
            QPushButton:pressed {
                background: #d8dce0;
            }
            QCheckBox {
                color: #1a1a2e;
                spacing: 6px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #b0b8c0;
                border-radius: 4px;
                background-color: #ffffff;
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
                border: 1px solid #d0d4dc;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 24px;
                color: #1a1a2e;
                background-color: #ffffff;
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
                background-color: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
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
                background-color: #e8ecf0;
            }
            QTabWidget::pane {
                border: 1px solid #d0d4dc;
                border-radius: 8px;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background: #e8ecf0;
                color: #666;
                padding: 8px 16px;
                border: 1px solid #d0d4dc;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #2563eb;
                border-bottom: 2px solid #2563eb;
            }
            QTabBar::tab:hover {
                background: #f0f2f5;
                color: #1a1a2e;
            }
            QSplitter::handle {
                background-color: #d0d4dc;
                width: 3px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #3b82f6;
            }
            QMenuBar {
                background-color: #ffffff;
                color: #1a1a2e;
                border-bottom: 1px solid #d0d4dc;
                padding: 2px;
            }
            QMenuBar::item:selected {
                background-color: #e8ecf0;
                border-radius: 4px;
            }
            QMenu {
                background-color: #ffffff;
                color: #1a1a2e;
                border: 1px solid #d0d4dc;
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
                background: #d0d4dc;
                margin: 4px 8px;
            }
            QStatusBar {
                background-color: #ffffff;
                color: #666;
                border-top: 1px solid #d0d4dc;
                font-size: 12px;
            }
            QLabel {
                color: #1a1a2e;
                font-size: 13px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #e8ecf0;
                border: 1px solid #d0d4dc;
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
                border: 2px solid #ffffff;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QScrollBar:vertical {
                background: #f0f2f5;
                width: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #b0b8c0;
                border-radius: 6px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #8a9098;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #f0f2f5;
                height: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: #b0b8c0;
                border-radius: 6px;
                min-width: 24px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #8a9098;
            }
        """

