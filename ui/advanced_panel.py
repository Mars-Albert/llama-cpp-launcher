from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QCheckBox, QTextEdit, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QLabel, QAbstractItemView,
    QScrollArea
)
from PyQt6.QtCore import Qt
from core.i18n import t


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

        if "repeat_penalty" in d:
            self.adv_repeat_penalty.setValue(d["repeat_penalty"])
        if "parallel" in d:
            self.adv_parallel.setValue(d["parallel"])
        if "log_verbosity" in d:
            lv = d["log_verbosity"]
            if 0 <= lv <= 4:
                self.adv_log_verbosity.setCurrentIndex(lv)
        if "mirostat" in d:
            self.adv_mirostat.setCurrentIndex(d["mirostat"])
        if "sampler_seq" in d:
            self.adv_sampler_seq.setText(d["sampler_seq"])
        if "spec_type" in d:
            self.adv_spec_type.setCurrentText(d["spec_type"])

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._form_labels = {}
        self._browse_btns = []
        self._add_rm_btns = []
        self._section_labels = []
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_model_tab(), t("模型"))
        self.tabs.addTab(self._create_context_tab(), t("上下文"))
        self.tabs.addTab(self._create_sampling_tab(), t("采样"))
        self.tabs.addTab(self._create_gpu_tab(), t("GPU/性能"))
        self.tabs.addTab(self._create_server_tab(), t("服务"))
        self.tabs.addTab(self._create_chat_tab(), t("聊天/推理"))
        self.tabs.addTab(self._create_advanced_tab(), t("高级"))
        layout.addWidget(self.tabs)

    def _add_form_row(self, form, label_key, widget):
        lbl = QLabel(t(label_key))
        self._form_labels[label_key] = lbl
        form.addRow(lbl, widget)
        return lbl

    def _make_file_row(self, browse_mode="file", filter_str="All Files (*)"):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        btn = QPushButton(t("浏览"))
        self._browse_btns.append(btn)
        def do_browse():
            if browse_mode == "file":
                path, _ = QFileDialog.getOpenFileName(self, t("选择文件"), "", filter_str)
            else:
                path = QFileDialog.getExistingDirectory(self, t("选择目录"))
            if path:
                edit.setText(path)
        btn.clicked.connect(do_browse)
        btn.setFixedWidth(80)
        lay.addWidget(edit, 1)
        lay.addWidget(btn)
        return w, edit

    def _create_model_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.adv_model = QLineEdit()
        self.adv_model.setPlaceholderText(t("选择或输入模型文件路径"))
        model_browse = QPushButton(t("浏览"))
        model_browse.setFixedWidth(80)
        self._browse_btns.append(model_browse)
        model_browse.clicked.connect(lambda: self.adv_model.setText(QFileDialog.getOpenFileName(self, t("选择模型"), "", "GGUF Files (*.gguf)")[0]))
        model_w = QWidget()
        model_lay = QHBoxLayout(model_w)
        model_lay.setContentsMargins(0, 0, 0, 0)
        model_lay.addWidget(self.adv_model)
        model_lay.addWidget(model_browse)
        self._add_form_row(form, "模型 (--model)", model_w)

        self.adv_mmproj = QLineEdit()
        self.adv_mmproj.setPlaceholderText(t("选择或输入视觉投影模型路径"))
        mmproj_browse = QPushButton(t("浏览"))
        mmproj_browse.setFixedWidth(80)
        self._browse_btns.append(mmproj_browse)
        mmproj_browse.clicked.connect(lambda: self.adv_mmproj.setText(QFileDialog.getOpenFileName(self, t("选择MMProj"), "", "GGUF Files (*.gguf)")[0]))
        mmproj_w = QWidget()
        mmproj_lay = QHBoxLayout(mmproj_w)
        mmproj_lay.setContentsMargins(0, 0, 0, 0)
        mmproj_lay.addWidget(self.adv_mmproj)
        mmproj_lay.addWidget(mmproj_browse)
        self._add_form_row(form, "视觉投影 (--mmproj)", mmproj_w)

        self.adv_mmproj_auto = QCheckBox()
        self.adv_mmproj_auto.setChecked(True)
        self._add_form_row(form, "自动MMProj (--mmproj-auto):", self.adv_mmproj_auto)

        self.adv_mmproj_offload = QCheckBox()
        self.adv_mmproj_offload.setChecked(True)
        self._add_form_row(form, "MMProj GPU卸载 (--mmproj-offload):", self.adv_mmproj_offload)

        self.adv_image_min_tokens = QSpinBox()
        self.adv_image_min_tokens.setRange(0, 999999)
        self.adv_image_min_tokens.setToolTip(t("0=使用模型默认"))
        self._add_form_row(form, "图像最小Token (--image-min-tokens):", self.adv_image_min_tokens)

        self.adv_image_max_tokens = QSpinBox()
        self.adv_image_max_tokens.setRange(0, 999999)
        self.adv_image_max_tokens.setToolTip(t("0=使用模型默认"))
        self._add_form_row(form, "图像最大Token (--image-max-tokens):", self.adv_image_max_tokens)

        lora_w, self.adv_lora_list = self._make_list_row(t("LoRA 适配器"), t("选择LoRA文件"), "GGUF Files (*.gguf)")
        self._add_form_row(form, "LoRA 适配器 (--lora)", lora_w)

        self.adv_lora_scaled = QLineEdit()
        self.adv_lora_scaled.setPlaceholderText("1.0, 0.5, ...")
        self._add_form_row(form, "LoRA 缩放 (--lora-scaled)", self.adv_lora_scaled)

        cv_w, self.adv_cv_list = self._make_list_row(t("控制向量"), t("选择控制向量文件"), "GGUF Files (*.gguf)")
        self._add_form_row(form, "控制向量 (--control-vector)", cv_w)

        self.adv_cv_scaled = QLineEdit()
        self.adv_cv_scaled.setPlaceholderText("path:scale, ...")
        self._add_form_row(form, "控制向量缩放 (--control-vector-scaled)", self.adv_cv_scaled)

        self.adv_cv_layer_range = QLineEdit()
        self.adv_cv_layer_range.setPlaceholderText("START END")
        self._add_form_row(form, "控制向量层范围 (--control-vector-layer-range)", self.adv_cv_layer_range)

        self.adv_alias = QLineEdit()
        self.adv_alias.setPlaceholderText(t("模型的自定义名称"))
        self._add_form_row(form, "别名 (--alias)", self.adv_alias)

        self.adv_tags = QLineEdit()
        self.adv_tags.setPlaceholderText(t("逗号分隔的标签列表"))
        self._add_form_row(form, "标签 (--tags)", self.adv_tags)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _make_list_row(self, label, title, filter_str):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lst = QListWidget()
        lst.setMaximumHeight(60)
        lst.setMinimumHeight(40)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        btn_row = QHBoxLayout()
        add_btn = QPushButton(t("添加"))
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(lambda: self._add_to_list(lst, title, filter_str))
        self._add_rm_btns.append(add_btn)
        rm_btn = QPushButton(t("移除"))
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

    def _create_context_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)

        self.adv_ctx_size = QSpinBox()
        self.adv_ctx_size.setRange(0, 999999)
        self.adv_ctx_size.setValue(0)
        self.adv_ctx_size.setToolTip(t("0=使用模型默认"))
        self._add_form_row(form, "上下文大小 (--ctx-size):", self.adv_ctx_size)

        self.adv_batch_size = QSpinBox()
        self.adv_batch_size.setRange(64, 16384)
        self.adv_batch_size.setValue(2048)
        self._add_form_row(form, "批处理大小 (--batch-size):", self.adv_batch_size)

        self.adv_ubatch_size = QSpinBox()
        self.adv_ubatch_size.setRange(32, 4096)
        self.adv_ubatch_size.setValue(512)
        self._add_form_row(form, "物理批处理 (--ubatch-size):", self.adv_ubatch_size)

        self.adv_n_predict = QSpinBox()
        self.adv_n_predict.setRange(-1, 999999)
        self.adv_n_predict.setValue(-1)
        self._add_form_row(form, "预测Token数 (--n-predict):", self.adv_n_predict)

        self.adv_keep = QSpinBox()
        self.adv_keep.setRange(0, 999999)
        self.adv_keep.setValue(0)
        self._add_form_row(form, "保留历史 (--keep):", self.adv_keep)

        self.adv_cache_prompt = QCheckBox()
        self.adv_cache_prompt.setChecked(True)
        self._add_form_row(form, "提示词缓存 (--cache-prompt):", self.adv_cache_prompt)

        self.adv_cache_reuse = QSpinBox()
        self.adv_cache_reuse.setRange(0, 999999)
        self.adv_cache_reuse.setValue(0)
        self._add_form_row(form, "缓存复用 (--cache-reuse):", self.adv_cache_reuse)

        self.adv_cache_ram = QSpinBox()
        self.adv_cache_ram.setRange(-1, 999999)
        self.adv_cache_ram.setValue(8192)
        self._add_form_row(form, "缓存RAM (--cache-ram):", self.adv_cache_ram)

        self.adv_context_shift = QCheckBox()
        self._add_form_row(form, "上下文偏移 (--context-shift):", self.adv_context_shift)

        self.adv_kv_offload = QCheckBox()
        self.adv_kv_offload.setChecked(True)
        self._add_form_row(form, "KV卸载 (--kv-offload):", self.adv_kv_offload)

        self.adv_kv_unified = QCheckBox()
        self.adv_kv_unified.setChecked(True)
        self._add_form_row(form, "统一KV (--kv-unified):", self.adv_kv_unified)

        self.adv_cache_type_k = QComboBox()
        self.adv_cache_type_k.addItems(["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"])
        self.adv_cache_type_k.setCurrentText("f16")
        self._add_form_row(form, "KV Cache K类型 (--cache-type-k):", self.adv_cache_type_k)

        self.adv_cache_type_v = QComboBox()
        self.adv_cache_type_v.addItems(["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"])
        self.adv_cache_type_v.setCurrentText("f16")
        self._add_form_row(form, "KV Cache V类型 (--cache-type-v):", self.adv_cache_type_v)

        self.adv_swa_full = QCheckBox()
        self._add_form_row(form, "SWA完整模式 (--swa-full):", self.adv_swa_full)

        self.adv_escape = QCheckBox()
        self.adv_escape.setChecked(True)
        self._add_form_row(form, "转义处理 (--escape):", self.adv_escape)

        self.adv_defrag_thold = QSpinBox()
        self.adv_defrag_thold.setRange(0, 999999)
        self.adv_defrag_thold.setToolTip("(DEPRECATED) KV cache defragmentation threshold")
        self._add_form_row(form, "KV整理阈值 (--defrag-thold):", self.adv_defrag_thold)

        self.adv_cache_idle_slots = QCheckBox()
        self.adv_cache_idle_slots.setChecked(True)
        self._add_form_row(form, "空闲槽位缓存 (--cache-idle-slots):", self.adv_cache_idle_slots)

        self.adv_ctx_checkpoints = QSpinBox()
        self.adv_ctx_checkpoints.setRange(1, 256)
        self.adv_ctx_checkpoints.setValue(32)
        self._add_form_row(form, "上下文检查点 (--ctx-checkpoints):", self.adv_ctx_checkpoints)

        self.adv_checkpoint_every = QSpinBox()
        self.adv_checkpoint_every.setRange(-1, 999999)
        self.adv_checkpoint_every.setValue(8192)
        self._add_form_row(form, "每N Token检查点 (--checkpoint-every-n-tokens):", self.adv_checkpoint_every)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _create_sampling_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)

        self.adv_temp = QDoubleSpinBox()
        self.adv_temp.setRange(0, 2.0)
        self.adv_temp.setSingleStep(0.05)
        self.adv_temp.setValue(0.8)
        self._add_form_row(form, "温度 (--temp):", self.adv_temp)

        self.adv_top_k = QSpinBox()
        self.adv_top_k.setRange(0, 200)
        self.adv_top_k.setValue(40)
        self._add_form_row(form, "Top-K (--top-k):", self.adv_top_k)

        self.adv_top_p = QDoubleSpinBox()
        self.adv_top_p.setRange(0, 1.0)
        self.adv_top_p.setSingleStep(0.05)
        self.adv_top_p.setValue(0.95)
        self._add_form_row(form, "Top-P (--top-p):", self.adv_top_p)

        self.adv_min_p = QDoubleSpinBox()
        self.adv_min_p.setRange(0, 1.0)
        self.adv_min_p.setSingleStep(0.05)
        self.adv_min_p.setValue(0.05)
        self._add_form_row(form, "Min-P (--min-p):", self.adv_min_p)

        self.adv_typical_p = QDoubleSpinBox()
        self.adv_typical_p.setRange(0, 1.0)
        self.adv_typical_p.setSingleStep(0.05)
        self.adv_typical_p.setValue(1.0)
        self._add_form_row(form, "Typical-P (--typical-p):", self.adv_typical_p)

        self.adv_top_n_sigma = QDoubleSpinBox()
        self.adv_top_n_sigma.setRange(-1.0, 3.0)
        self.adv_top_n_sigma.setSingleStep(0.1)
        self.adv_top_n_sigma.setValue(-1.0)
        self._add_form_row(form, "Top-N-Sigma (--top-n-sigma):", self.adv_top_n_sigma)

        self.adv_xtc_prob = QDoubleSpinBox()
        self.adv_xtc_prob.setRange(0, 1.0)
        self.adv_xtc_prob.setSingleStep(0.05)
        self.adv_xtc_prob.setValue(0.0)
        self._add_form_row(form, "XTC概率 (--xtc-probability):", self.adv_xtc_prob)

        self.adv_xtc_thresh = QDoubleSpinBox()
        self.adv_xtc_thresh.setRange(0, 1.0)
        self.adv_xtc_thresh.setSingleStep(0.05)
        self.adv_xtc_thresh.setValue(0.1)
        self._add_form_row(form, "XTC阈值 (--xtc-threshold):", self.adv_xtc_thresh)

        self.adv_repeat_penalty = QDoubleSpinBox()
        self.adv_repeat_penalty.setRange(0, 2.0)
        self.adv_repeat_penalty.setSingleStep(0.05)
        self.adv_repeat_penalty.setValue(1.0)
        self._add_form_row(form, "重复惩罚 (--repeat-penalty):", self.adv_repeat_penalty)

        self.adv_presence_penalty = QDoubleSpinBox()
        self.adv_presence_penalty.setRange(-2.0, 2.0)
        self.adv_presence_penalty.setSingleStep(0.1)
        self.adv_presence_penalty.setValue(0.0)
        self._add_form_row(form, "存在惩罚 (--presence-penalty):", self.adv_presence_penalty)

        self.adv_freq_penalty = QDoubleSpinBox()
        self.adv_freq_penalty.setRange(-2.0, 2.0)
        self.adv_freq_penalty.setSingleStep(0.1)
        self.adv_freq_penalty.setValue(0.0)
        self._add_form_row(form, "频率惩罚 (--frequency-penalty):", self.adv_freq_penalty)

        self.adv_dry_mult = QDoubleSpinBox()
        self.adv_dry_mult.setRange(0, 2.0)
        self.adv_dry_mult.setSingleStep(0.05)
        self.adv_dry_mult.setValue(0.0)
        self._add_form_row(form, "DRY乘数 (--dry-multiplier):", self.adv_dry_mult)

        self.adv_dry_base = QDoubleSpinBox()
        self.adv_dry_base.setRange(1.0, 3.0)
        self.adv_dry_base.setSingleStep(0.05)
        self.adv_dry_base.setValue(1.75)
        self._add_form_row(form, "DRY基数 (--dry-base):", self.adv_dry_base)

        self.adv_dry_len = QSpinBox()
        self.adv_dry_len.setRange(1, 64)
        self.adv_dry_len.setValue(2)
        self._add_form_row(form, "DRY允许长度 (--dry-allowed-length):", self.adv_dry_len)

        self.adv_dry_penalty_last_n = QSpinBox()
        self.adv_dry_penalty_last_n.setRange(-1, 999999)
        self.adv_dry_penalty_last_n.setValue(-1)
        self._add_form_row(form, "DRY惩罚最后N (--dry-penalty-last-n):", self.adv_dry_penalty_last_n)

        self.adv_adaptive_target = QDoubleSpinBox()
        self.adv_adaptive_target.setRange(-1.0, 1.0)
        self.adv_adaptive_target.setSingleStep(0.05)
        self.adv_adaptive_target.setValue(-1.0)
        self._add_form_row(form, "自适应目标 (--adaptive-target):", self.adv_adaptive_target)

        self.adv_adaptive_decay = QDoubleSpinBox()
        self.adv_adaptive_decay.setRange(0.0, 0.99)
        self.adv_adaptive_decay.setSingleStep(0.05)
        self.adv_adaptive_decay.setValue(0.9)
        self._add_form_row(form, "自适应衰减 (--adaptive-decay):", self.adv_adaptive_decay)

        self.adv_repeat_last_n = QSpinBox()
        self.adv_repeat_last_n.setRange(-1, 999999)
        self.adv_repeat_last_n.setValue(64)
        self._add_form_row(form, "重复最后N (--repeat-last-n):", self.adv_repeat_last_n)

        self.adv_seed = QSpinBox()
        self.adv_seed.setRange(-1, 999999999)
        self.adv_seed.setValue(-1)
        self._add_form_row(form, "随机种子 (--seed):", self.adv_seed)

        self.adv_mirostat = QComboBox()
        self.adv_mirostat.addItems([t("禁用") + " (0)", "Mirostat (1)", "Mirostat 2.0 (2)"])
        self._add_form_row(form, "Mirostat (--mirostat):", self.adv_mirostat)

        self.adv_mirostat_lr = QDoubleSpinBox()
        self.adv_mirostat_lr.setRange(0, 1.0)
        self.adv_mirostat_lr.setSingleStep(0.01)
        self.adv_mirostat_lr.setValue(0.1)
        self._add_form_row(form, "Mirostat学习率 (--mirostat-lr):", self.adv_mirostat_lr)

        self.adv_mirostat_ent = QDoubleSpinBox()
        self.adv_mirostat_ent.setRange(0, 10.0)
        self.adv_mirostat_ent.setSingleStep(0.1)
        self.adv_mirostat_ent.setValue(5.0)
        self._add_form_row(form, "Mirostat熵 (--mirostat-ent):", self.adv_mirostat_ent)

        self.adv_dynatemp_range = QDoubleSpinBox()
        self.adv_dynatemp_range.setRange(0, 2.0)
        self.adv_dynatemp_range.setSingleStep(0.05)
        self.adv_dynatemp_range.setValue(0.0)
        self._add_form_row(form, "动态温度范围 (--dynatemp-range):", self.adv_dynatemp_range)

        self.adv_dynatemp_exp = QDoubleSpinBox()
        self.adv_dynatemp_exp.setRange(0.1, 5.0)
        self.adv_dynatemp_exp.setSingleStep(0.1)
        self.adv_dynatemp_exp.setValue(1.0)
        self._add_form_row(form, "动态温度指数 (--dynatemp-exp):", self.adv_dynatemp_exp)

        self.adv_ignore_eos = QCheckBox()
        self._add_form_row(form, "忽略EOS (--ignore-eos):", self.adv_ignore_eos)

        self.adv_backend_sampling = QCheckBox()
        self._add_form_row(form, "后端采样 (--backend-sampling):", self.adv_backend_sampling)

        self.adv_samplers = QLineEdit()
        self.adv_samplers.setText("penalties;dry;top_n_sigma;top_k;typ_p;top_p;min_p;xtc;temperature")
        self._add_form_row(form, "采样器顺序 (--samplers):", self.adv_samplers)

        self.adv_sampler_seq = QLineEdit()
        self.adv_sampler_seq.setPlaceholderText(t("简化采样器序列"))
        self._add_form_row(form, "采样器序列 (--sampling-seq):", self.adv_sampler_seq)

        self.adv_logit_bias = QLineEdit()
        self.adv_logit_bias.setPlaceholderText("TOKEN_ID(+/-)BIAS")
        self._add_form_row(form, "Logit偏置 (--logit-bias):", self.adv_logit_bias)

        grammar_row, self.adv_grammar = self._make_file_row("file", "GBNF Files (*.gbnf)")
        self._add_form_row(form, "Grammar (--grammar):", grammar_row)

        grammar_file_row, self.adv_grammar_file = self._make_file_row("file", "All Files (*)")
        self._add_form_row(form, "Grammar文件 (--grammar-file):", grammar_file_row)

        json_schema_row, self.adv_json_schema = self._make_text_row("JSON Schema")
        self._add_form_row(form, "JSON Schema (--json-schema):", json_schema_row)

        json_schema_file_row, self.adv_json_schema_file = self._make_file_row("file", "JSON Files (*.json)")
        self._add_form_row(form, "JSON Schema文件 (--json-schema-file):", json_schema_file_row)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _make_text_row(self, placeholder):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        edit = QTextEdit()
        edit.setMaximumHeight(80)
        edit.setPlaceholderText(placeholder)
        lay.addWidget(edit)
        return w, edit

    def _create_gpu_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)

        self.adv_ngl = QComboBox()
        self.adv_ngl.addItems(["auto", "all"])
        self.adv_ngl.setEditable(True)
        self._add_form_row(form, "GPU层数 (--n-gpu-layers):", self.adv_ngl)

        self.adv_ngl_spin = QSpinBox()
        self.adv_ngl_spin.setRange(0, 999)
        self.adv_ngl_spin.setValue(0)
        self.adv_ngl_spin.setToolTip(t("手动指定层数"))
        self.adv_ngl_spin.valueChanged.connect(lambda v: self.adv_ngl.setEditText(str(v)))
        self._add_form_row(form, "手动指定层数:", self.adv_ngl_spin)

        self.adv_device = QLineEdit()
        self._add_form_row(form, "设备 (--device):", self.adv_device)

        self.adv_split_mode = QComboBox()
        self.adv_split_mode.addItems(["layer", "none", "row", "tensor"])
        self._add_form_row(form, "分割模式 (--split-mode):", self.adv_split_mode)

        self.adv_tensor_split = QLineEdit()
        self._add_form_row(form, "张量分割 (--tensor-split):", self.adv_tensor_split)

        self.adv_main_gpu = QSpinBox()
        self.adv_main_gpu.setRange(0, 15)
        self.adv_main_gpu.setValue(0)
        self._add_form_row(form, "主GPU (--main-gpu):", self.adv_main_gpu)

        self.adv_threads = QSpinBox()
        self.adv_threads.setRange(-1, 256)
        self.adv_threads.setValue(-1)
        self._add_form_row(form, "线程数 (--threads):", self.adv_threads)

        self.adv_threads_batch = QSpinBox()
        self.adv_threads_batch.setRange(-1, 256)
        self.adv_threads_batch.setValue(-1)
        self._add_form_row(form, "批处理线程 (--threads-batch):", self.adv_threads_batch)

        self.adv_threads_http = QSpinBox()
        self.adv_threads_http.setRange(-1, 256)
        self.adv_threads_http.setValue(-1)
        self._add_form_row(form, "HTTP线程 (--threads-http):", self.adv_threads_http)

        self.adv_prio = QComboBox()
        self.adv_prio.addItems(["low", "normal", "medium", "high", "realtime"])
        self.adv_prio.setCurrentText("normal")
        self._add_form_row(form, "优先级 (--prio):", self.adv_prio)

        self.adv_flash_attn = QComboBox()
        self.adv_flash_attn.addItems(["on", "off", "auto"])
        self.adv_flash_attn.setCurrentText("auto")
        self._add_form_row(form, "Flash Attention (--flash-attn):", self.adv_flash_attn)

        self.adv_mmap = QCheckBox()
        self.adv_mmap.setChecked(True)
        self._add_form_row(form, "内存映射 (--mmap):", self.adv_mmap)

        self.adv_mlock = QCheckBox()
        self._add_form_row(form, "内存锁定 (--mlock):", self.adv_mlock)

        self.adv_no_host = QCheckBox()
        self._add_form_row(form, "无主机内存 (--no-host):", self.adv_no_host)

        self.adv_repack = QCheckBox()
        self.adv_repack.setChecked(True)
        self._add_form_row(form, "重打包 (--repack):", self.adv_repack)

        self.adv_fit = QComboBox()
        self.adv_fit.addItems(["on", "off"])
        self.adv_fit.setCurrentText("on")
        self._add_form_row(form, "适配内存 (--fit):", self.adv_fit)

        self.adv_fit_target = QSpinBox()
        self.adv_fit_target.setRange(0, 32768)
        self.adv_fit_target.setValue(1024)
        self._add_form_row(form, "适配目标MB (--fit-target):", self.adv_fit_target)

        self.adv_fit_ctx = QSpinBox()
        self.adv_fit_ctx.setRange(256, 999999)
        self.adv_fit_ctx.setValue(4096)
        self._add_form_row(form, "适配最小上下文 (--fit-ctx):", self.adv_fit_ctx)

        self.adv_check_tensors = QCheckBox()
        self._add_form_row(form, "检查张量 (--check-tensors):", self.adv_check_tensors)

        self.adv_n_cpu_moe = QSpinBox()
        self.adv_n_cpu_moe.setRange(0, 999)
        self._add_form_row(form, "CPU MoE层数 (--n-cpu-moe):", self.adv_n_cpu_moe)

        self.adv_direct_io = QCheckBox()
        self._add_form_row(form, "直接IO (--direct-io):", self.adv_direct_io)

        self.adv_numa = QComboBox()
        self.adv_numa.addItems(["disable", "distribute", "isolate", "numactl"])
        self._add_form_row(form, "NUMA (--numa):", self.adv_numa)

        self.adv_warmup = QCheckBox()
        self.adv_warmup.setChecked(True)
        self._add_form_row(form, "预热 (--warmup):", self.adv_warmup)

        self.adv_perf = QCheckBox()
        self._add_form_row(form, "性能统计 (--perf):", self.adv_perf)

        self.adv_cpu_moe = QCheckBox()
        self._add_form_row(form, "CPU MoE (--cpu-moe):", self.adv_cpu_moe)

        self.adv_op_offload = QCheckBox()
        self.adv_op_offload.setChecked(True)
        self._add_form_row(form, "算子卸载 (--op-offload):", self.adv_op_offload)

        draft_section_lbl = QLabel(f"<b>{t('--- 草稿模型 (投机解码) ---')}</b>")
        self._section_labels.append(("--- 草稿模型 (投机解码) ---", draft_section_lbl))
        form.addRow(draft_section_lbl)

        draft_model_row, self.adv_draft_model = self._make_file_row("file", "GGUF Files (*.gguf)")
        self._add_form_row(form, "草稿模型 (--model-draft):", draft_model_row)

        self.adv_threads_draft = QSpinBox()
        self.adv_threads_draft.setRange(-1, 256)
        self.adv_threads_draft.setValue(-1)
        self._add_form_row(form, "草稿线程 (--threads-draft):", self.adv_threads_draft)

        self.adv_threads_batch_draft = QSpinBox()
        self.adv_threads_batch_draft.setRange(-1, 256)
        self.adv_threads_batch_draft.setValue(-1)
        self._add_form_row(form, "草稿批处理线程 (--threads-batch-draft):", self.adv_threads_batch_draft)

        self.adv_ctx_size_draft = QSpinBox()
        self.adv_ctx_size_draft.setRange(0, 999999)
        self.adv_ctx_size_draft.setToolTip(t("0=使用模型默认"))
        self._add_form_row(form, "草稿上下文 (--ctx-size-draft):", self.adv_ctx_size_draft)

        self.adv_device_draft = QLineEdit()
        self._add_form_row(form, "草稿设备 (--device-draft):", self.adv_device_draft)

        self.adv_n_gpu_layers_draft = QComboBox()
        self.adv_n_gpu_layers_draft.addItems(["auto", "all"])
        self.adv_n_gpu_layers_draft.setEditable(True)
        self._add_form_row(form, "草稿GPU层数 (--n-gpu-layers-draft):", self.adv_n_gpu_layers_draft)

        self.adv_cpu_moe_draft = QCheckBox()
        self._add_form_row(form, "草稿CPU MoE (--cpu-moe-draft):", self.adv_cpu_moe_draft)

        self.adv_n_cpu_moe_draft = QSpinBox()
        self.adv_n_cpu_moe_draft.setRange(0, 999)
        self._add_form_row(form, "草稿CPU MoE层数 (--n-cpu-moe-draft):", self.adv_n_cpu_moe_draft)

        self.adv_cache_type_k_draft = QComboBox()
        self.adv_cache_type_k_draft.addItems(["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"])
        self.adv_cache_type_k_draft.setCurrentText("f16")
        self._add_form_row(form, "草稿KV K类型 (--spec-draft-type-k):", self.adv_cache_type_k_draft)

        self.adv_cache_type_v_draft = QComboBox()
        self.adv_cache_type_v_draft.addItems(["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"])
        self.adv_cache_type_v_draft.setCurrentText("f16")
        self._add_form_row(form, "草稿KV V类型 (--spec-draft-type-v):", self.adv_cache_type_v_draft)

        self.adv_draft_max = QSpinBox()
        self.adv_draft_max.setRange(1, 256)
        self.adv_draft_max.setValue(16)
        self._add_form_row(form, "草稿Token数 (--spec-draft-n-max):", self.adv_draft_max)

        self.adv_draft_min = QSpinBox()
        self.adv_draft_min.setRange(0, 256)
        self._add_form_row(form, "草稿最小Token (--spec-draft-n-min):", self.adv_draft_min)

        self.adv_draft_p_min = QDoubleSpinBox()
        self.adv_draft_p_min.setRange(0.0, 1.0)
        self.adv_draft_p_min.setSingleStep(0.05)
        self.adv_draft_p_min.setValue(0.75)
        self._add_form_row(form, "草稿最小概率 (--spec-draft-p-min):", self.adv_draft_p_min)

        self.adv_spec_draft_p_split = QDoubleSpinBox()
        self.adv_spec_draft_p_split.setRange(0.0, 1.0)
        self.adv_spec_draft_p_split.setSingleStep(0.05)
        self.adv_spec_draft_p_split.setValue(0.10)
        self._add_form_row(form, "投机拆分概率 (--spec-draft-p-split):", self.adv_spec_draft_p_split)

        self.adv_spec_type = QComboBox()
        self.adv_spec_type.addItems(["none", "draft-simple", "draft-eagle3", "draft-mtp", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache"])
        self._add_form_row(form, "投机类型 (--spec-type):", self.adv_spec_type)

        self.adv_spec_ngram_n = QSpinBox()
        self.adv_spec_ngram_n.setRange(1, 128)
        self.adv_spec_ngram_n.setValue(12)
        self._add_form_row(form, "Ngram大小N (--spec-ngram-simple-size-n):", self.adv_spec_ngram_n)

        self.adv_spec_ngram_m = QSpinBox()
        self.adv_spec_ngram_m.setRange(1, 256)
        self.adv_spec_ngram_m.setValue(48)
        self._add_form_row(form, "Ngram大小M (--spec-ngram-simple-size-m):", self.adv_spec_ngram_m)

        self.adv_spec_ngram_min_hits = QSpinBox()
        self.adv_spec_ngram_min_hits.setRange(1, 256)
        self._add_form_row(form, "Ngram最小命中 (--spec-ngram-simple-min-hits):", self.adv_spec_ngram_min_hits)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _create_server_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)

        self.adv_host = QLineEdit()
        self.adv_host.setText("127.0.0.1")
        self._add_form_row(form, "主机 (--host):", self.adv_host)

        self.adv_port = QSpinBox()
        self.adv_port.setRange(1, 65535)
        self.adv_port.setValue(8080)
        self._add_form_row(form, "端口 (--port):", self.adv_port)

        self.adv_reuse_port = QCheckBox()
        self._add_form_row(form, "复用端口 (--reuse-port):", self.adv_reuse_port)

        self.adv_api_key = QLineEdit()
        self.adv_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._add_form_row(form, "API密钥 (--api-key):", self.adv_api_key)

        self.adv_api_prefix = QLineEdit()
        self._add_form_row(form, "API前缀 (--api-prefix):", self.adv_api_prefix)

        self.adv_path = QLineEdit()
        self._add_form_row(form, "API路径 (--path):", self.adv_path)

        self.adv_webui = QCheckBox()
        self.adv_webui.setChecked(True)
        self._add_form_row(form, "WebUI (--webui):", self.adv_webui)

        webui_cfg_row, self.adv_webui_cfg = self._make_file_row("file", "JSON Files (*.json)")
        self._add_form_row(form, "WebUI配置 (--webui-config-file):", webui_cfg_row)

        self.adv_webui_mcp = QCheckBox()
        self._add_form_row(form, "WebUI MCP代理 (--webui-mcp-proxy):", self.adv_webui_mcp)

        self.adv_tools_list = QListWidget()
        self.adv_tools_list.setMaximumHeight(80)
        for tool in ["calculator", "retriever", "python", "bash", "curl"]:
            item = QListWidgetItem(tool)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.adv_tools_list.addItem(item)
        self._add_form_row(form, "工具 (--tools):", self.adv_tools_list)

        self.adv_cont_batching = QCheckBox()
        self.adv_cont_batching.setChecked(True)
        self._add_form_row(form, "连续批处理 (--cont-batching):", self.adv_cont_batching)

        self.adv_parallel = QSpinBox()
        self.adv_parallel.setRange(-1, 64)
        self.adv_parallel.setValue(-1)
        self._add_form_row(form, "并行槽位 (--parallel):", self.adv_parallel)

        self.adv_timeout = QSpinBox()
        self.adv_timeout.setRange(1, 99999)
        self.adv_timeout.setValue(600)
        self._add_form_row(form, "超时秒数 (--timeout):", self.adv_timeout)

        self.adv_slot_sim = QDoubleSpinBox()
        self.adv_slot_sim.setRange(0, 1.0)
        self.adv_slot_sim.setSingleStep(0.05)
        self.adv_slot_sim.setValue(0.1)
        self._add_form_row(form, "槽位提示相似度 (--slot-prompt-similarity):", self.adv_slot_sim)

        self.adv_slots = QCheckBox()
        self.adv_slots.setChecked(True)
        self._add_form_row(form, "槽位API (--slots):", self.adv_slots)

        self.adv_metrics = QCheckBox()
        self._add_form_row(form, "Prometheus指标 (--metrics):", self.adv_metrics)

        self.adv_props = QCheckBox()
        self._add_form_row(form, "属性端点 (--props):", self.adv_props)

        ssl_key_row, self.adv_ssl_key = self._make_file_row("file", "PEM Files (*.pem *.key)")
        self._add_form_row(form, "SSL密钥 (--ssl-key-file):", ssl_key_row)

        ssl_cert_row, self.adv_ssl_cert = self._make_file_row("file", "PEM Files (*.pem *.crt)")
        self._add_form_row(form, "SSL证书 (--ssl-cert-file):", ssl_cert_row)

        api_key_file_row, self.adv_api_key_file = self._make_file_row("file", "All Files (*)")
        self._add_form_row(form, "API密钥文件 (--api-key-file):", api_key_file_row)

        self.adv_webui_config = QLineEdit()
        self.adv_webui_config.setPlaceholderText(t("JSON格式的WebUI配置"))
        self._add_form_row(form, "WebUI配置JSON (--webui-config):", self.adv_webui_config)

        self.adv_slot_save_path = QLineEdit()
        self.adv_slot_save_path.setPlaceholderText(t("槽位KV缓存保存路径"))
        slot_save_row = QWidget()
        slot_save_lay = QHBoxLayout(slot_save_row)
        slot_save_lay.setContentsMargins(0, 0, 0, 0)
        slot_save_btn = QPushButton(t("浏览"))
        slot_save_btn.setFixedWidth(80)
        self._browse_btns.append(slot_save_btn)
        slot_save_btn.clicked.connect(lambda: self.adv_slot_save_path.setText(QFileDialog.getExistingDirectory(self, t("选择目录"))))
        slot_save_lay.addWidget(self.adv_slot_save_path, 1)
        slot_save_lay.addWidget(slot_save_btn)
        self._add_form_row(form, "槽位保存路径 (--slot-save-path):", slot_save_row)

        self.adv_media_path = QLineEdit()
        self.adv_media_path.setPlaceholderText(t("本地媒体文件目录"))
        media_row = QWidget()
        media_lay = QHBoxLayout(media_row)
        media_lay.setContentsMargins(0, 0, 0, 0)
        media_btn = QPushButton(t("浏览"))
        media_btn.setFixedWidth(80)
        self._browse_btns.append(media_btn)
        media_btn.clicked.connect(lambda: self.adv_media_path.setText(QFileDialog.getExistingDirectory(self, t("选择目录"))))
        media_lay.addWidget(self.adv_media_path, 1)
        media_lay.addWidget(media_btn)
        self._add_form_row(form, "媒体路径 (--media-path):", media_row)

        self.adv_lora_init_without_apply = QCheckBox()
        self._add_form_row(form, "LoRA延迟应用 (--lora-init-without-apply):", self.adv_lora_init_without_apply)

        self.adv_models_max = QSpinBox()
        self.adv_models_max.setRange(0, 64)
        self.adv_models_max.setValue(4)
        self._add_form_row(form, "最大模型数 (--models-max):", self.adv_models_max)

        self.adv_models_autoload = QCheckBox()
        self.adv_models_autoload.setChecked(True)
        self._add_form_row(form, "自动加载模型 (--models-autoload):", self.adv_models_autoload)

        self.adv_sleep_idle = QSpinBox()
        self.adv_sleep_idle.setRange(-1, 99999)
        self.adv_sleep_idle.setValue(-1)
        self._add_form_row(form, "空闲休眠秒 (--sleep-idle-seconds):", self.adv_sleep_idle)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _create_chat_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)

        self.adv_jinja = QCheckBox()
        self.adv_jinja.setChecked(True)
        self._add_form_row(form, "Jinja模板 (--jinja):", self.adv_jinja)

        self.adv_chat_template = QComboBox()
        self.adv_chat_template.addItems([""] + self._chat_templates)
        self.adv_chat_template.setEditable(True)
        self._add_form_row(form, "聊天模板 (--chat-template):", self.adv_chat_template)

        chat_file_row, self.adv_chat_template_file = self._make_file_row("file", "Jinja Files (*.jinja *.j2)")
        self._add_form_row(form, "模板文件 (--chat-template-file):", chat_file_row)

        kwargs_row, self.adv_chat_kwargs = self._make_text_row('{"key": "value"}')
        self._add_form_row(form, "模板参数 (--chat-template-kwargs):", kwargs_row)

        self.adv_skip_chat = QCheckBox()
        self._add_form_row(form, "跳过聊天解析 (--skip-chat-parsing):", self.adv_skip_chat)

        self.adv_prefill = QCheckBox()
        self.adv_prefill.setChecked(True)
        self._add_form_row(form, "预填充助手 (--prefill-assistant):", self.adv_prefill)

        self.adv_reasoning = QComboBox()
        self.adv_reasoning.addItems(["on", "off", "auto"])
        self.adv_reasoning.setCurrentText("auto")
        self._add_form_row(form, "推理模式 (--reasoning):", self.adv_reasoning)

        self.adv_reasoning_fmt = QComboBox()
        self.adv_reasoning_fmt.addItems(["none", "deepseek", "deepseek-legacy", "auto"])
        self.adv_reasoning_fmt.setCurrentText("auto")
        self._add_form_row(form, "推理格式 (--reasoning-format):", self.adv_reasoning_fmt)

        self.adv_reasoning_budget = QSpinBox()
        self.adv_reasoning_budget.setRange(-1, 99999)
        self.adv_reasoning_budget.setValue(-1)
        self._add_form_row(form, "推理预算 (--reasoning-budget):", self.adv_reasoning_budget)

        self.adv_reasoning_budget_msg = QLineEdit()
        self._add_form_row(form, "推理预算消息 (--reasoning-budget-message):", self.adv_reasoning_budget_msg)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def _create_advanced_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(8)

        self.adv_rope_scaling = QComboBox()
        self.adv_rope_scaling.addItems(["none", "linear", "yarn"])
        self._add_form_row(form, "RoPE缩放 (--rope-scaling):", self.adv_rope_scaling)

        self.adv_rope_scale = QDoubleSpinBox()
        self.adv_rope_scale.setRange(0, 100)
        self.adv_rope_scale.setSingleStep(0.1)
        self.adv_rope_scale.setValue(0)
        self._add_form_row(form, "RoPE缩放因子 (--rope-scale):", self.adv_rope_scale)

        self.adv_rope_freq_base = QDoubleSpinBox()
        self.adv_rope_freq_base.setRange(0, 999999)
        self.adv_rope_freq_base.setValue(0)
        self._add_form_row(form, "RoPE频率基 (--rope-freq-base):", self.adv_rope_freq_base)

        self.adv_rope_freq_scale = QDoubleSpinBox()
        self.adv_rope_freq_scale.setRange(0, 10)
        self.adv_rope_freq_scale.setSingleStep(0.1)
        self.adv_rope_freq_scale.setValue(0)
        self._add_form_row(form, "RoPE频率缩放 (--rope-freq-scale):", self.adv_rope_freq_scale)

        self.adv_yarn_orig_ctx = QSpinBox()
        self.adv_yarn_orig_ctx.setRange(0, 999999)
        self.adv_yarn_orig_ctx.setValue(0)
        self._add_form_row(form, "YaRN原始上下文 (--yarn-orig-ctx):", self.adv_yarn_orig_ctx)

        self.adv_yarn_ext = QDoubleSpinBox()
        self.adv_yarn_ext.setRange(-1.0, 1.0)
        self.adv_yarn_ext.setSingleStep(0.1)
        self.adv_yarn_ext.setValue(-1.0)
        self._add_form_row(form, "YaRN扩展因子 (--yarn-ext-factor):", self.adv_yarn_ext)

        self.adv_yarn_attn = QDoubleSpinBox()
        self.adv_yarn_attn.setRange(-1.0, 2.0)
        self.adv_yarn_attn.setSingleStep(0.1)
        self.adv_yarn_attn.setValue(-1.0)
        self._add_form_row(form, "YaRN注意力因子 (--yarn-attn-factor):", self.adv_yarn_attn)

        self.adv_yarn_beta_slow = QDoubleSpinBox()
        self.adv_yarn_beta_slow.setRange(-1.0, 2.0)
        self.adv_yarn_beta_slow.setSingleStep(0.1)
        self.adv_yarn_beta_slow.setValue(-1.0)
        self._add_form_row(form, "YaRN Beta慢 (--yarn-beta-slow):", self.adv_yarn_beta_slow)

        self.adv_yarn_beta_fast = QDoubleSpinBox()
        self.adv_yarn_beta_fast.setRange(-1.0, 2.0)
        self.adv_yarn_beta_fast.setSingleStep(0.1)
        self.adv_yarn_beta_fast.setValue(-1.0)
        self._add_form_row(form, "YaRN Beta快 (--yarn-beta-fast):", self.adv_yarn_beta_fast)

        self.adv_embedding = QCheckBox()
        self._add_form_row(form, "嵌入模式 (--embedding):", self.adv_embedding)

        self.adv_rerank = QCheckBox()
        self._add_form_row(form, "重排模式 (--rerank):", self.adv_rerank)

        self.adv_pooling = QComboBox()
        self.adv_pooling.addItems(["none", "mean", "cls", "last", "rank"])
        self._add_form_row(form, "池化类型 (--pooling):", self.adv_pooling)

        self.adv_verbose = QCheckBox()
        self._add_form_row(form, "详细输出 (--verbose):", self.adv_verbose)

        self.adv_log_verbosity = QComboBox()
        self.adv_log_verbosity.addItems(["0 (none)", "1 (error)", "2 (warning)", "3 (info)", "4 (debug)"])
        self.adv_log_verbosity.setCurrentIndex(3)
        self._add_form_row(form, "日志详细度 (--log-verbosity):", self.adv_log_verbosity)

        self.adv_log_colors = QComboBox()
        self.adv_log_colors.addItems(["on", "off", "auto"])
        self.adv_log_colors.setCurrentText("auto")
        self._add_form_row(form, "日志颜色 (--log-colors):", self.adv_log_colors)

        log_file_row, self.adv_log_file = self._make_file_row("file", "Text Files (*.txt *.log)")
        self._add_form_row(form, "日志文件 (--log-file):", log_file_row)

        self.adv_log_prefix = QCheckBox()
        self._add_form_row(form, "日志前缀 (--log-prefix):", self.adv_log_prefix)

        self.adv_log_timestamps = QCheckBox()
        self._add_form_row(form, "日志时间戳 (--log-timestamps):", self.adv_log_timestamps)

        self.adv_offline = QCheckBox()
        self._add_form_row(form, "离线模式 (--offline):", self.adv_offline)

        self.adv_special = QCheckBox()
        self._add_form_row(form, "特殊Token (--special):", self.adv_special)

        self.adv_reverse_prompt = QLineEdit()
        self._add_form_row(form, "反向提示词 (--reverse-prompt):", self.adv_reverse_prompt)

        self.adv_spm_infill = QCheckBox()
        self._add_form_row(form, "SPM填充 (--spm-infill):", self.adv_spm_infill)

        extra_row, self.adv_extra_args = self._make_text_row(t("额外参数，每行一个"))
        self._add_form_row(form, "额外参数:", extra_row)

        scroll.setWidget(content)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(scroll)
        return tab

    def get_values(self):
        v = {}
        v["model"] = self.adv_model.text()
        v["mmproj"] = self.adv_mmproj.text()
        v["lora"] = [self.adv_lora_list.item(i).text() for i in range(self.adv_lora_list.count())]
        v["lora_scaled"] = [s.strip() for s in self.adv_lora_scaled.text().split(",") if s.strip()]
        v["control_vector"] = [self.adv_cv_list.item(i).text() for i in range(self.adv_cv_list.count())]
        v["control_vector_scaled"] = [s.strip() for s in self.adv_cv_scaled.text().split(",") if s.strip()]
        v["control_vector_layer_range"] = self.adv_cv_layer_range.text()
        v["mmproj_auto"] = self.adv_mmproj_auto.isChecked()
        v["mmproj_offload"] = self.adv_mmproj_offload.isChecked()
        v["image_min_tokens"] = self.adv_image_min_tokens.value()
        v["image_max_tokens"] = self.adv_image_max_tokens.value()
        v["alias"] = self.adv_alias.text()
        v["tags"] = self.adv_tags.text()
        v["ctx_size"] = self.adv_ctx_size.value()
        v["batch_size"] = self.adv_batch_size.value()
        v["ubatch_size"] = self.adv_ubatch_size.value()
        v["n_predict"] = self.adv_n_predict.value()
        v["keep"] = self.adv_keep.value()
        v["cache_prompt"] = self.adv_cache_prompt.isChecked()
        v["cache_reuse"] = self.adv_cache_reuse.value()
        v["cache_ram"] = self.adv_cache_ram.value()
        v["context_shift"] = self.adv_context_shift.isChecked()
        v["kv_offload"] = self.adv_kv_offload.isChecked()
        v["kv_unified"] = self.adv_kv_unified.isChecked()
        v["cache_type_k"] = self.adv_cache_type_k.currentText()
        v["cache_type_v"] = self.adv_cache_type_v.currentText()
        v["swa_full"] = self.adv_swa_full.isChecked()
        v["escape"] = self.adv_escape.isChecked()
        v["defrag_thold"] = self.adv_defrag_thold.value()
        v["cache_idle_slots"] = self.adv_cache_idle_slots.isChecked()
        v["ctx_checkpoints"] = self.adv_ctx_checkpoints.value()
        v["checkpoint_every_n_tokens"] = self.adv_checkpoint_every.value()
        v["temp"] = self.adv_temp.value()
        v["top_k"] = self.adv_top_k.value()
        v["top_p"] = self.adv_top_p.value()
        v["min_p"] = self.adv_min_p.value()
        v["typical_p"] = self.adv_typical_p.value()
        v["top_n_sigma"] = self.adv_top_n_sigma.value()
        v["xtc_probability"] = self.adv_xtc_prob.value()
        v["xtc_threshold"] = self.adv_xtc_thresh.value()
        v["repeat_penalty"] = self.adv_repeat_penalty.value()
        v["presence_penalty"] = self.adv_presence_penalty.value()
        v["frequency_penalty"] = self.adv_freq_penalty.value()
        v["dry_multiplier"] = self.adv_dry_mult.value()
        v["dry_base"] = self.adv_dry_base.value()
        v["dry_allowed_length"] = self.adv_dry_len.value()
        v["dry_penalty_last_n"] = self.adv_dry_penalty_last_n.value()
        v["adaptive_target"] = self.adv_adaptive_target.value()
        v["adaptive_decay"] = self.adv_adaptive_decay.value()
        v["repeat_last_n"] = self.adv_repeat_last_n.value()
        v["seed"] = self.adv_seed.value()
        v["mirostat"] = self.adv_mirostat.currentIndex()
        v["mirostat_lr"] = self.adv_mirostat_lr.value()
        v["mirostat_ent"] = self.adv_mirostat_ent.value()
        v["dynatemp_range"] = self.adv_dynatemp_range.value()
        v["dynatemp_exp"] = self.adv_dynatemp_exp.value()
        v["grammar"] = self.adv_grammar.text()
        v["json_schema"] = self.adv_json_schema.toPlainText()
        v["ignore_eos"] = self.adv_ignore_eos.isChecked()
        v["backend_sampling"] = self.adv_backend_sampling.isChecked()
        v["samplers"] = self.adv_samplers.text()
        v["sampler_seq"] = self.adv_sampler_seq.text()
        v["logit_bias"] = self.adv_logit_bias.text()
        v["grammar_file"] = self.adv_grammar_file.text()
        v["json_schema_file"] = self.adv_json_schema_file.text()
        v["n_gpu_layers"] = self.adv_ngl.currentText()
        v["device"] = self.adv_device.text()
        v["split_mode"] = self.adv_split_mode.currentText()
        v["tensor_split"] = self.adv_tensor_split.text()
        v["main_gpu"] = self.adv_main_gpu.value()
        v["threads"] = self.adv_threads.value()
        v["threads_batch"] = self.adv_threads_batch.value()
        v["threads_http"] = self.adv_threads_http.value()
        v["prio"] = self.adv_prio.currentText()
        v["flash_attn"] = self.adv_flash_attn.currentText()
        v["mmap"] = self.adv_mmap.isChecked()
        v["mlock"] = self.adv_mlock.isChecked()
        v["no_host"] = self.adv_no_host.isChecked()
        v["repack"] = self.adv_repack.isChecked()
        v["fit"] = self.adv_fit.currentText()
        v["fit_target"] = self.adv_fit_target.value()
        v["fit_ctx"] = self.adv_fit_ctx.value()
        v["check_tensors"] = self.adv_check_tensors.isChecked()
        v["n_cpu_moe"] = self.adv_n_cpu_moe.value()
        v["direct_io"] = self.adv_direct_io.isChecked()
        v["draft_model"] = self.adv_draft_model.text()
        v["threads_draft"] = self.adv_threads_draft.value()
        v["threads_batch_draft"] = self.adv_threads_batch_draft.value()
        v["ctx_size_draft"] = self.adv_ctx_size_draft.value()
        v["device_draft"] = self.adv_device_draft.text()
        v["n_gpu_layers_draft"] = self.adv_n_gpu_layers_draft.currentText()
        v["cpu_moe_draft"] = self.adv_cpu_moe_draft.isChecked()
        v["n_cpu_moe_draft"] = self.adv_n_cpu_moe_draft.value()
        v["cache_type_k_draft"] = self.adv_cache_type_k_draft.currentText()
        v["cache_type_v_draft"] = self.adv_cache_type_v_draft.currentText()
        v["draft_max"] = self.adv_draft_max.value()
        v["draft_min"] = self.adv_draft_min.value()
        v["draft_p_min"] = self.adv_draft_p_min.value()
        v["spec_draft_p_split"] = self.adv_spec_draft_p_split.value()
        v["spec_type"] = self.adv_spec_type.currentText()
        v["spec_ngram_size_n"] = self.adv_spec_ngram_n.value()
        v["spec_ngram_size_m"] = self.adv_spec_ngram_m.value()
        v["spec_ngram_min_hits"] = self.adv_spec_ngram_min_hits.value()
        v["numa"] = self.adv_numa.currentText()
        v["warmup"] = self.adv_warmup.isChecked()
        v["perf"] = self.adv_perf.isChecked()
        v["host"] = self.adv_host.text()
        v["port"] = self.adv_port.value()
        v["reuse_port"] = self.adv_reuse_port.isChecked()
        v["api_key"] = self.adv_api_key.text()
        v["api_prefix"] = self.adv_api_prefix.text()
        v["path"] = self.adv_path.text()
        v["webui"] = self.adv_webui.isChecked()
        v["webui_config_file"] = self.adv_webui_cfg.text()
        v["webui_mcp_proxy"] = self.adv_webui_mcp.isChecked()
        v["tools"] = [self.adv_tools_list.item(i).text() for i in range(self.adv_tools_list.count()) if self.adv_tools_list.item(i).checkState() == Qt.CheckState.Checked]
        v["cont_batching"] = self.adv_cont_batching.isChecked()
        v["parallel"] = self.adv_parallel.value()
        v["timeout"] = self.adv_timeout.value()
        v["slot_prompt_similarity"] = self.adv_slot_sim.value()
        v["slots"] = self.adv_slots.isChecked()
        v["metrics"] = self.adv_metrics.isChecked()
        v["props"] = self.adv_props.isChecked()
        v["ssl_key_file"] = self.adv_ssl_key.text()
        v["ssl_cert_file"] = self.adv_ssl_cert.text()
        v["api_key_file"] = self.adv_api_key_file.text()
        v["webui_config"] = self.adv_webui_config.text()
        v["slot_save_path"] = self.adv_slot_save_path.text()
        v["media_path"] = self.adv_media_path.text()
        v["lora_init_without_apply"] = self.adv_lora_init_without_apply.isChecked()
        v["models_max"] = self.adv_models_max.value()
        v["models_autoload"] = self.adv_models_autoload.isChecked()
        v["sleep_idle_seconds"] = self.adv_sleep_idle.value()
        v["jinja"] = self.adv_jinja.isChecked()
        v["chat_template"] = self.adv_chat_template.currentText()
        v["chat_template_file"] = self.adv_chat_template_file.text()
        v["chat_template_kwargs"] = self.adv_chat_kwargs.toPlainText()
        v["skip_chat_parsing"] = self.adv_skip_chat.isChecked()
        v["prefill_assistant"] = self.adv_prefill.isChecked()
        v["reasoning"] = self.adv_reasoning.currentText()
        v["reasoning_format"] = self.adv_reasoning_fmt.currentText()
        v["reasoning_budget"] = self.adv_reasoning_budget.value()
        v["reasoning_budget_message"] = self.adv_reasoning_budget_msg.text()
        v["special"] = self.adv_special.isChecked()
        v["reverse_prompt"] = self.adv_reverse_prompt.text()
        v["spm_infill"] = self.adv_spm_infill.isChecked()
        v["rope_scaling"] = self.adv_rope_scaling.currentText()
        v["rope_scale"] = self.adv_rope_scale.value()
        v["rope_freq_base"] = self.adv_rope_freq_base.value()
        v["rope_freq_scale"] = self.adv_rope_freq_scale.value()
        v["yarn_orig_ctx"] = self.adv_yarn_orig_ctx.value()
        v["yarn_ext_factor"] = self.adv_yarn_ext.value()
        v["yarn_attn_factor"] = self.adv_yarn_attn.value()
        v["yarn_beta_slow"] = self.adv_yarn_beta_slow.value()
        v["yarn_beta_fast"] = self.adv_yarn_beta_fast.value()
        v["embedding"] = self.adv_embedding.isChecked()
        v["rerank"] = self.adv_rerank.isChecked()
        v["pooling"] = self.adv_pooling.currentText()
        v["cpu_moe"] = self.adv_cpu_moe.isChecked()
        v["op_offload"] = self.adv_op_offload.isChecked()
        v["verbose"] = self.adv_verbose.isChecked()
        v["log_verbosity"] = self.adv_log_verbosity.currentIndex()
        v["log_colors"] = self.adv_log_colors.currentText()
        v["log_file"] = self.adv_log_file.text()
        v["log_prefix"] = self.adv_log_prefix.isChecked()
        v["log_timestamps"] = self.adv_log_timestamps.isChecked()
        v["offline"] = self.adv_offline.isChecked()
        v["extra_args"] = self.adv_extra_args.toPlainText()
        return v

    def set_values(self, values):
        values = dict(values)
        if "model" in values:
            self.adv_model.setText(values["model"])
        if "mmproj" in values:
            self.adv_mmproj.setText(values["mmproj"])
        if "lora" in values:
            self.adv_lora_list.clear()
            for item in values["lora"]:
                self.adv_lora_list.addItem(item)
        if "lora_scaled" in values:
            self.adv_lora_scaled.setText(", ".join(str(x) for x in values["lora_scaled"]))
        if "control_vector" in values:
            self.adv_cv_list.clear()
            for item in values["control_vector"]:
                self.adv_cv_list.addItem(item)
        if "control_vector_scaled" in values:
            self.adv_cv_scaled.setText(", ".join(str(x) for x in values["control_vector_scaled"]))
        if "control_vector_layer_range" in values:
            self.adv_cv_layer_range.setText(values["control_vector_layer_range"])
        if "mmproj_auto" in values:
            self.adv_mmproj_auto.setChecked(values["mmproj_auto"])
        if "mmproj_offload" in values:
            self.adv_mmproj_offload.setChecked(values["mmproj_offload"])
        if "image_min_tokens" in values:
            self.adv_image_min_tokens.setValue(values["image_min_tokens"])
        if "image_max_tokens" in values:
            self.adv_image_max_tokens.setValue(values["image_max_tokens"])
        if "alias" in values:
            self.adv_alias.setText(values["alias"])
        if "tags" in values:
            self.adv_tags.setText(values["tags"])
        if "ctx_size" in values:
            self.adv_ctx_size.setValue(values["ctx_size"])
        if "batch_size" in values:
            self.adv_batch_size.setValue(values["batch_size"])
        if "ubatch_size" in values:
            self.adv_ubatch_size.setValue(values["ubatch_size"])
        if "n_predict" in values:
            self.adv_n_predict.setValue(values["n_predict"])
        if "keep" in values:
            self.adv_keep.setValue(values["keep"])
        if "cache_prompt" in values:
            self.adv_cache_prompt.setChecked(values["cache_prompt"])
        if "cache_reuse" in values:
            self.adv_cache_reuse.setValue(values["cache_reuse"])
        if "cache_ram" in values:
            self.adv_cache_ram.setValue(values["cache_ram"])
        if "context_shift" in values:
            self.adv_context_shift.setChecked(values["context_shift"])
        if "kv_offload" in values:
            self.adv_kv_offload.setChecked(values["kv_offload"])
        if "kv_unified" in values:
            self.adv_kv_unified.setChecked(values["kv_unified"])
        if "cache_type_k" in values:
            self.adv_cache_type_k.setCurrentText(values["cache_type_k"])
        if "cache_type_v" in values:
            self.adv_cache_type_v.setCurrentText(values["cache_type_v"])
        if "swa_full" in values:
            self.adv_swa_full.setChecked(values["swa_full"])
        if "escape" in values:
            self.adv_escape.setChecked(values["escape"])
        if "defrag_thold" in values:
            self.adv_defrag_thold.setValue(values["defrag_thold"])
        if "cache_idle_slots" in values:
            self.adv_cache_idle_slots.setChecked(values["cache_idle_slots"])
        if "ctx_checkpoints" in values:
            self.adv_ctx_checkpoints.setValue(values["ctx_checkpoints"])
        if "checkpoint_every_n_tokens" in values:
            self.adv_checkpoint_every.setValue(values["checkpoint_every_n_tokens"])
        if "temp" in values:
            self.adv_temp.setValue(values["temp"])
        if "top_k" in values:
            self.adv_top_k.setValue(values["top_k"])
        if "top_p" in values:
            self.adv_top_p.setValue(values["top_p"])
        if "min_p" in values:
            self.adv_min_p.setValue(values["min_p"])
        if "typical_p" in values:
            self.adv_typical_p.setValue(values["typical_p"])
        if "top_n_sigma" in values:
            self.adv_top_n_sigma.setValue(values["top_n_sigma"])
        if "xtc_probability" in values:
            self.adv_xtc_prob.setValue(values["xtc_probability"])
        if "xtc_threshold" in values:
            self.adv_xtc_thresh.setValue(values["xtc_threshold"])
        if "repeat_penalty" in values:
            self.adv_repeat_penalty.setValue(values["repeat_penalty"])
        if "presence_penalty" in values:
            self.adv_presence_penalty.setValue(values["presence_penalty"])
        if "frequency_penalty" in values:
            self.adv_freq_penalty.setValue(values["frequency_penalty"])
        if "dry_multiplier" in values:
            self.adv_dry_mult.setValue(values["dry_multiplier"])
        if "dry_base" in values:
            self.adv_dry_base.setValue(values["dry_base"])
        if "dry_allowed_length" in values:
            self.adv_dry_len.setValue(values["dry_allowed_length"])
        if "dry_penalty_last_n" in values:
            self.adv_dry_penalty_last_n.setValue(values["dry_penalty_last_n"])
        if "adaptive_target" in values:
            self.adv_adaptive_target.setValue(values["adaptive_target"])
        if "adaptive_decay" in values:
            self.adv_adaptive_decay.setValue(values["adaptive_decay"])
        if "repeat_last_n" in values:
            self.adv_repeat_last_n.setValue(values["repeat_last_n"])
        if "seed" in values:
            self.adv_seed.setValue(values["seed"])
        if "mirostat" in values:
            self.adv_mirostat.setCurrentIndex(values["mirostat"])
        if "mirostat_lr" in values:
            self.adv_mirostat_lr.setValue(values["mirostat_lr"])
        if "mirostat_ent" in values:
            self.adv_mirostat_ent.setValue(values["mirostat_ent"])
        if "dynatemp_range" in values:
            self.adv_dynatemp_range.setValue(values["dynatemp_range"])
        if "dynatemp_exp" in values:
            self.adv_dynatemp_exp.setValue(values["dynatemp_exp"])
        if "grammar" in values:
            self.adv_grammar.setText(values["grammar"])
        if "json_schema" in values:
            self.adv_json_schema.setPlainText(values["json_schema"])
        if "ignore_eos" in values:
            self.adv_ignore_eos.setChecked(values["ignore_eos"])
        if "backend_sampling" in values:
            self.adv_backend_sampling.setChecked(values["backend_sampling"])
        if "samplers" in values:
            self.adv_samplers.setText(values["samplers"])
        if "sampler_seq" in values:
            self.adv_sampler_seq.setText(values["sampler_seq"])
        if "logit_bias" in values:
            self.adv_logit_bias.setText(values["logit_bias"])
        if "grammar_file" in values:
            self.adv_grammar_file.setText(values["grammar_file"])
        if "json_schema_file" in values:
            self.adv_json_schema_file.setText(values["json_schema_file"])
        if "n_gpu_layers" in values:
            val = str(values["n_gpu_layers"])
            idx = self.adv_ngl.findText(val)
            self.adv_ngl_spin.blockSignals(True)
            if idx >= 0:
                self.adv_ngl.setCurrentIndex(idx)
            else:
                self.adv_ngl.setEditText(val)
            try:
                self.adv_ngl_spin.setValue(int(val))
            except (ValueError, TypeError):
                self.adv_ngl_spin.setValue(0)
            self.adv_ngl_spin.blockSignals(False)
        if "device" in values:
            self.adv_device.setText(values["device"])
        if "split_mode" in values:
            self.adv_split_mode.setCurrentText(values["split_mode"])
        if "tensor_split" in values:
            self.adv_tensor_split.setText(values["tensor_split"])
        if "main_gpu" in values:
            self.adv_main_gpu.setValue(values["main_gpu"])
        if "threads" in values:
            self.adv_threads.setValue(values["threads"])
        if "threads_batch" in values:
            self.adv_threads_batch.setValue(values["threads_batch"])
        if "threads_http" in values:
            self.adv_threads_http.setValue(values["threads_http"])
        if "prio" in values:
            self.adv_prio.setCurrentText(values["prio"])
        if "flash_attn" in values:
            self.adv_flash_attn.setCurrentText(values["flash_attn"])
        if "mmap" in values:
            self.adv_mmap.setChecked(values["mmap"])
        if "mlock" in values:
            self.adv_mlock.setChecked(values["mlock"])
        if "no_host" in values:
            self.adv_no_host.setChecked(values["no_host"])
        if "repack" in values:
            self.adv_repack.setChecked(values["repack"])
        if "fit" in values:
            self.adv_fit.setCurrentText(values["fit"])
        if "fit_target" in values:
            self.adv_fit_target.setValue(values["fit_target"])
        if "fit_ctx" in values:
            self.adv_fit_ctx.setValue(values["fit_ctx"])
        if "check_tensors" in values:
            self.adv_check_tensors.setChecked(values["check_tensors"])
        if "n_cpu_moe" in values:
            self.adv_n_cpu_moe.setValue(values["n_cpu_moe"])
        if "direct_io" in values:
            self.adv_direct_io.setChecked(values["direct_io"])
        if "draft_model" in values:
            self.adv_draft_model.setText(values["draft_model"])
        if "threads_draft" in values:
            self.adv_threads_draft.setValue(values["threads_draft"])
        if "threads_batch_draft" in values:
            self.adv_threads_batch_draft.setValue(values["threads_batch_draft"])
        if "ctx_size_draft" in values:
            self.adv_ctx_size_draft.setValue(values["ctx_size_draft"])
        if "device_draft" in values:
            self.adv_device_draft.setText(values["device_draft"])
        if "n_gpu_layers_draft" in values:
            val = str(values["n_gpu_layers_draft"])
            idx = self.adv_n_gpu_layers_draft.findText(val)
            if idx >= 0:
                self.adv_n_gpu_layers_draft.setCurrentIndex(idx)
            else:
                self.adv_n_gpu_layers_draft.setEditText(val)
        if "cpu_moe_draft" in values:
            self.adv_cpu_moe_draft.setChecked(values["cpu_moe_draft"])
        if "n_cpu_moe_draft" in values:
            self.adv_n_cpu_moe_draft.setValue(values["n_cpu_moe_draft"])
        if "cache_type_k_draft" in values:
            self.adv_cache_type_k_draft.setCurrentText(values["cache_type_k_draft"])
        if "cache_type_v_draft" in values:
            self.adv_cache_type_v_draft.setCurrentText(values["cache_type_v_draft"])
        if "draft_max" in values:
            self.adv_draft_max.setValue(values["draft_max"])
        if "draft_min" in values:
            self.adv_draft_min.setValue(values["draft_min"])
        if "draft_p_min" in values:
            self.adv_draft_p_min.setValue(values["draft_p_min"])
        if "spec_draft_p_split" in values:
            self.adv_spec_draft_p_split.setValue(values["spec_draft_p_split"])
        if "spec_type" in values:
            self.adv_spec_type.setCurrentText(values["spec_type"])
        if "spec_ngram_size_n" in values:
            self.adv_spec_ngram_n.setValue(values["spec_ngram_size_n"])
        if "spec_ngram_size_m" in values:
            self.adv_spec_ngram_m.setValue(values["spec_ngram_size_m"])
        if "spec_ngram_min_hits" in values:
            self.adv_spec_ngram_min_hits.setValue(values["spec_ngram_min_hits"])
        if "numa" in values:
            self.adv_numa.setCurrentText(values["numa"])
        if "warmup" in values:
            self.adv_warmup.setChecked(values["warmup"])
        if "perf" in values:
            self.adv_perf.setChecked(values["perf"])
        if "host" in values:
            self.adv_host.setText(values["host"])
        if "port" in values:
            self.adv_port.setValue(values["port"])
        if "reuse_port" in values:
            self.adv_reuse_port.setChecked(values["reuse_port"])
        if "api_key" in values:
            self.adv_api_key.setText(values["api_key"])
        if "api_prefix" in values:
            self.adv_api_prefix.setText(values["api_prefix"])
        if "path" in values:
            self.adv_path.setText(values["path"])
        if "webui" in values:
            self.adv_webui.setChecked(values["webui"])
        if "webui_config_file" in values:
            self.adv_webui_cfg.setText(values["webui_config_file"])
        if "webui_mcp_proxy" in values:
            self.adv_webui_mcp.setChecked(values["webui_mcp_proxy"])
        if "tools" in values:
            for i in range(self.adv_tools_list.count()):
                item = self.adv_tools_list.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.text() in values["tools"] else Qt.CheckState.Unchecked)
        if "cont_batching" in values:
            self.adv_cont_batching.setChecked(values["cont_batching"])
        if "parallel" in values:
            self.adv_parallel.setValue(values["parallel"])
        if "timeout" in values:
            self.adv_timeout.setValue(values["timeout"])
        if "slot_prompt_similarity" in values:
            self.adv_slot_sim.setValue(values["slot_prompt_similarity"])
        if "slots" in values:
            self.adv_slots.setChecked(values["slots"])
        if "metrics" in values:
            self.adv_metrics.setChecked(values["metrics"])
        if "props" in values:
            self.adv_props.setChecked(values["props"])
        if "ssl_key_file" in values:
            self.adv_ssl_key.setText(values["ssl_key_file"])
        if "ssl_cert_file" in values:
            self.adv_ssl_cert.setText(values["ssl_cert_file"])
        if "api_key_file" in values:
            self.adv_api_key_file.setText(values["api_key_file"])
        if "webui_config" in values:
            self.adv_webui_config.setText(values["webui_config"])
        if "slot_save_path" in values:
            self.adv_slot_save_path.setText(values["slot_save_path"])
        if "media_path" in values:
            self.adv_media_path.setText(values["media_path"])
        if "lora_init_without_apply" in values:
            self.adv_lora_init_without_apply.setChecked(values["lora_init_without_apply"])
        if "models_max" in values:
            self.adv_models_max.setValue(values["models_max"])
        if "models_autoload" in values:
            self.adv_models_autoload.setChecked(values["models_autoload"])
        if "sleep_idle_seconds" in values:
            self.adv_sleep_idle.setValue(values["sleep_idle_seconds"])
        if "jinja" in values:
            self.adv_jinja.setChecked(values["jinja"])
        if "chat_template" in values:
            idx = self.adv_chat_template.findText(values["chat_template"])
            if idx >= 0:
                self.adv_chat_template.setCurrentIndex(idx)
            else:
                self.adv_chat_template.setEditText(values["chat_template"])
        if "chat_template_file" in values:
            self.adv_chat_template_file.setText(values["chat_template_file"])
        if "chat_template_kwargs" in values:
            self.adv_chat_kwargs.setPlainText(values["chat_template_kwargs"])
        if "skip_chat_parsing" in values:
            self.adv_skip_chat.setChecked(values["skip_chat_parsing"])
        if "prefill_assistant" in values:
            self.adv_prefill.setChecked(values["prefill_assistant"])
        if "reasoning" in values:
            self.adv_reasoning.setCurrentText(values["reasoning"])
        if "reasoning_format" in values:
            self.adv_reasoning_fmt.setCurrentText(values["reasoning_format"])
        if "reasoning_budget" in values:
            self.adv_reasoning_budget.setValue(values["reasoning_budget"])
        if "reasoning_budget_message" in values:
            self.adv_reasoning_budget_msg.setText(values["reasoning_budget_message"])
        if "special" in values:
            self.adv_special.setChecked(values["special"])
        if "reverse_prompt" in values:
            self.adv_reverse_prompt.setText(values["reverse_prompt"])
        if "spm_infill" in values:
            self.adv_spm_infill.setChecked(values["spm_infill"])
        if "rope_scaling" in values:
            self.adv_rope_scaling.setCurrentText(values["rope_scaling"])
        if "rope_scale" in values:
            self.adv_rope_scale.setValue(values["rope_scale"])
        if "rope_freq_base" in values:
            self.adv_rope_freq_base.setValue(values["rope_freq_base"])
        if "rope_freq_scale" in values:
            self.adv_rope_freq_scale.setValue(values["rope_freq_scale"])
        if "yarn_orig_ctx" in values:
            self.adv_yarn_orig_ctx.setValue(values["yarn_orig_ctx"])
        if "yarn_ext_factor" in values:
            self.adv_yarn_ext.setValue(values["yarn_ext_factor"])
        if "yarn_attn_factor" in values:
            self.adv_yarn_attn.setValue(values["yarn_attn_factor"])
        if "yarn_beta_slow" in values:
            self.adv_yarn_beta_slow.setValue(values["yarn_beta_slow"])
        if "yarn_beta_fast" in values:
            self.adv_yarn_beta_fast.setValue(values["yarn_beta_fast"])
        if "embedding" in values:
            self.adv_embedding.setChecked(values["embedding"])
        if "rerank" in values:
            self.adv_rerank.setChecked(values["rerank"])
        if "pooling" in values:
            self.adv_pooling.setCurrentText(values["pooling"])
        if "cpu_moe" in values:
            self.adv_cpu_moe.setChecked(values["cpu_moe"])
        if "op_offload" in values:
            self.adv_op_offload.setChecked(values["op_offload"])
        if "verbose" in values:
            self.adv_verbose.setChecked(values["verbose"])
        if "log_verbosity" in values:
            self.adv_log_verbosity.setCurrentIndex(values["log_verbosity"])
        if "log_colors" in values:
            self.adv_log_colors.setCurrentText(values["log_colors"])
        if "log_file" in values:
            self.adv_log_file.setText(values["log_file"])
        if "log_prefix" in values:
            self.adv_log_prefix.setChecked(values["log_prefix"])
        if "log_timestamps" in values:
            self.adv_log_timestamps.setChecked(values["log_timestamps"])
        if "offline" in values:
            self.adv_offline.setChecked(values["offline"])
        if "extra_args" in values:
            self.adv_extra_args.setPlainText(values["extra_args"])

    def reset(self):
        self.set_values(dict(self._defaults))

    def retranslate_ui(self):
        # Tab titles
        self.tabs.setTabText(0, t("模型"))
        self.tabs.setTabText(1, t("上下文"))
        self.tabs.setTabText(2, t("采样"))
        self.tabs.setTabText(3, t("GPU/性能"))
        self.tabs.setTabText(4, t("服务"))
        self.tabs.setTabText(5, t("聊天/推理"))
        self.tabs.setTabText(6, t("高级"))

        # Form labels
        for key, lbl in self._form_labels.items():
            lbl.setText(t(key))

        # Section labels
        for key, lbl in self._section_labels:
            lbl.setText(f"<b>{t(key)}</b>")

        # Mirostat combo
        idx = self.adv_mirostat.currentIndex()
        self.adv_mirostat.clear()
        self.adv_mirostat.addItems([t("禁用") + " (0)", "Mirostat (1)", "Mirostat 2.0 (2)"])
        self.adv_mirostat.setCurrentIndex(idx)

        # Placeholders
        self.adv_model.setPlaceholderText(t("选择或输入模型文件路径"))
        self.adv_mmproj.setPlaceholderText(t("选择或输入视觉投影模型路径"))
        self.adv_alias.setPlaceholderText(t("模型的自定义名称"))
        self.adv_tags.setPlaceholderText(t("逗号分隔的标签列表"))
        self.adv_sampler_seq.setPlaceholderText(t("简化采样器序列"))
        self.adv_webui_config.setPlaceholderText(t("JSON格式的WebUI配置"))
        self.adv_slot_save_path.setPlaceholderText(t("槽位KV缓存保存路径"))
        self.adv_media_path.setPlaceholderText(t("本地媒体文件目录"))
        self.adv_extra_args.setPlaceholderText(t("额外参数，每行一个"))

        # Buttons
        for btn in self._browse_btns:
            btn.setText(t("浏览"))
        if hasattr(self, '_add_rm_btns'):
            for btn in self._add_rm_btns:
                if btn.text() in ("添加", "Add"):
                    btn.setText(t("添加"))
                elif btn.text() in ("移除", "Remove"):
                    btn.setText(t("移除"))
