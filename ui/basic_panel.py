import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QComboBox, QSpinBox, QSlider, QLineEdit,
    QCheckBox, QPushButton, QLabel, QFileDialog
)
from PyQt6.QtCore import Qt
from core.i18n import t
from core.constants import DEFAULT_HOST, DEFAULT_PORT, CONTEXT_SIZE_PRESETS, MAIN_GPU_MAX
from ui.advanced_panel import SPEC_TYPE_ITEMS
from ui.param_help import make_help_button

logger = logging.getLogger(__name__)


class BasicPanel(QWidget):

    def __init__(self, defaults=None, parent=None):
        super().__init__(parent)
        self._defaults = defaults or {}
        self._help_btns = []
        self._setup_ui()
        self._apply_defaults()

    def _add_help(self, layout, key):
        """Append a small '?' help button to a row layout (no-op if the
        parameter has no explanation yet)."""
        from core.params_help import has_help
        if not has_help(key):
            return
        btn = make_help_button(key, lambda: self._defaults)
        self._help_btns.append(btn)
        layout.addWidget(btn)

    def _apply_defaults(self):
        d = self._defaults
        if not d:
            return
        # Apply the full set of parsed defaults (from llama-server --help) to every
        # widget, so the UI reflects the live server's defaults rather than
        # construction-time hardcoded values.
        self.set_values(dict(d))

    def set_defaults(self, defaults):
        """Update the defaults baseline (live-parsed defaults arriving after startup, plan A10)."""
        self._defaults = dict(defaults)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(self._create_model_group())
        layout.addWidget(self._create_sampling_group())
        layout.addWidget(self._create_server_group())
        layout.addWidget(self._create_quick_toggles_group())
        layout.addStretch()

    def _create_model_group(self):
        self._model_group = QGroupBox(t("🧠 模型设置"))
        layout = QVBoxLayout(self._model_group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        self._lbl_model = QLabel(t("模型:"))
        self._lbl_model.setFixedWidth(56)
        row1.addWidget(self._lbl_model)
        self._add_help(row1, "model")
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        row1.addWidget(self.model_combo)
        # C4: previously a hardcoded English-only string, now goes through t()
        self._btn_browse_model = QPushButton(t("..."))
        self._btn_browse_model.setFixedWidth(36)
        self._btn_browse_model.clicked.connect(self._browse_model)
        row1.addWidget(self._btn_browse_model)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._lbl_mmproj = QLabel(t("mmproj:"))
        self._lbl_mmproj.setFixedWidth(56)
        row2.addWidget(self._lbl_mmproj)
        self._add_help(row2, "mmproj")
        self.mmproj_combo = QComboBox()
        self.mmproj_combo.setEditable(True)
        row2.addWidget(self.mmproj_combo)
        self._btn_browse_mmproj = QPushButton(t("..."))
        self._btn_browse_mmproj.setFixedWidth(36)
        self._btn_browse_mmproj.clicked.connect(self._browse_mmproj)
        row2.addWidget(self._btn_browse_mmproj)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self._lbl_ngl = QLabel(t("GPU层数:"))
        row3.addWidget(self._lbl_ngl)
        self._add_help(row3, "n_gpu_layers")
        self.ngl_combo = QComboBox()
        self.ngl_combo.addItems(["auto", "all"])
        self.ngl_combo.setEditable(True)
        self.ngl_combo.setFixedWidth(80)
        self.ngl_combo.setToolTip(t("auto=自动检测, all=全部卸载到GPU, 或输入具体层数"))
        row3.addWidget(self.ngl_combo)
        self.ngl_spin = QSpinBox()
        self.ngl_spin.setRange(0, 999)
        self.ngl_spin.setValue(0)
        self.ngl_spin.setFixedWidth(60)
        self.ngl_spin.setToolTip(t("手动指定GPU卸载层数"))
        self.ngl_spin.valueChanged.connect(lambda v: self.ngl_combo.setEditText(str(v)))
        row3.addWidget(self.ngl_spin)
        row3.addSpacing(12)
        self._lbl_ctx = QLabel(t("上下文:"))
        row3.addWidget(self._lbl_ctx)
        self._add_help(row3, "ctx_size")
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(0, 999999)
        self.ctx_spin.setValue(0)
        self.ctx_spin.setFixedWidth(90)
        self.ctx_spin.setToolTip(t("0=使用模型默认"))
        row3.addWidget(self.ctx_spin)
        self.ctx_default_btn = QPushButton(t("默认"))
        self.ctx_default_btn.setMinimumWidth(48)
        self.ctx_default_btn.setToolTip(t("使用模型默认上下文长度"))
        self.ctx_default_btn.clicked.connect(lambda: self.ctx_spin.setValue(0))
        row3.addWidget(self.ctx_default_btn)
        for val in CONTEXT_SIZE_PRESETS:
            btn = QPushButton(str(val))
            btn.setMinimumWidth(56)
            btn.setToolTip(t("设置上下文长度为 {val}", val=val))
            btn.clicked.connect(lambda checked, v=val: self.ctx_spin.setValue(v))
            row3.addWidget(btn)
        row3.addStretch()
        layout.addLayout(row3)
        # E8: detected GPU devices (from the `--list-devices` probe)
        self.gpu_info_label = QLabel("")
        self.gpu_info_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.gpu_info_label.setVisible(False)
        layout.addWidget(self.gpu_info_label)
        return self._model_group

    def _create_sampling_group(self):
        self._sampling_group = QGroupBox(t("🎲 采样参数"))
        layout = QVBoxLayout(self._sampling_group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        self._lbl_temp = QLabel(t("温度:"))
        row1.addWidget(self._lbl_temp)
        self._add_help(row1, "temp")
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 200)
        self.temp_slider.setValue(80)
        self.temp_label = QLabel("0.80")
        self.temp_label.setFixedWidth(40)
        self.temp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.temp_slider.valueChanged.connect(self._on_temp_changed)
        row1.addWidget(self.temp_slider)
        row1.addWidget(self.temp_label)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._lbl_top_p = QLabel(t("Top-P:"))
        row2.addWidget(self._lbl_top_p)
        self._add_help(row2, "top_p")
        self.top_p_slider = QSlider(Qt.Orientation.Horizontal)
        self.top_p_slider.setRange(0, 100)
        self.top_p_slider.setValue(95)
        self.top_p_label = QLabel("0.95")
        self.top_p_label.setFixedWidth(40)
        self.top_p_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.top_p_slider.valueChanged.connect(self._on_top_p_changed)
        row2.addWidget(self.top_p_slider)
        row2.addWidget(self.top_p_label)
        row2.addSpacing(12)
        self._lbl_top_k = QLabel(t("Top-K:"))
        row2.addWidget(self._lbl_top_k)
        self._add_help(row2, "top_k")
        self.top_k_spin = QSpinBox()
        self.top_k_spin.setRange(0, 200)
        self.top_k_spin.setValue(40)
        self.top_k_spin.setFixedWidth(60)
        row2.addWidget(self.top_k_spin)
        row2.addSpacing(12)
        self._lbl_min_p = QLabel(t("Min-P:"))
        row2.addWidget(self._lbl_min_p)
        self._add_help(row2, "min_p")
        self.min_p_slider = QSlider(Qt.Orientation.Horizontal)
        self.min_p_slider.setRange(0, 100)
        self.min_p_slider.setValue(5)
        self.min_p_label = QLabel("0.05")
        self.min_p_label.setFixedWidth(40)
        self.min_p_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.min_p_slider.valueChanged.connect(self._on_min_p_changed)
        row2.addWidget(self.min_p_slider)
        row2.addWidget(self.min_p_label)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self._lbl_repeat_penalty = QLabel(t("重复惩罚:"))
        row3.addWidget(self._lbl_repeat_penalty)
        self._add_help(row3, "repeat_penalty")
        self.repeat_penalty_slider = QSlider(Qt.Orientation.Horizontal)
        self.repeat_penalty_slider.setRange(0, 200)
        self.repeat_penalty_slider.setValue(100)
        self.repeat_penalty_label = QLabel("1.00")
        self.repeat_penalty_label.setFixedWidth(40)
        self.repeat_penalty_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.repeat_penalty_slider.valueChanged.connect(self._on_repeat_penalty_changed)
        row3.addWidget(self.repeat_penalty_slider)
        row3.addWidget(self.repeat_penalty_label)
        row3.addStretch()
        layout.addLayout(row3)
        return self._sampling_group

    def _create_server_group(self):
        self._server_group = QGroupBox(t("🌐 网络服务"))
        layout = QHBoxLayout(self._server_group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)
        self._lbl_host = QLabel(t("地址:"))
        layout.addWidget(self._lbl_host)
        self._add_help(layout, "host")
        self.host_edit = QLineEdit(DEFAULT_HOST)
        self.host_edit.setFixedWidth(110)
        layout.addWidget(self.host_edit)
        layout.addWidget(QLabel(":"))
        self._add_help(layout, "port")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_PORT)
        self.port_spin.setFixedWidth(70)
        layout.addWidget(self.port_spin)
        layout.addSpacing(12)
        self._lbl_parallel = QLabel(t("并行:"))
        layout.addWidget(self._lbl_parallel)
        self._add_help(layout, "parallel")
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(-1, 64)
        self.parallel_spin.setValue(1)
        self.parallel_spin.setFixedWidth(60)
        layout.addWidget(self.parallel_spin)
        layout.addSpacing(12)
        self.chk_webui = QCheckBox(t("WebUI"))
        self.chk_webui.setChecked(True)
        layout.addWidget(self.chk_webui)
        self._add_help(layout, "webui")
        layout.addSpacing(12)
        self.chk_verbose = QCheckBox(t("Verbose"))
        self.chk_verbose.setChecked(False)
        layout.addWidget(self.chk_verbose)
        self._add_help(layout, "verbose")
        layout.addStretch()
        return self._server_group

    def _create_quick_toggles_group(self):
        self._toggles_group = QGroupBox(t("⚡ 快捷开关"))
        layout = QHBoxLayout(self._toggles_group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)
        self.flash_attn_combo = QComboBox()
        self.flash_attn_combo.addItems(["auto", "on", "off"])
        self.flash_attn_combo.setCurrentText("auto")
        self.flash_attn_combo.setFixedWidth(78)
        self._lbl_flash_attn = QLabel(t("FlashAttn:"))
        layout.addWidget(self._lbl_flash_attn)
        self._add_help(layout, "flash_attn")
        layout.addWidget(self.flash_attn_combo)
        layout.addSpacing(12)
        self.reasoning_combo = QComboBox()
        self.reasoning_combo.addItems(["auto", "on", "off"])
        self.reasoning_combo.setCurrentText("auto")
        self.reasoning_combo.setFixedWidth(78)
        self._lbl_reasoning = QLabel(t("推理:"))
        layout.addWidget(self._lbl_reasoning)
        self._add_help(layout, "reasoning")
        layout.addWidget(self.reasoning_combo)
        layout.addSpacing(12)
        self.split_mode_combo = QComboBox()
        self.split_mode_combo.addItems(["none", "layer", "row", "tensor"])
        self.split_mode_combo.setCurrentText("layer")
        self.split_mode_combo.setFixedWidth(78)
        self._lbl_split_mode = QLabel(t("分割模式:"))
        layout.addWidget(self._lbl_split_mode)
        self._add_help(layout, "split_mode")
        layout.addWidget(self.split_mode_combo)
        layout.addSpacing(12)
        self.spec_type_combo = QComboBox()
        self.spec_type_combo.addItems(SPEC_TYPE_ITEMS)
        self.spec_type_combo.setCurrentText("none")
        self.spec_type_combo.setFixedWidth(140)
        self._lbl_spec_type = QLabel(t("投机类型:"))
        layout.addWidget(self._lbl_spec_type)
        self._add_help(layout, "spec_type")
        layout.addWidget(self.spec_type_combo)
        layout.addSpacing(12)
        self.draft_max_spin = QSpinBox()
        self.draft_max_spin.setRange(1, 256)
        self.draft_max_spin.setValue(3)
        self.draft_max_spin.setFixedWidth(60)
        self._lbl_draft_max = QLabel(t("草稿Token:"))
        layout.addWidget(self._lbl_draft_max)
        self._add_help(layout, "draft_max")
        layout.addWidget(self.draft_max_spin)
        layout.addStretch()
        return self._toggles_group

    def _browse_gguf(self, title, combo):
        path, _ = QFileDialog.getOpenFileName(self, title, "", "GGUF Files (*.gguf)")
        if path:
            idx = combo.findText(path)
            if idx == -1:
                combo.addItem(path)
                combo.setCurrentText(path)
            else:
                combo.setCurrentIndex(idx)

    def _browse_model(self):
        self._browse_gguf(t("选择模型"), self.model_combo)

    def _browse_mmproj(self):
        self._browse_gguf(t("选择MMProj"), self.mmproj_combo)

    def _on_temp_changed(self, value):
        self.temp_label.setText(f"{value / 100:.2f}")

    def _on_top_p_changed(self, value):
        self.top_p_label.setText(f"{value / 100:.2f}")

    def _on_min_p_changed(self, value):
        self.min_p_label.setText(f"{value / 100:.2f}")

    def _on_repeat_penalty_changed(self, value):
        self.repeat_penalty_label.setText(f"{value / 100:.2f}")

    def set_gpu_info(self, devices):
        """E8: render detected GPU devices (or CPU-only) next to the ngl control."""
        self._gpu_devices = list(devices or [])
        self._render_gpu_info()

    def _render_gpu_info(self):
        label = getattr(self, "gpu_info_label", None)
        if label is None:
            return
        devs = getattr(self, "_gpu_devices", None)
        if devs is None:
            return  # probe not finished yet
        if not devs:
            label.setText(t("仅 CPU（未检测到 GPU 设备）"))
            label.setToolTip(t("未检测到 GPU 设备"))
        else:
            parts = [f"{d['name']} ({round(d['total_mib'] / 1024)}GB)" for d in devs]
            label.setText(t("检测到 {n}× GPU: {names}", n=len(devs), names=" + ".join(parts)))
            label.setToolTip("\n".join(
                f"{d['index']}: {d['name']} (total {d['total_mib']:,} MiB, "
                f"free {d['free_mib']:,} MiB)" for d in devs))
        label.setVisible(True)

    def get_values(self):
        return {
            "model": self.model_combo.currentText(),
            "mmproj": self.mmproj_combo.currentText(),
            "n_gpu_layers": self.ngl_combo.currentText(),
            "ctx_size": self.ctx_spin.value(),
            "temp": self.temp_slider.value() / 100.0,
            "top_p": self.top_p_slider.value() / 100.0,
            "top_k": self.top_k_spin.value(),
            "min_p": self.min_p_slider.value() / 100.0,
            "repeat_penalty": self.repeat_penalty_slider.value() / 100.0,
            "host": self.host_edit.text(),
            "port": self.port_spin.value(),
            "parallel": self.parallel_spin.value(),
            "flash_attn": self.flash_attn_combo.currentText(),
            "webui": self.chk_webui.isChecked(),
            "verbose": self.chk_verbose.isChecked(),
            "reasoning": self.reasoning_combo.currentText(),
            "split_mode": self.split_mode_combo.currentText(),
            "spec_type": self.spec_type_combo.currentText(),
            "draft_max": self.draft_max_spin.value(),
        }

    def set_values(self, values):
        values = dict(values)
        try:
            self._set_values_impl(values)
            return
        except (TypeError, ValueError):
            # 预设值类型损坏：按 key 逐个应用，跳过问题 key，避免中断整个预设加载
            for key in values:
                try:
                    self._set_values_impl({key: values[key]})
                except (TypeError, ValueError):
                    logger.warning("忽略无效的预设值: %s=%r", key, values[key])

    def _set_values_impl(self, values):
        values = dict(values)
        if "model" in values:
            val = values["model"]
            idx = self.model_combo.findText(val)
            if idx == -1 and val:
                self.model_combo.addItem(val)
            self.model_combo.setCurrentText(val)
        if "mmproj" in values:
            val = values["mmproj"]
            idx = self.mmproj_combo.findText(val)
            if idx == -1 and val:
                self.mmproj_combo.addItem(val)
            self.mmproj_combo.setCurrentText(val)
        if "n_gpu_layers" in values:
            self.ngl_spin.blockSignals(True)
            self.ngl_combo.setCurrentText(str(values["n_gpu_layers"]))
            try:
                self.ngl_spin.setValue(int(values["n_gpu_layers"]))
            except (ValueError, TypeError):
                self.ngl_spin.setValue(0)
            self.ngl_spin.blockSignals(False)
        if "ctx_size" in values:
            self.ctx_spin.setValue(values["ctx_size"])
        if "temp" in values:
            v = values["temp"]
            self.temp_slider.setValue(int(round(v * 100)) if v <= 2.0 else int(v))
        if "top_p" in values:
            v = values["top_p"]
            self.top_p_slider.setValue(int(round(v * 100)) if v <= 1.0 else int(v))
        if "top_k" in values:
            self.top_k_spin.setValue(values["top_k"])
        if "min_p" in values:
            v = values["min_p"]
            self.min_p_slider.setValue(int(round(v * 100)) if v <= 1.0 else int(v))
        if "repeat_penalty" in values:
            v = values["repeat_penalty"]
            self.repeat_penalty_slider.setValue(int(round(v * 100)) if v <= 2.0 else int(v))
        if "host" in values:
            self.host_edit.setText(values["host"])
        if "port" in values:
            self.port_spin.setValue(values["port"])
        if "parallel" in values:
            self.parallel_spin.setValue(values["parallel"])
        if "flash_attn" in values:
            self.flash_attn_combo.setCurrentText(str(values["flash_attn"]))
        if "webui" in values:
            self.chk_webui.setChecked(values["webui"])
        if "verbose" in values:
            self.chk_verbose.setChecked(values["verbose"])
        if "reasoning" in values:
            self.reasoning_combo.setCurrentText(str(values["reasoning"]))
        if "split_mode" in values:
            self.split_mode_combo.setCurrentText(str(values["split_mode"]))
        if "spec_type" in values:
            self.spec_type_combo.setCurrentText(str(values["spec_type"]))
        if "draft_max" in values:
            self.draft_max_spin.setValue(values["draft_max"])

    def retranslate_ui(self):
        self._model_group.setTitle(t("🧠 模型设置"))
        self._lbl_model.setText(t("模型:"))
        self._lbl_ngl.setText(t("GPU层数:"))
        self.ngl_combo.setToolTip(t("auto=自动检测, all=全部卸载到GPU, 或输入具体层数"))
        self.ngl_spin.setToolTip(t("手动指定GPU卸载层数"))
        self._lbl_ctx.setText(t("上下文:"))
        self.ctx_spin.setToolTip(t("0=使用模型默认"))
        self.ctx_default_btn.setText(t("默认"))
        self._sampling_group.setTitle(t("🎲 采样参数"))
        self._lbl_temp.setText(t("温度:"))
        self._lbl_repeat_penalty.setText(t("重复惩罚:"))
        self._server_group.setTitle(t("🌐 网络服务"))
        self._lbl_host.setText(t("地址:"))
        self._lbl_parallel.setText(t("并行:"))
        self._toggles_group.setTitle(t("⚡ 快捷开关"))
        self._lbl_reasoning.setText(t("推理:"))
        self._lbl_flash_attn.setText(t("FlashAttn:"))
        self.chk_webui.setText(t("WebUI"))
        self.chk_verbose.setText(t("Verbose"))
        self._lbl_mmproj.setText(t("mmproj:"))
        self._lbl_top_p.setText(t("Top-P:"))
        self._lbl_top_k.setText(t("Top-K:"))
        self._lbl_min_p.setText(t("Min-P:"))
        self._btn_browse_model.setText(t("..."))
        self._btn_browse_mmproj.setText(t("..."))
        self._lbl_split_mode.setText(t("分割模式:"))
        self._lbl_spec_type.setText(t("投机类型:"))
        self._lbl_draft_max.setText(t("草稿Token:"))
        for btn in self._help_btns:
            btn.setToolTip(t("查看参数说明"))
        self._render_gpu_info()
