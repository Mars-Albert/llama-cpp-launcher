import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QDialog,
    QComboBox, QSpinBox, QSlider, QLineEdit,
    QCheckBox, QPushButton, QLabel, QFileDialog
)
from PyQt6.QtCore import Qt
from core.i18n import t
from core.constants import DEFAULT_HOST, DEFAULT_PORT, CONTEXT_SIZE_PRESETS
from core.params_schema import PARAMS_BY_KEY
from ui.param_help import make_help_button
from ui.quick_params import (
    QUICK_DEFAULT_KEYS, build_quick_widget, quick_label_text,
    read_quick, sanitize_quick_keys, write_quick,
)

logger = logging.getLogger(__name__)


class BasicPanel(QWidget):
    """Basic mode panel. Simplified UI with commonly used parameters only.

    The ⚡ quick-toggles group is user-configurable (plan E10): which
    parameters it shows is chosen from the 设置 menu (自定义快捷开关…)
    and persisted as an ordered key list (ui.quick_params in
    settings.json).
    """

    def __init__(self, defaults=None, parent=None):
        super().__init__(parent)
        self._defaults = defaults or {}
        self._help_btns = []
        self._quick_keys = list(QUICK_DEFAULT_KEYS)
        self._quick_items = []
        self._quick_boxes = []
        self._quick_help_btns = []
        self._setup_ui()
        self._apply_defaults()

    def _add_help(self, layout, key, registry=None):
        """Append a small '?' help button to a row layout (no-op if the
        parameter has no explanation yet). Returns the button or None."""
        from core.params_help import has_help
        if not has_help(key):
            return None
        btn = make_help_button(key, lambda: self._defaults)
        (registry if registry is not None else self._help_btns).append(btn)
        layout.addWidget(btn)
        return btn

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
        # E10: the group content is schema-driven and user-configurable
        # (customize from the 设置 menu → QuickParamsDialog). Slots wrap in
        # an adaptive-column QGridLayout (a Python flow-layout subclass
        # would be the natural fit, but the pinned PyQt6 6.11 build crashes
        # the process in any Python QLayout subclass — see quick_params.py).
        self._toggles_group = QGroupBox(t("⚡ 快捷开关"))
        outer = QVBoxLayout(self._toggles_group)
        outer.setContentsMargins(6, 2, 6, 6)
        outer.setSpacing(2)
        self._quick_grid = QGridLayout()
        self._quick_grid.setContentsMargins(4, 2, 4, 4)
        self._quick_grid.setHorizontalSpacing(12)
        self._quick_grid.setVerticalSpacing(8)
        outer.addLayout(self._quick_grid)
        self._rebuild_quick_toggles()
        return self._toggles_group

    # Typical quick-toggle slot width (label + control + help), used to
    # estimate how many slots fit per row.
    _QUICK_CELL_WIDTH = 215

    def _quick_cols(self):
        n = max(1, len(self._quick_keys))
        w = self._toggles_group.width()
        return max(1, min(n, int((w - 24) / self._QUICK_CELL_WIDTH)))

    def _arrange_quick_toggles(self):
        """Re-place the slot boxes in the grid for the current width. Boxes
        keep their parent (the group), so this is a cheap take/re-add."""
        grid = self._quick_grid
        cols = self._quick_cols()
        while grid.count():
            grid.takeAt(0)
        for i, box in enumerate(self._quick_boxes):
            grid.addWidget(box, i // cols, i % cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._quick_boxes:
            self._arrange_quick_toggles()

    def _rebuild_quick_toggles(self):
        """E10: (re)build the quick-toggle slots from self._quick_keys."""
        grid = self._quick_grid
        while grid.count():
            grid.takeAt(0)
        for box in self._quick_boxes:
            box.setParent(None)
            box.deleteLater()
        self._quick_items = []
        self._quick_boxes = []
        self._quick_help_btns = []
        for key in self._quick_keys:
            p = PARAMS_BY_KEY[key]
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            w = build_quick_widget(p)
            lbl = None
            if p.widget != "check":
                lbl = QLabel(quick_label_text(p))
                row.addWidget(lbl)
            row.addWidget(w)
            self._add_help(row, key, registry=self._quick_help_btns)
            self._quick_items.append((p, w, lbl))
            self._quick_boxes.append(box)
        self._arrange_quick_toggles()

    def get_quick_params(self):
        """E10: currently shown quick-toggle keys, in display order."""
        return list(self._quick_keys)

    def set_quick_params(self, keys):
        """E10: apply a quick-toggle key list (validated; rebuilds the group).
        No-op when the cleaned list is unchanged."""
        cleaned = sanitize_quick_keys(keys)
        if cleaned == self._quick_keys:
            return
        self._quick_keys = cleaned
        self._rebuild_quick_toggles()

    def _retranslate_quick_toggles(self):
        for p, w, lbl in self._quick_items:
            if lbl is not None:
                lbl.setText(quick_label_text(p))
            elif p.widget == "check":
                w.setText(quick_label_text(p))
        for btn in self._quick_help_btns:
            btn.setToolTip(t("查看参数说明"))

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
        out = {
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
            "webui": self.chk_webui.isChecked(),
            "verbose": self.chk_verbose.isChecked(),
        }
        # E10: dynamic quick-toggle slots (only the ones currently shown)
        for p, w, _lbl in self._quick_items:
            out[p.key] = read_quick(p, w)
        return out

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
        if "webui" in values:
            self.chk_webui.setChecked(values["webui"])
        if "verbose" in values:
            self.chk_verbose.setChecked(values["verbose"])
        # E10: dynamic quick-toggle slots; corrupt values raise and are
        # skipped per-key by the set_values() fallback loop
        for p, w, _lbl in self._quick_items:
            if p.key in values:
                write_quick(p, w, values[p.key])

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
        self.chk_webui.setText(t("WebUI"))
        self.chk_verbose.setText(t("Verbose"))
        self._lbl_mmproj.setText(t("mmproj:"))
        self._lbl_top_p.setText(t("Top-P:"))
        self._lbl_top_k.setText(t("Top-K:"))
        self._lbl_min_p.setText(t("Min-P:"))
        self._btn_browse_model.setText(t("..."))
        self._btn_browse_mmproj.setText(t("..."))
        self._retranslate_quick_toggles()
        for btn in self._help_btns:
            btn.setToolTip(t("查看参数说明"))
        self._render_gpu_info()
