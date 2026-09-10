import logging
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QCheckBox, QTextEdit, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QLabel, QAbstractItemView,
    QScrollArea, QToolButton
)
from PyQt6.QtCore import Qt
from core.i18n import t
from core.constants import DEFAULT_HOST, DEFAULT_PORT, MAIN_GPU_MAX
from core.params_schema import PARAMS_BY_KEY, TAB_TITLES, UI_PARAMS, tab_params
from core.params_help import has_help
from ui.param_help import make_help_button

logger = logging.getLogger(__name__)

# Shared combo item lists
CACHE_TYPE_ITEMS = ["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"]
SPEC_TYPE_ITEMS = ["none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash", "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache"]
LOAD_MODE_ITEMS = ["auto", "none", "mmap", "mlock", "mmap+mlock", "dio"]
DRAFT_PRIO_ITEMS = ["normal", "medium", "high", "realtime"]


class AdvancedPanel(QWidget):
    def __init__(self, parent=None, chat_templates=None, defaults=None):
        super().__init__(parent)
        self._chat_templates = chat_templates or []
        self._defaults = defaults or {}
        self.init_ui()
        self._apply_defaults()

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

    def tab_keys(self):
        """Tab keys in UI order (stable identifiers for persistence)."""
        return [k for k, _ in self._TAB_TITLES]

    def current_tab_key(self):
        """Key of the currently selected tab (or '' if none)."""
        idx = self.tabs.currentIndex()
        keys = self.tab_keys()
        return keys[idx] if 0 <= idx < len(keys) else ""

    def set_chat_templates(self, templates):
        """Replace the chat-template list, preserving the current selection (plan A10)."""
        self._chat_templates = list(templates)
        current = self.adv_chat_template.currentText()
        self.adv_chat_template.blockSignals(True)
        try:
            self.adv_chat_template.clear()
            self.adv_chat_template.addItems([""] + self._chat_templates)
            idx = self.adv_chat_template.findText(current)
            if idx >= 0:
                self.adv_chat_template.setCurrentIndex(idx)
        finally:
            self.adv_chat_template.blockSignals(False)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._form_labels = {}
        self._browse_btns = []
        self._add_rm_btns = []
        self._section_labels = []
        self._help_btns = []
        self.tabs = QTabWidget()
        for tab_key, tab_name in self._TAB_TITLES:
            self.tabs.addTab(self._create_tab(tab_key), t(tab_name))
        layout.addWidget(self.tabs)

    def _add_form_row(self, form, label_key, widget, param_key=None,
                      right_label=False):
        """Add a label+widget row; if the param has an explanation, a small
        "?" button is appended to the label (param help card on click)."""
        lbl = QLabel(t(label_key))
        self._form_labels[label_key] = lbl
        btn = None
        if param_key is not None and has_help(param_key):
            btn = make_help_button(param_key, lambda: self._defaults)
            self._help_btns.append(btn)
        if btn is None:
            form.addRow(lbl, widget)
            return lbl
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        if right_label:
            hl.addStretch()  # keep the model tab's right-aligned labels
        hl.addWidget(lbl)
        hl.addWidget(btn)
        form.addRow(holder, widget)
        return lbl

    def _browse_to_edit(self, edit, mode="file", title=None, filter_str="GGUF Files (*.gguf)"):
        if mode == "file":
            path, _ = QFileDialog.getOpenFileName(self, title or t("选择文件"), "", filter_str)
        else:
            path = QFileDialog.getExistingDirectory(self, title or t("选择目录"))
        if path:
            edit.setText(path)

    # -- C1: schema-driven UI construction ------------------------------
    #
    # The nine tabs are built from core.params_schema: each Param carries
    # its tab, row order, label, and the full widget definition (kind,
    # range, items, placeholder, tooltip, browse dialog, ...). The one
    # non-parameter row (the E8 GPU-info label) is anchored after the
    # parameter that precedes it (gpu tab, after tensor_split).
    #
    # Tab grouping follows the semantic structure of llama.cpp
    # (common_params_sampling / common_params_speculative / mmproj /
    # cpuparams, plus the server README's Multimodal/Tools/MCP sections):
    # model (+sources+adapters+mmproj), context (+KV cache+RoPE/YaRN),
    # sampling, gpu (+CPU threads/affinity), spec (speculative decoding),
    # server, agent (tools/MCP), chat, advanced (logging/text I/O).
    #
    # The schema stores raw Chinese literals; t() is applied at build
    # time here (labels via _add_form_row, items/placeholders/tooltips
    # via _T) so live language switching keeps working (D4).

    _TAB_TITLES = TAB_TITLES  # single source of truth (core.params_schema)
    # Text widgets whose construction-time text is the param default
    # (the rest start empty; _apply_defaults fills them all anyway).
    _INIT_TEXT = frozenset({"host", "cors_origins", "cors_methods",
                            "cors_headers", "fit_target", "samplers"})
    _CJK_RE = re.compile(r"[\u4e00-\u9fff]")

    @classmethod
    def _T(cls, s):
        """Translate a schema string at build/retranslate time (C1)."""
        return t(s) if cls._CJK_RE.search(s) else s

    @classmethod
    def _t_items(cls, items):
        return [cls._T(i) for i in items]

    def _create_tab(self, tab_key):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)
        if tab_key == "model":
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for p in tab_params(tab_key):
            self._build_param_row(form, p)
            if tab_key == "gpu" and p.key == "tensor_split":
                # E8: detected GPU devices (from the `--list-devices` probe)
                self.gpu_info_label = QLabel("")
                self.gpu_info_label.setStyleSheet("color: #6b7280; font-size: 11px;")
                self.gpu_info_label.setVisible(False)
                form.addRow(self.gpu_info_label)
        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _add_widget_row(self, form, p, row_widget, widget=None):
        # Explicit None check: empty Qt models (e.g. a fresh QListWidget)
        # are falsy in PyQt, so `widget or row_widget` would misfire.
        if widget is None:
            widget = row_widget
        setattr(self, p.wattr, widget)
        self._add_form_row(form, p.label, row_widget, param_key=p.key,
                           right_label=(p.tab == "model"))

    def _build_param_row(self, form, p):
        kind = p.widget
        if kind == "check":
            w = QCheckBox()
            if p.default:
                w.setChecked(True)
            self._add_widget_row(form, p, w)
        elif kind == "spin":
            w = QSpinBox()
            w.setRange(p.min, p.max)
            if p.default:
                w.setValue(p.default)
            if p.tooltip:
                w.setToolTip(self._T(p.tooltip))
            self._add_widget_row(form, p, w)
        elif kind == "dspin":
            w = QDoubleSpinBox()
            w.setRange(p.min, p.max)
            if p.step:
                w.setSingleStep(p.step)
            if p.default:
                w.setValue(float(p.default))
            if p.tooltip:
                w.setToolTip(self._T(p.tooltip))
            self._add_widget_row(form, p, w)
        elif kind in ("combo", "combo_index"):
            w = QComboBox()
            w.addItems(self._t_items(p.items))
            if kind == "combo" and p.curtext:
                w.setCurrentText(p.curtext)
            if kind == "combo_index" and p.curidx is not None:
                w.setCurrentIndex(p.curidx)
            self._add_widget_row(form, p, w)
        elif kind == "combo_edit":
            self._build_combo_edit_row(form, p)
        elif kind == "mtext":
            w = QTextEdit()
            w.setMaximumHeight(80)
            if p.placeholder:
                w.setPlaceholderText(self._T(p.placeholder))
            row_w = QWidget()
            lay = QVBoxLayout(row_w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(w)
            self._add_widget_row(form, p, row_w, widget=w)
        elif kind == "list":
            row_w, w = self._make_list_row(self._T(p.list_title), p.list_filter)
            self._add_widget_row(form, p, row_w, widget=w)
        elif kind == "checklist":
            w = QListWidget()
            w.setMaximumHeight(80)
            for name in p.items:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                w.addItem(item)
            self._add_widget_row(form, p, w)
        else:  # text / file / password / dir / dir_text
            w = QLineEdit()
            if p.placeholder:
                w.setPlaceholderText(self._T(p.placeholder))
            if p.echo:
                w.setEchoMode(QLineEdit.EchoMode.Password)
            if p.key in self._INIT_TEXT and p.default:
                w.setText(str(p.default))
            if p.browse:
                row_w = QWidget()
                lay = QHBoxLayout(row_w)
                lay.setContentsMargins(0, 0, 0, 0)
                btn = QPushButton(t("📂 浏览"))
                self._browse_btns.append(btn)
                title = self._T(p.browse_title) if p.browse_title else None
                filter_str = p.filter_str or "All Files (*)"
                btn.clicked.connect(lambda: self._browse_to_edit(
                    w, mode=p.browse, title=title, filter_str=filter_str))
                btn.setFixedWidth(80)
                lay.addWidget(w, 1)
                lay.addWidget(btn)
                self._add_widget_row(form, p, row_w, widget=w)
            else:
                self._add_widget_row(form, p, w)

    def _build_combo_edit_row(self, form, p):
        w = QComboBox()
        if p.key == "chat_template":
            # Dynamic item list (live-parsed chat templates, plan A10).
            w.addItems([""] + self._chat_templates)
        elif p.items:
            w.addItems(self._t_items(p.items))
        w.setEditable(True)
        if p.curtext:
            w.setCurrentText(p.curtext)
        setattr(self, p.wattr, w)
        self._add_form_row(form, p.label, w, param_key=p.key,
                           right_label=(p.tab == "model"))
        if p.value != "ngl":
            return
        # ngl composite: the editable combo plus a helper spinbox; the
        # combo is the source of truth (get_values reads currentText).
        spin = QSpinBox()
        spin.setRange(0, 999)
        spin.setValue(0)
        spin.setToolTip(t("手动指定层数"))
        spin.valueChanged.connect(lambda v: w.setEditText(str(v)))
        self.adv_ngl_spin = spin
        self._add_form_row(form, "手动指定层数:", spin, param_key="n_gpu_layers")

    def _make_list_row(self, title, filter_str):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lst = QListWidget()
        lst.setMaximumHeight(60)
        lst.setMinimumHeight(40)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        btn_row = QHBoxLayout()
        add_btn = QPushButton(t("➕ 添加"))
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(lambda: self._add_to_list(lst, title, filter_str))
        self._add_rm_btns.append(add_btn)
        rm_btn = QPushButton(t("➖ 移除"))
        rm_btn.setFixedWidth(80)
        self._add_rm_btns.append(rm_btn)
        rm_btn.clicked.connect(lambda: self._remove_from_list(lst))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rm_btn)
        btn_row.addStretch()
        lay.addWidget(lst)
        lay.addLayout(btn_row)
        return w, lst

    def _add_to_list(self, lst, title, filter_str):
        path, _ = QFileDialog.getOpenFileName(self, title, "", filter_str)
        if path:
            lst.addItem(path)

    def _remove_from_list(self, lst):
        for item in lst.selectedItems():
            lst.takeItem(lst.row(item))

    def _read_param(self, p):
        w = getattr(self, p.wattr)
        kind = p.widget
        if kind == "list":
            return [w.item(i).text() for i in range(w.count())]
        if kind == "checklist":
            return [w.item(i).text() for i in range(w.count())
                    if w.item(i).checkState() == Qt.CheckState.Checked]
        if kind == "combo_index":
            return w.currentIndex()
        if kind == "mtext":
            return w.toPlainText()
        if kind == "text" and p.value == "join":
            return [s.strip() for s in w.text().split(",") if s.strip()]
        if kind == "spin" or kind == "dspin":
            return w.value()
        if kind == "check":
            return w.isChecked()
        # text / file / password / dir / dir_text / combo / combo_edit
        return w.currentText() if kind in ("combo", "combo_edit") else w.text()

    def _write_param(self, p, val):
        w = getattr(self, p.wattr)
        kind = p.widget
        if kind == "list":
            w.clear()
            for item in val:
                w.addItem(item)
        elif kind == "checklist":
            for i in range(w.count()):
                item = w.item(i)
                item.setCheckState(
                    Qt.CheckState.Checked if item.text() in val else Qt.CheckState.Unchecked)
        elif kind == "combo_index":
            w.setCurrentIndex(val)
        elif kind == "mtext":
            w.setPlainText(val)
        elif kind == "text" and p.value == "join":
            w.setText(", ".join(str(x) for x in val))
        elif kind == "check":
            w.setChecked(val)
        elif kind in ("spin", "dspin"):
            w.setValue(val)
        elif kind == "combo":
            w.setCurrentText(val)
        elif kind == "combo_edit":
            if p.value == "ngl":
                # Composite: editable combo + helper spinbox. The combo is
                # the source of truth (get_values reads currentText).
                val = str(val)
                idx = w.findText(val)
                self.adv_ngl_spin.blockSignals(True)
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    w.setEditText(val)
                try:
                    self.adv_ngl_spin.setValue(int(val))
                except (ValueError, TypeError):
                    self.adv_ngl_spin.setValue(0)
                self.adv_ngl_spin.blockSignals(False)
            elif p.value in ("ngl_edit", "combo_edit"):
                val = str(val)
                idx = w.findText(val)
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    w.setEditText(val)
            else:
                w.setCurrentText(val)
        else:  # text / file / password / dir / dir_text
            # fit_target may hold a float default; the line edit needs a str.
            if p.key == "fit_target":
                w.setText(str(val))
            else:
                w.setText(val)

    def get_values(self):
        return {p.key: self._read_param(p) for p in UI_PARAMS
                if p.wattr is not None}

    def set_values(self, values):
        values = dict(values)
        try:
            self._set_values_impl(values)
            return
        except (TypeError, ValueError):
            # 预设值类型损坏（如 port 存成了字符串）：按 key 逐个应用，
            # 跳过问题 key，避免一个坏值中断整个预设加载
            for key in values:
                try:
                    self._set_values_impl({key: values[key]})
                except (TypeError, ValueError):
                    logger.warning("忽略无效的预设值: %s=%r", key, values[key])

    def _set_values_impl(self, values):
        for key, val in values.items():
            p = PARAMS_BY_KEY.get(key)
            if p is None or p.wattr is None:
                continue  # unknown key or schema-only param (prio_batch)
            self._write_param(p, val)

    def set_gpu_info(self, devices):
        """E8: render detected GPU devices (or CPU-only) in the GPU/perf tab."""
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

    def retranslate_ui(self):
        # Tab titles (from _TAB_TITLES — same source as init_ui)
        for i, (_, tab_name) in enumerate(self._TAB_TITLES):
            self.tabs.setTabText(i, t(tab_name))

        # Form labels
        for key, lbl in self._form_labels.items():
            lbl.setText(t(key))

        # Section labels
        for key, lbl in self._section_labels:
            lbl.setText(f"<b>{t(key)}</b>")

        # Combo item lists with translatable text (mirostat)
        for p in UI_PARAMS:
            if (p.widget in ("combo", "combo_index") and p.items
                    and any(self._CJK_RE.search(i) for i in p.items)):
                w = getattr(self, p.wattr)
                idx = w.currentIndex()
                w.clear()
                w.addItems(self._t_items(p.items))
                w.setCurrentIndex(idx)

        # Placeholders (schema strings containing CJK are translated;
        # ASCII-only placeholders pass through unchanged)
        for p in UI_PARAMS:
            if p.placeholder and self._CJK_RE.search(p.placeholder):
                w = getattr(self, p.wattr)
                w.setPlaceholderText(t(p.placeholder))
        self._render_gpu_info()

        # Help buttons (? tooltips)
        for btn in self._help_btns:
            btn.setToolTip(t("查看参数说明"))

        # Buttons
        for btn in self._browse_btns:
            btn.setText(t("📂 浏览"))
        if hasattr(self, '_add_rm_btns'):
            for btn in self._add_rm_btns:
                if btn.text() in ("➕ 添加", "➕ Add"):
                    btn.setText(t("➕ 添加"))
                elif btn.text() in ("➖ 移除", "➖ Remove"):
                    btn.setText(t("➖ 移除"))
