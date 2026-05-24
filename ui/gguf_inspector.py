import csv
import html as _html
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QTableView,
    QFileDialog, QMessageBox, QTextEdit, QAbstractItemView, QApplication,
    QLineEdit, QComboBox, QProgressBar,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QAbstractTableModel, QModelIndex,
    QSortFilterProxyModel,
)
from PyQt6.QtGui import QFont, QColor

from core.i18n import t
from gguf.parser import parse_gguf
from gguf.models import GGUFInfo
from gguf.ggml_types import GGML_TYPES


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class GGUFParseWorker(QThread):
    progress = pyqtSignal(str)
    parsed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self._path = path
        self._cancelled = False

    def run(self):
        try:
            self.progress.emit(t("正在读取文件头..."))
            info = parse_gguf(self._path, progress_callback=self.progress.emit)
            if not self._cancelled:
                self.parsed.emit(info)
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(str(e))

    def cancel(self):
        self._cancelled = True


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_parse_cache: dict[tuple, GGUFInfo] = {}
_CACHE_MAX = 10


def _cache_key(path, file_size, mtime_ns):
    return (str(path), file_size, mtime_ns)


# ---------------------------------------------------------------------------
# Metadata table model
# ---------------------------------------------------------------------------

class MetadataTableModel(QAbstractTableModel):
    HEADERS = [t("Key"), t("Type"), t("Preview")]

    def __init__(self):
        super().__init__()
        self._data = []  # list of (key, type_str, preview, full_value_str)

    def load(self, metadata: dict):
        self.beginResetModel()
        self._data = []
        for key, value in sorted(metadata.items()):
            vtype, preview, full_str = self._format_value(value)
            self._data.append((key, vtype, preview, full_str))
        self.endResetModel()

    def _format_value(self, value):
        if isinstance(value, bool):
            return "bool", str(value), str(value)
        elif isinstance(value, int):
            return "int", str(value), str(value)
        elif isinstance(value, float):
            return "float", f"{value:.6g}", str(value)
        elif isinstance(value, str):
            preview = value[:120] + "..." if len(value) > 120 else value
            return "string", preview, value
        elif isinstance(value, list):
            if not value:
                return "array[]", "[]", "[]"
            elem_type = type(value[0]).__name__
            if isinstance(value[0], str):
                preview = f'array[string], len={len(value)}, preview={value[:3]}'
            elif isinstance(value[0], bool):
                preview = f'array[bool], len={len(value)}, preview={value[:5]}'
            elif isinstance(value[0], (int, float)):
                preview = f'array[{elem_type}], len={len(value)}, preview={value[:5]}'
            else:
                preview = f'array[{elem_type}], len={len(value)}'
            full_str = json.dumps(value, ensure_ascii=False, default=str)
            return f"array[{elem_type}]", preview, full_str
        else:
            return type(value).__name__, str(value)[:120], str(value)

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        key, vtype, preview, _full_str = self._data[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return [key, vtype, preview][col]

        if role == Qt.ItemDataRole.ToolTipRole:
            return preview

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                font = QFont()
                font.setBold(True)
                return font

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def get_row_json(self, row):
        key, vtype, _preview, full_str = self._data[row]
        return {"key": key, "type": vtype, "value": full_str}

    def get_all_json(self):
        return [self.get_row_json(i) for i in range(len(self._data))]


# ---------------------------------------------------------------------------
# Tensor table model
# ---------------------------------------------------------------------------

class TensorTableModel(QAbstractTableModel):
    HEADERS = [
        t("Name"), t("Shape"), t("Type"), t("Params"),
        t("Est. Size"), t("Offset"), t("Abs Offset"),
        t("Layer"), t("Module")
    ]

    def __init__(self):
        super().__init__()
        self._data = []  # list of GGUFTensorInfo

    def load(self, tensors):
        self.beginResetModel()
        self._data = list(tensors)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return 9

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        t_obj = self._data[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return t_obj.name
            elif col == 1:
                return "x".join(str(d) for d in t_obj.dims)
            elif col == 2:
                return t_obj.type_name
            elif col == 3:
                return self._fmt_params(t_obj.n_params)
            elif col == 4:
                return self._fmt_bytes(t_obj.estimated_nbytes)
            elif col == 5:
                return str(t_obj.offset)
            elif col == 6:
                return str(t_obj.absolute_offset)
            elif col == 7:
                return str(t_obj.layer) if t_obj.layer is not None else ""
            elif col == 8:
                return t_obj.module or ""

        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"Name: {t_obj.name}\n"
                f"Shape: {'x'.join(str(d) for d in t_obj.dims)}\n"
                f"Type: {t_obj.type_name} (id={t_obj.type_id})\n"
                f"Params: {t_obj.n_params:,}\n"
                f"Offset: {t_obj.offset}\n"
                f"Abs Offset: {t_obj.absolute_offset}"
            )

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    @staticmethod
    def _fmt_params(n):
        if n >= 1e12:
            return f"{n/1e12:.2f}T"
        if n >= 1e9:
            return f"{n/1e9:.2f}B"
        if n >= 1e6:
            return f"{n/1e6:.1f}M"
        if n >= 1e3:
            return f"{n/1e3:.1f}K"
        return str(n)

    @staticmethod
    def _fmt_bytes(n):
        if n is None:
            return "N/A"
        if n >= 1e12:
            return f"{n/1e12:.2f} TB"
        if n >= 1e9:
            return f"{n/1e9:.2f} GB"
        if n >= 1e6:
            return f"{n/1e6:.1f} MB"
        return f"{n/1e3:.0f} KB"

    def get_tensor_csv_rows(self):
        rows = []
        for t_obj in self._data:
            rows.append({
                "name": t_obj.name,
                "shape": "x".join(str(d) for d in t_obj.dims),
                "type": t_obj.type_name,
                "params": t_obj.n_params,
                "estimated_bytes": t_obj.estimated_nbytes or 0,
                "offset": t_obj.offset,
                "absolute_offset": t_obj.absolute_offset,
                "layer": t_obj.layer if t_obj.layer is not None else "",
                "module": t_obj.module or "",
            })
        return rows


# ---------------------------------------------------------------------------
# Tensor filter proxy (combined text + type + layer)
# ---------------------------------------------------------------------------

class TensorFilterProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._text = ""
        self._type = ""
        self._layer = ""

    def set_filters(self, text="", type_name="", layer=""):
        self._text = text.lower()
        self._type = type_name
        self._layer = layer
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        index_name = model.index(source_row, 0, source_parent)
        index_type = model.index(source_row, 2, source_parent)
        index_layer = model.index(source_row, 7, source_parent)

        name = model.data(index_name, Qt.ItemDataRole.DisplayRole) or ""
        type_name = model.data(index_type, Qt.ItemDataRole.DisplayRole) or ""
        layer = model.data(index_layer, Qt.ItemDataRole.DisplayRole) or ""

        if self._text and self._text not in name.lower():
            return False
        if self._type and type_name != self._type:
            return False
        if self._layer and layer != self._layer:
            return False
        return True


# ---------------------------------------------------------------------------
# Inspector dialog
# ---------------------------------------------------------------------------

class GGUFInspectorDialog(QDialog):
    def __init__(self, file_path, launcher_params=None, parent=None):
        super().__init__(parent)
        self._path = file_path
        self._info: GGUFInfo | None = None
        self._launcher_params = launcher_params or {}
        self._worker: GGUFParseWorker | None = None
        self._metadata_model = MetadataTableModel()
        self._tensor_model = TensorTableModel()
        self._proxy_metadata = QSortFilterProxyModel()
        self._proxy_tensor = TensorFilterProxyModel()

        # Build file list for model selector
        self._file_options = []  # list of (label, path)
        mmproj_path = self._launcher_params.get("mmproj", "")
        if mmproj_path and Path(mmproj_path).exists():
            self._file_options.append((Path(file_path).name, file_path))
            self._file_options.append((Path(mmproj_path).name, mmproj_path))
        else:
            self._file_options.append((Path(file_path).name, file_path))

        self._init_ui()
        self.setWindowTitle(f"GGUF Inspector — {Path(file_path).name}")
        self.setMinimumSize(900, 650)
        self.resize(1000, 700)

        # Try cache
        self._try_cache_or_parse()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Top bar
        top = QHBoxLayout()

        # Model selector
        self._model_selector = QComboBox()
        self._model_selector.setMinimumWidth(200)
        for label, _path in self._file_options:
            self._model_selector.addItem(label)
        self._model_selector.currentIndexChanged.connect(self._on_model_selected)
        top.addWidget(self._model_selector)

        top.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #666; font-size:11px;")
        top.addWidget(self._lbl_status)

        self._btn_reparse = QPushButton(t("🔄 重新解析"))
        self._btn_reparse.setToolTip(t("重新解析当前 GGUF 文件"))
        self._btn_reparse.clicked.connect(self._start_parse)
        top.addWidget(self._btn_reparse)

        self._btn_export = QPushButton(t("📥 导出"))
        self._btn_export.setToolTip(t("导出解析结果"))
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self._export_menu)
        top.addWidget(self._btn_export)

        root.addLayout(top)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setMaximum(0)
        self._progress.setMaximumHeight(4)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_overview_tab(), t("📋 概览"))
        self._tabs.addTab(self._create_stats_tab(), t("📊 统计"))
        self._tabs.addTab(self._create_metadata_tab(), t("📝 元数据"))
        self._tabs.addTab(self._create_tensors_tab(), t("🧊 张量"))
        self._tabs.addTab(self._create_tokenizer_tab(), t("🔤 分词器"))
        self._tabs.addTab(self._create_filename_tab(), t("📄 文件名"))
        self._tabs.addTab(self._create_diagnostics_tab(), t("🔍 诊断"))
        root.addWidget(self._tabs, 1)

    # --- Overview tab ---

    def _create_overview_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        self._overview_text = QTextEdit()
        self._overview_text.setReadOnly(True)
        self._overview_text.setStyleSheet(
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; "
            "font-family: Consolas, monospace; font-size: 12px; "
            "border: 1px solid #313244; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self._overview_text)
        return w

    # --- Stats tab ---

    def _create_stats_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        self._stats_text = QTextEdit()
        self._stats_text.setReadOnly(True)
        self._stats_text.setStyleSheet(
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; "
            "font-family: Consolas, monospace; font-size: 12px; "
            "border: 1px solid #313244; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self._stats_text)
        return w

    # --- Metadata tab ---

    def _create_metadata_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Search
        search_layout = QHBoxLayout()
        self._meta_search = QLineEdit()
        self._meta_search.setPlaceholderText(t("搜索 key 或 value..."))
        self._meta_search.setClearButtonEnabled(True)
        self._meta_search.textChanged.connect(self._filter_metadata)
        search_layout.addWidget(QLabel(t("🔍")))
        search_layout.addWidget(self._meta_search, 1)

        self._meta_group = QComboBox()
        self._meta_group.addItems([
            t("全部"), "general.*", "tokenizer.*",
            t("架构字段"), t("其他")
        ])
        self._meta_group.currentTextChanged.connect(self._filter_metadata)
        search_layout.addWidget(self._meta_group)
        layout.addLayout(search_layout)

        self._proxy_metadata.setSourceModel(self._metadata_model)
        self._proxy_metadata.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy_metadata.setFilterKeyColumn(-1)

        self._meta_table = QTableView()
        self._meta_table.setModel(self._proxy_metadata)
        self._meta_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._meta_table.setAlternatingRowColors(True)
        self._meta_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._meta_table.customContextMenuRequested.connect(self._meta_context_menu)
        self._meta_table.horizontalHeader().setStretchLastSection(True)
        self._meta_table.verticalHeader().setVisible(False)
        layout.addWidget(self._meta_table, 1)

        return w

    # --- Tensors tab ---

    def _create_tensors_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Filters
        filter_layout = QHBoxLayout()
        self._tensor_search = QLineEdit()
        self._tensor_search.setPlaceholderText(t("搜索张量名称..."))
        self._tensor_search.setClearButtonEnabled(True)
        self._tensor_search.textChanged.connect(self._filter_tensors)
        filter_layout.addWidget(QLabel(t("🔍")))
        filter_layout.addWidget(self._tensor_search, 1)

        self._tensor_type_filter = QComboBox()
        self._tensor_type_filter.addItem(t("全部类型"))
        self._tensor_type_filter.currentTextChanged.connect(self._filter_tensors)
        filter_layout.addWidget(self._tensor_type_filter)

        self._tensor_layer_filter = QComboBox()
        self._tensor_layer_filter.addItem(t("全部层"))
        self._tensor_layer_filter.currentTextChanged.connect(self._filter_tensors)
        filter_layout.addWidget(self._tensor_layer_filter)
        layout.addLayout(filter_layout)

        self._proxy_tensor.setSourceModel(self._tensor_model)
        self._proxy_tensor.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy_tensor.setFilterKeyColumn(0)

        self._tensor_table = QTableView()
        self._tensor_table.setModel(self._proxy_tensor)
        self._tensor_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tensor_table.setAlternatingRowColors(True)
        self._tensor_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tensor_table.customContextMenuRequested.connect(self._tensor_context_menu)
        self._tensor_table.horizontalHeader().setStretchLastSection(True)
        self._tensor_table.verticalHeader().setVisible(False)
        layout.addWidget(self._tensor_table, 1)

        # Stats
        self._tensor_stats = QLabel("")
        self._tensor_stats.setStyleSheet("color: #555; font-size: 11px; padding: 4px;")
        layout.addWidget(self._tensor_stats)

        return w

    # --- Tokenizer tab ---

    def _create_tokenizer_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        self._tokenizer_text = QTextEdit()
        self._tokenizer_text.setReadOnly(True)
        self._tokenizer_text.setStyleSheet(
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; "
            "font-family: Consolas, monospace; font-size: 12px; "
            "border: 1px solid #313244; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self._tokenizer_text, 1)

        return w

    # --- Filename tab ---

    def _create_filename_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        self._filename_text = QTextEdit()
        self._filename_text.setReadOnly(True)
        self._filename_text.setStyleSheet(
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; "
            "font-family: Consolas, monospace; font-size: 12px; "
            "border: 1px solid #313244; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self._filename_text)
        return w

    # --- Diagnostics tab ---

    def _create_diagnostics_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        self._diag_table = QTableWidget()
        self._diag_table.setColumnCount(3)
        self._diag_table.setHorizontalHeaderLabels([
            t("级别"), t("检查项"), t("信息")
        ])
        self._diag_table.horizontalHeader().setStretchLastSection(True)
        self._diag_table.verticalHeader().setVisible(False)
        self._diag_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._diag_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self._diag_table, 1)

        return w

    # ------------------------------------------------------------------
    # Parse logic
    # ------------------------------------------------------------------

    def _try_cache_or_parse(self):
        path = self._file_options[self._model_selector.currentIndex()][1]
        self._path = path
        try:
            st = os.stat(path)
            key = _cache_key(path, st.st_size, int(st.st_mtime_ns))
            if key in _parse_cache:
                self._on_parsed(_parse_cache[key])
                return
        except OSError:
            pass
        self._start_parse()

    def _on_model_selected(self, index):
        if index < 0 or index >= len(self._file_options):
            return
        path = self._file_options[index][1]
        if path == self._path and self._info is not None:
            return
        self.setWindowTitle(f"GGUF Inspector — {Path(path).name}")
        self._try_cache_or_parse()

    def _start_parse(self):
        if self._worker and self._worker.isRunning():
            return
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._btn_reparse.setEnabled(False)
        self._lbl_status.setText(t("正在解析..."))
        self._worker = GGUFParseWorker(self._path)
        self._worker.progress.connect(self._on_progress)
        self._worker.parsed.connect(self._on_parsed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, msg):
        self._lbl_status.setText(msg)

    def _on_parsed(self, info: GGUFInfo):
        self._info = info
        self._progress.setVisible(False)
        self._btn_reparse.setEnabled(True)
        self._btn_export.setEnabled(True)
        self._lbl_status.setText(
            f"{info.header.tensor_count} tensors · "
            f"{len(info.metadata)} metadata · "
            f"{info.file_size / (1024**3):.2f} GB"
        )

        # Cache
        try:
            st = os.stat(self._path)
            key = _cache_key(self._path, st.st_size, int(st.st_mtime_ns))
            if len(_parse_cache) >= _CACHE_MAX:
                _parse_cache.pop(next(iter(_parse_cache)))
            _parse_cache[key] = info
        except OSError:
            pass

        self._populate_all_tabs()

    def _on_failed(self, msg):
        self._progress.setVisible(False)
        self._btn_reparse.setEnabled(True)
        self._lbl_status.setText(t("解析失败"))
        QMessageBox.critical(self, t("解析错误"), msg)

    # ------------------------------------------------------------------
    # Populate tabs
    # ------------------------------------------------------------------

    def _populate_all_tabs(self):
        if not self._info:
            return
        self._populate_overview()
        self._populate_stats()
        self._populate_metadata()
        self._populate_tensors()
        self._populate_tokenizer()
        self._populate_filename()
        self._populate_diagnostics()

    def _populate_overview(self):
        info = self._info
        m = info.metadata
        arch = m.get("general.architecture", "")

        def _meta(key, default="—"):
            v = m.get(key, default)
            if isinstance(v, (int, float)):
                return str(v)
            if isinstance(v, bool):
                return t("是") if v else t("否")
            if isinstance(v, list):
                return f"array[{len(v)}]"
            return str(v) if v else default

        def _badge(val, color="#7aa2f7"):
            return f'<span style="background:{color};color:#1e1e2e;padding:2px 8px;border-radius:3px;font-weight:bold;">{val}</span>'

        def _section(title, icon=""):
            label = f"{icon} {title}" if icon else title
            return (
                f'<div style="background:#313244;color:#cdd6f4;padding:6px 12px;'
                f'border-radius:4px;font-weight:bold;font-size:13px;margin-top:12px;margin-bottom:4px;">'
                f'{label}</div>'
            )

        def _kv_table(rows):
            """rows: list of (label, value, [highlight])"""
            html = '<table style="border-collapse:collapse;width:100%;">'
            for i, (label, value, *rest) in enumerate(rows):
                highlight = rest[0] if rest else False
                bg = "#262637" if i % 2 == 0 else "#1e1e2e"
                val_style = "color:#a6e3a1;font-weight:bold;" if highlight else "color:#cdd6f4;"
                html += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:3px 12px;color:#9399b2;width:200px;white-space:nowrap;">{label}</td>'
                    f'<td style="padding:3px 12px;{val_style}">{value}</td>'
                    f'</tr>'
                )
            html += '</table>'
            return html

        parts = []

        # File Info
        parts.append(_section(t("文件信息"), "\U0001F4C1"))
        try:
            mtime = datetime.fromtimestamp(os.stat(info.path).st_mtime).isoformat()
        except OSError:
            mtime = "—"
        parts.append(_kv_table([
            (t("文件名"), Path(info.path).name),
            (t("路径"), f'<span style="color:#9399b2;font-size:11px;">{info.path}</span>'),
            (t("文件大小"), _badge(f"{info.file_size / (1024**3):.2f} GB")),
            (t("修改时间"), mtime),
            (t("GGUF 版本"), str(info.header.version)),
            (t("张量数量"), _badge(f"{info.header.tensor_count:,}")),
            (t("元数据 KV 数量"), str(info.header.metadata_kv_count)),
            (t("张量数据偏移"), f"{info.tensor_data_offset:,}"),
            (t("对齐"), str(info.alignment)),
        ]))

        # Model Identity
        parts.append(_section(t("模型标识"), "\U0001F916"))
        id_rows = []
        for key in ["general.name", "general.architecture", "general.basename",
                     "general.size_label", "general.version", "general.author",
                     "general.organization", "general.license", "general.repo_url"]:
            val = _meta(key)
            if val != "—":
                id_rows.append((key, _badge(val) if key == "general.name" else val))
        if id_rows:
            parts.append(_kv_table(id_rows))

        # Architecture
        if arch:
            parts.append(_section(f"{t('架构')} ({arch})", "⚙️"))
            arch_keys = [
                f"{arch}.context_length", f"{arch}.embedding_length",
                f"{arch}.block_count", f"{arch}.feed_forward_length",
                f"{arch}.attention.head_count", f"{arch}.attention.head_count_kv",
                f"{arch}.rope.dimension_count", f"{arch}.rope.freq_base",
                f"{arch}.rope.scaling.type", f"{arch}.rope.scaling.factor",
                f"{arch}.rope.scaling.original_context_length",
                f"{arch}.expert_count", f"{arch}.expert_used_count",
            ]
            arch_rows = []
            for key in arch_keys:
                val = _meta(key)
                if val != "—":
                    short = key.replace(f"{arch}.", "")
                    arch_rows.append((short, val))
            if arch_rows:
                parts.append(_kv_table(arch_rows))

        # Quantization Summary
        parts.append(_section(t("量化摘要"), "\U0001F4A0"))
        q_rows = [
            ("file_type", _meta("general.file_type")),
            ("quantization_version", _meta("general.quantization_version")),
            (t("主导类型"), _badge(info.stats.dominant_type_name, "#f9e2af")),
        ]
        for tid, count in sorted(info.stats.tensor_type_counts.items()):
            type_name = GGML_TYPES.get(tid, f"UNKNOWN_{tid}")
            est = info.stats.tensor_type_sizes.get(tid, 0)
            q_rows.append((type_name, f"{count} {t('张量')}  ~{est/(1024**2):.1f} MB"))
        parts.append(_kv_table(q_rows))

        # Tokenizer Summary
        parts.append(_section(t("分词器摘要"), "\U0001F524"))
        tokens = m.get("tokenizer.ggml.tokens")
        vocab_size = f"{len(tokens):,}" if isinstance(tokens, list) else "—"
        has_template = "tokenizer.chat_template" in m
        has_hf = "tokenizer.huggingface.json" in m
        t_rows = [
            (t("模型"), _meta("tokenizer.ggml.model")),
            (t("词表大小"), _badge(vocab_size)),
            ("BOS token id", _meta("tokenizer.ggml.bos_token_id")),
            ("EOS token id", _meta("tokenizer.ggml.eos_token_id")),
            ("UNK token id", _meta("tokenizer.ggml.unknown_token_id")),
            ("SEP token id", _meta("tokenizer.ggml.separator_token_id")),
            ("PAD token id", _meta("tokenizer.ggml.padding_token_id")),
            (t("聊天模板"), _badge(t("是"), "#a6e3a1") if has_template else _badge(t("否"), "#f38ba8")),
            (t("HF 分词器 JSON"), _badge(t("是"), "#a6e3a1") if has_hf else _badge(t("否"), "#f38ba8")),
        ]
        parts.append(_kv_table(t_rows))

        html = (
            '<div style="padding:4px;font-family:Consolas,monospace;font-size:12px;">'
            + "".join(parts)
            + '</div>'
        )
        self._overview_text.setHtml(html)

    def _populate_stats(self):
        info = self._info
        tensors = info.tensors
        stats = info.stats

        def _fmt_bytes(n):
            if n is None:
                return "N/A"
            if n >= 1e12:
                return f"{n/1e12:.2f} TB"
            if n >= 1e9:
                return f"{n/1e9:.2f} GB"
            if n >= 1e6:
                return f"{n/1e6:.1f} MB"
            return f"{n/1e3:.0f} KB"

        def _fmt_params(n):
            if n >= 1e12:
                return f"{n/1e12:.2f}T"
            if n >= 1e9:
                return f"{n/1e9:.2f}B"
            if n >= 1e6:
                return f"{n/1e6:.1f}M"
            if n >= 1e3:
                return f"{n/1e3:.1f}K"
            return str(n)

        def _badge(val, color="#7aa2f7"):
            return f'<span style="background:{color};color:#1e1e2e;padding:2px 8px;border-radius:3px;font-weight:bold;">{val}</span>'

        def _section(title, icon=""):
            label = f"{icon} {title}" if icon else title
            return (
                f'<div style="background:#313244;color:#cdd6f4;padding:6px 12px;'
                f'border-radius:4px;font-weight:bold;font-size:13px;margin-top:12px;margin-bottom:4px;">'
                f'{label}</div>'
            )

        def _bar(value, max_value, width=20, fill="█", empty="░"):
            """Unicode bar chart."""
            if max_value <= 0:
                return ""
            ratio = min(value / max_value, 1.0)
            filled = int(ratio * width)
            return f'<span style="color:#7aa2f7;">{fill * filled}</span><span style="color:#45475a;">{empty * (width - filled)}</span>'

        def _kv_table(rows):
            html = '<table style="border-collapse:collapse;width:100%;">'
            for i, (label, value, *rest) in enumerate(rows):
                highlight = rest[0] if rest else False
                bg = "#262637" if i % 2 == 0 else "#1e1e2e"
                val_style = "color:#a6e3a1;font-weight:bold;" if highlight else "color:#cdd6f4;"
                html += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:3px 12px;color:#9399b2;width:220px;white-space:nowrap;">{label}</td>'
                    f'<td style="padding:3px 12px;{val_style}">{value}</td>'
                    f'</tr>'
                )
            html += '</table>'
            return html

        def _data_table(headers, rows):
            """Styled data table with header."""
            html = '<table style="border-collapse:collapse;width:100%;font-size:11px;">'
            # Header
            html += '<tr style="background:#45475a;color:#cdd6f4;">'
            for h in headers:
                html += f'<td style="padding:4px 10px;font-weight:bold;white-space:nowrap;">{h}</td>'
            html += '</tr>'
            for i, row in enumerate(rows):
                bg = "#262637" if i % 2 == 0 else "#1e1e2e"
                html += f'<tr style="background:{bg};">'
                for cell in row:
                    html += f'<td style="padding:3px 10px;color:#cdd6f4;white-space:nowrap;">{cell}</td>'
                html += '</tr>'
            html += '</table>'
            return html

        parts = []

        # File Size Breakdown
        meta_overhead = info.tensor_data_offset
        tensor_data = info.file_size - info.tensor_data_offset
        pct = (meta_overhead / info.file_size * 100) if info.file_size > 0 else 0
        parts.append(_section(t("文件大小分析"), "\U0001F4BE"))
        parts.append(_kv_table([
            (t("总文件大小"), _badge(_fmt_bytes(info.file_size))),
            (t("元数据开销"), f"{_fmt_bytes(meta_overhead)} ({pct:.1f}%)"),
            (t("张量数据"), _badge(_fmt_bytes(tensor_data), "#a6e3a1")),
        ]))

        # Memory Footprint
        uncompressed = stats.total_params * 4
        estimated = stats.total_estimated_bytes
        ratio = uncompressed / estimated if estimated > 0 else 0
        parts.append(_section(t("内存占用"), "\U0001F9E0"))
        parts.append(_kv_table([
            (t("磁盘估算"), _badge(_fmt_bytes(estimated))),
            (t("未压缩 (F32)"), _fmt_bytes(uncompressed)),
            (t("压缩比"), _badge(f"{ratio:.1f}x", "#f9e2af")),
        ]))

        # Quantization Distribution
        sorted_types = sorted(stats.tensor_type_counts.items(), key=lambda x: -x[1])
        if sorted_types:
            max_count = max(c for _, c in sorted_types)
            parts.append(_section(t("量化分布"), "\U0001F4A0"))
            q_rows = []
            for tid, count in sorted_types:
                type_name = GGML_TYPES.get(tid, f"UNKNOWN_{tid}")
                est = stats.tensor_type_sizes.get(tid, 0)
                bar = _bar(count, max_count, width=25)
                q_rows.append([
                    f'<span style="font-weight:bold;">{type_name}</span>',
                    f'{bar}',
                    f'{count}',
                    f'~{_fmt_bytes(est)}',
                ])
            parts.append(_data_table([t("Type"), t("分布"), t("张量"), t("Est. Size")], q_rows))

        # Parameter Concentration
        sorted_tensors = sorted(tensors, key=lambda t: -t.n_params)
        total = stats.total_params
        if total > 0:
            parts.append(_section(t("参数集中度"), "\U0001F4CA"))
            c_rows = []
            for n in [10, 20, 50, 100]:
                cum = sum(t_obj.n_params for t_obj in sorted_tensors[:min(n, len(sorted_tensors))])
                pct_val = cum / total * 100
                bar = _bar(pct_val, 100, width=30)
                c_rows.append([
                    f'{t("Top {n}", n=n)}',
                    _badge(_fmt_params(cum), "#f9e2af"),
                    f'{bar}',
                    f'{pct_val:.1f}%',
                ])
            parts.append(_data_table([t("张量"), t("参数"), t("覆盖率"), ""], c_rows))

        # Layer-wise Breakdown
        layer_data: dict[int, dict] = {}
        non_block_count = 0
        non_block_params = 0
        non_block_bytes = 0
        for t_obj in tensors:
            if t_obj.layer is not None:
                if t_obj.layer not in layer_data:
                    layer_data[t_obj.layer] = {"count": 0, "params": 0, "bytes": 0}
                layer_data[t_obj.layer]["count"] += 1
                layer_data[t_obj.layer]["params"] += t_obj.n_params
                layer_data[t_obj.layer]["bytes"] += t_obj.estimated_nbytes or 0
            else:
                non_block_count += 1
                non_block_params += t_obj.n_params
                non_block_bytes += t_obj.estimated_nbytes or 0

        if layer_data:
            max_layer_params = max(d["params"] for d in layer_data.values())
            parts.append(_section(t("逐层分析"), "\U0001F9E9"))
            l_rows = []
            for layer_idx in sorted(layer_data.keys()):
                d = layer_data[layer_idx]
                bar = _bar(d["params"], max_layer_params, width=20)
                l_rows.append([
                    f'<span style="font-weight:bold;">{layer_idx}</span>',
                    f'{d["count"]}',
                    _fmt_params(d["params"]),
                    f'{bar}',
                    _fmt_bytes(d["bytes"]),
                ])
            if non_block_count > 0:
                l_rows.append([
                    f'<span style="color:#9399b2;">{t("其他")}</span>',
                    str(non_block_count),
                    _fmt_params(non_block_params),
                    '',
                    _fmt_bytes(non_block_bytes),
                ])
            parts.append(_data_table([t("Layer"), t("张量"), t("Params"), t("相对大小"), t("Est. Size")], l_rows))

        # Module Breakdown
        module_data: dict[str, dict] = {}
        other_count = 0
        other_params = 0
        other_bytes = 0
        for t_obj in tensors:
            mod = t_obj.module or "other"
            if mod == "other":
                other_count += 1
                other_params += t_obj.n_params
                other_bytes += t_obj.estimated_nbytes or 0
            else:
                if mod not in module_data:
                    module_data[mod] = {"count": 0, "params": 0, "bytes": 0}
                module_data[mod]["count"] += 1
                module_data[mod]["params"] += t_obj.n_params
                module_data[mod]["bytes"] += t_obj.estimated_nbytes or 0

        if module_data:
            max_mod_params = max(d["params"] for d in module_data.values())
            parts.append(_section(t("模块分析"), "\U0001F4E6"))
            m_rows = []
            for mod_name in sorted(module_data.keys(), key=lambda k: -module_data[k]["params"]):
                d = module_data[mod_name]
                bar = _bar(d["params"], max_mod_params, width=20)
                m_rows.append([
                    f'<span style="font-weight:bold;">{mod_name}</span>',
                    f'{d["count"]}',
                    _fmt_params(d["params"]),
                    f'{bar}',
                    _fmt_bytes(d["bytes"]),
                ])
            if other_count > 0:
                m_rows.append([
                    f'<span style="color:#9399b2;">{t("其他")}</span>',
                    str(other_count),
                    _fmt_params(other_params),
                    '',
                    _fmt_bytes(other_bytes),
                ])
            parts.append(_data_table([t("Module"), t("张量"), t("Params"), t("相对大小"), t("Est. Size")], m_rows))

        # Top 20 Largest Tensors
        top_tensors = sorted(tensors, key=lambda t: -(t.estimated_nbytes or 0))[:20]
        if top_tensors:
            max_top_bytes = top_tensors[0].estimated_nbytes or 1
            parts.append(_section(t("最大的 20 个张量"), "\U0001F3AF"))
            t_rows = []
            for t_obj in top_tensors:
                shape = " × ".join(str(d) for d in t_obj.dims)
                name_short = t_obj.name if len(t_obj.name) <= 40 else "…" + t_obj.name[-37:]
                bar = _bar(t_obj.estimated_nbytes or 0, max_top_bytes, width=15)
                t_rows.append([
                    f'<span style="font-size:10px;">{name_short}</span>',
                    f'<span style="color:#9399b2;">{shape}</span>',
                    f'{t_obj.type_name}',
                    f'{_fmt_params(t_obj.n_params)}',
                    f'{bar}',
                    _fmt_bytes(t_obj.estimated_nbytes),
                ])
            parts.append(_data_table([t("Name"), t("Shape"), t("Type"), t("Params"), "", t("Est. Size")], t_rows))

        # Tensor Shape Stats
        rank_counts: dict[int, int] = {}
        for t_obj in tensors:
            rank = len(t_obj.dims)
            rank_counts[rank] = rank_counts.get(rank, 0) + 1

        if rank_counts:
            max_rank = max(rank_counts.values())
            parts.append(_section(t("张量形状统计"), "\U0001F538"))
            s_rows = []
            for rank in sorted(rank_counts.keys()):
                count = rank_counts[rank]
                pct_val = count / len(tensors) * 100 if tensors else 0
                bar = _bar(count, max_rank, width=20)
                s_rows.append([
                    f'{rank}D',
                    f'{bar}',
                    f'{count:,}',
                    f'{pct_val:.1f}%',
                ])
            parts.append(_data_table([t("排名"), "", t("数量"), t("百分比")], s_rows))

        html = (
            '<div style="padding:4px;font-family:Consolas,monospace;font-size:12px;">'
            + "".join(parts)
            + '</div>'
        )
        self._stats_text.setHtml(html)

    def _populate_metadata(self):
        self._metadata_model.load(self._info.metadata)
        self._meta_table.setModel(self._proxy_metadata)
        self._meta_table.resizeColumnsToContents()

    def _populate_tensors(self):
        info = self._info
        self._tensor_model.load(info.tensors)
        self._tensor_table.setModel(self._proxy_tensor)
        self._tensor_table.resizeColumnsToContents()

        # Populate type filter
        self._tensor_type_filter.blockSignals(True)
        self._tensor_type_filter.clear()
        self._tensor_type_filter.addItem(t("全部类型"))
        types_seen = set()
        for t_obj in info.tensors:
            if t_obj.type_name not in types_seen:
                self._tensor_type_filter.addItem(t_obj.type_name)
                types_seen.add(t_obj.type_name)
        self._tensor_type_filter.blockSignals(False)

        # Populate layer filter
        self._tensor_layer_filter.blockSignals(True)
        self._tensor_layer_filter.clear()
        self._tensor_layer_filter.addItem(t("全部层"))
        layers = sorted(set(t_obj.layer for t_obj in info.tensors if t_obj.layer is not None))
        for l in layers:
            self._tensor_layer_filter.addItem(str(l))
        self._tensor_layer_filter.blockSignals(False)

        # Stats
        s = info.stats
        est_str = f"{s.total_estimated_bytes/(1024**3):.2f} GB" if s.total_estimated_bytes else "N/A"
        self._tensor_stats.setText(
            t("共 {count} 个张量 · 参数量: {params} · 估算体积: {size}").format(
                count=len(info.tensors),
                params=TensorTableModel._fmt_params(s.total_params),
                size=est_str
            )
        )

    def _populate_tokenizer(self):
        m = self._info.metadata

        def _badge(val, color="#7aa2f7"):
            return f'<span style="background:{color};color:#1e1e2e;padding:2px 8px;border-radius:3px;font-weight:bold;">{val}</span>'

        def _section(title, icon=""):
            label = f"{icon} {title}" if icon else title
            return (
                f'<div style="background:#313244;color:#cdd6f4;padding:6px 12px;'
                f'border-radius:4px;font-weight:bold;font-size:13px;margin-top:12px;margin-bottom:4px;">'
                f'{label}</div>'
            )

        def _kv_table(rows):
            html = '<table style="border-collapse:collapse;width:100%;">'
            for i, (label, value, *rest) in enumerate(rows):
                highlight = rest[0] if rest else False
                bg = "#262637" if i % 2 == 0 else "#1e1e2e"
                val_style = "color:#a6e3a1;font-weight:bold;" if highlight else "color:#cdd6f4;"
                html += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:3px 12px;color:#9399b2;width:200px;white-space:nowrap;">{label}</td>'
                    f'<td style="padding:3px 12px;{val_style}">{value}</td>'
                    f'</tr>'
                )
            html += '</table>'
            return html

        parts = []

        # Tokenizer Info
        parts.append(_section(t("分词器信息"), "\U0001F524"))
        tokens = m.get("tokenizer.ggml.tokens")
        merges = m.get("tokenizer.ggml.merges")
        has_hf = "tokenizer.huggingface.json" in m
        has_template = "tokenizer.chat_template" in m
        parts.append(_kv_table([
            (t("模型"), _badge(m.get("tokenizer.ggml.model", "—"))),
            (t("词表大小"), _badge(f"{len(tokens):,}" if isinstance(tokens, list) else "—")),
            (t("合并规则数"), f"{len(merges):,}" if isinstance(merges, list) else "—"),
            ("BOS token id", str(m.get("tokenizer.ggml.bos_token_id", "—"))),
            ("EOS token id", str(m.get("tokenizer.ggml.eos_token_id", "—"))),
            ("UNK token id", str(m.get("tokenizer.ggml.unknown_token_id", "—"))),
            ("SEP token id", str(m.get("tokenizer.ggml.separator_token_id", "—"))),
            ("PAD token id", str(m.get("tokenizer.ggml.padding_token_id", "—"))),
            (t("HF 分词器 JSON"), _badge(t("是"), "#a6e3a1") if has_hf else _badge(t("否"), "#f38ba8")),
            (t("聊天模板"), _badge(t("是"), "#a6e3a1") if has_template else _badge(t("否"), "#f38ba8")),
        ]))

        # Chat Template
        if has_template:
            template_str = str(m["tokenizer.chat_template"])
            # Escape HTML and wrap in a styled code block
            escaped = _html.escape(template_str)
            parts.append(_section(t("聊天模板"), "\U0001F4AC"))
            parts.append(
                f'<div style="background:#181825;border:1px solid #313244;border-radius:4px;'
                f'padding:10px;font-family:Consolas,monospace;font-size:11px;color:#cdd6f4;'
                f'white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto;">'
                f'{escaped}</div>'
            )

        html = (
            '<div style="padding:4px;font-family:Consolas,monospace;font-size:12px;">'
            + "".join(parts)
            + '</div>'
        )
        self._tokenizer_text.setHtml(html)

    def _populate_filename(self):
        info = self._info
        fn = info.filename_info
        m = info.metadata

        def _badge(val, color="#7aa2f7"):
            return f'<span style="background:{color};color:#1e1e2e;padding:2px 8px;border-radius:3px;font-weight:bold;">{val}</span>'

        def _section(title, icon=""):
            label = f"{icon} {title}" if icon else title
            return (
                f'<div style="background:#313244;color:#cdd6f4;padding:6px 12px;'
                f'border-radius:4px;font-weight:bold;font-size:13px;margin-top:12px;margin-bottom:4px;">'
                f'{label}</div>'
            )

        def _kv_table(rows):
            html = '<table style="border-collapse:collapse;width:100%;">'
            for i, (label, value, *rest) in enumerate(rows):
                highlight = rest[0] if rest else False
                bg = "#262637" if i % 2 == 0 else "#1e1e2e"
                val_style = "color:#a6e3a1;font-weight:bold;" if highlight else "color:#cdd6f4;"
                html += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:3px 12px;color:#9399b2;width:160px;white-space:nowrap;">{label}</td>'
                    f'<td style="padding:3px 12px;{val_style}">{value}</td>'
                    f'</tr>'
                )
            html += '</table>'
            return html

        def _data_table(headers, rows):
            html = '<table style="border-collapse:collapse;width:100%;font-size:11px;">'
            html += '<tr style="background:#45475a;color:#cdd6f4;">'
            for h in headers:
                html += f'<td style="padding:4px 10px;font-weight:bold;white-space:nowrap;">{h}</td>'
            html += '</tr>'
            for i, row in enumerate(rows):
                bg = "#262637" if i % 2 == 0 else "#1e1e2e"
                html += f'<tr style="background:{bg};">'
                for cell in row:
                    html += f'<td style="padding:3px 10px;color:#cdd6f4;white-space:nowrap;">{cell}</td>'
                html += '</tr>'
            html += '</table>'
            return html

        parts = []

        # Full Filename
        parts.append(_section(t("文件名"), "\U0001F4C4"))
        fname = _html.escape(Path(info.path).name)
        parts.append(
            f'<div style="background:#181825;border:1px solid #313244;border-radius:4px;'
            f'padding:8px 12px;font-family:Consolas,monospace;font-size:12px;color:#f9e2af;'
            f'word-break:break-all;margin:4px 0;">{fname}</div>'
        )

        # Parsed Fields
        if fn and fn.parse_ok:
            mode = t("启发式") if fn.heuristic else t("严格")
            parts.append(_section(f"{t('解析的文件名字段')} ({mode})", "🔍"))
            if fn.heuristic:
                parts.append(
                    f'<div style="color:#fab387;font-size:11px;margin-bottom:4px;">'
                    f'{t("文件名不完全符合命名规范 — 使用启发式回退解析。")}'
                    f'</div>'
                )
            parts.append(_kv_table([
                ("Sidecar", _badge(fn.sidecar, "#94e2d5") if fn.sidecar else '<span style="color:#585b70;">—</span>'),
                ("BaseName", _badge(fn.base_name, "#89b4fa") if fn.base_name else '<span style="color:#585b70;">—</span>'),
                ("SizeLabel", _badge(fn.size_label, "#f9e2af") if fn.size_label else '<span style="color:#585b70;">—</span>'),
                ("FineTune", fn.fine_tune or '<span style="color:#585b70;">—</span>'),
                ("Version", _badge(fn.version, "#cba6f7") if fn.version else '<span style="color:#585b70;">—</span>'),
                (t("编码"), _badge(fn.encoding, "#f38ba8") if fn.encoding else '<span style="color:#585b70;">—</span>'),
                ("Type", _badge(fn.type, "#fab387") if fn.type else '<span style="color:#585b70;">—</span>'),
                (t("分片"), fn.shard or '<span style="color:#585b70;">—</span>'),
            ]))
        else:
            parts.append(_section(t("解析结果"), "❌"))
            parts.append(
                f'<div style="color:#f38ba8;padding:8px;">'
                f'{t("文件名不符合推荐的 GGUF 命名规范。")}'
                f'</div>'
            )

        # Metadata Comparison
        parts.append(_section(t("元数据对比"), "\U0001F504"))
        comparisons = [
            (t("BaseName vs general.basename"), fn.base_name if fn else None, m.get("general.basename")),
            (t("SizeLabel vs general.size_label"), fn.size_label if fn else None, m.get("general.size_label")),
            (t("Version vs general.version"), fn.version if fn else None, m.get("general.version")),
            (t("Encoding vs dominant type"), fn.encoding if fn else None, info.stats.dominant_type_name or None),
        ]
        cmp_rows = []
        for label, fn_val, meta_val in comparisons:
            fn_str = fn_val or "—"
            meta_str = meta_val or "—"
            match = fn_val and meta_val and fn_val.lower() == str(meta_val).lower()
            status = _badge(t("匹配"), "#a6e3a1") if match else _badge(t("不匹配"), "#f38ba8")
            cmp_rows.append([
                f'{label}',
                f'<span style="color:#9399b2;">{_html.escape(str(fn_str))}</span>',
                f'<span style="color:#9399b2;">{_html.escape(str(meta_str))}</span>',
                status,
            ])
        parts.append(_data_table([t("对比"), t("文件名"), t("元数据"), ""], cmp_rows))

        html = (
            '<div style="padding:4px;font-family:Consolas,monospace;font-size:12px;">'
            + "".join(parts)
            + '</div>'
        )
        self._filename_text.setHtml(html)

    def _populate_diagnostics(self):
        # Run additional launcher-aware diagnostics
        from gguf.diagnostics import run_diagnostics
        diags = run_diagnostics(
            self._info,
            launcher_ctx=self._launcher_params.get("ctx_size", 0),
            mmproj_path=self._launcher_params.get("mmproj", ""),
            spec_type=self._launcher_params.get("spec_type", ""),
            draft_tokens=self._launcher_params.get("draft_tokens", 0),
            flash_attn=self._launcher_params.get("flash_attn", False),
        )

        level_colors = {
            "error": QColor("#f38ba8"),
            "warning": QColor("#fab387"),
            "info": QColor("#a6e3a1"),
        }

        self._diag_table.setRowCount(len(diags))
        for i, d in enumerate(diags):
            level_item = QTableWidgetItem(d.level.upper())
            level_item.setForeground(level_colors.get(d.level, QColor("#cdd6f4")))
            self._diag_table.setItem(i, 0, level_item)
            self._diag_table.setItem(i, 1, QTableWidgetItem(d.title))
            self._diag_table.setItem(i, 2, QTableWidgetItem(d.message))
        self._diag_table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _filter_metadata(self, _=None):
        text = self._meta_search.text()
        group = self._meta_group.currentText()
        self._proxy_metadata.setFilterFixedString(text)

        if group == t("全部"):
            self._proxy_metadata.setFilterKeyColumn(-1)
        elif group == "general.*":
            self._proxy_metadata.setFilterKeyColumn(0)
            self._proxy_metadata.setFilterRegularExpression(r"^general\.")
        elif group == "tokenizer.*":
            self._proxy_metadata.setFilterKeyColumn(0)
            self._proxy_metadata.setFilterRegularExpression(r"^tokenizer\.")
        elif group == t("架构字段"):
            arch = self._info.metadata.get("general.architecture", "") if self._info else ""
            if arch:
                self._proxy_metadata.setFilterKeyColumn(0)
                self._proxy_metadata.setFilterRegularExpression(rf"^{re.escape(arch)}\.")
            else:
                self._proxy_metadata.setFilterKeyColumn(-1)
                self._proxy_metadata.setFilterFixedString("")
        elif group == t("其他"):
            self._proxy_metadata.setFilterKeyColumn(0)
            self._proxy_metadata.setFilterRegularExpression(
                r"^(?!general\.|tokenizer\.|llama\.|qwen|gemma\.|mistral\.)"
            )

    def _filter_tensors(self, _=None):
        text = self._tensor_search.text()
        type_text = self._tensor_type_filter.currentText()
        layer_text = self._tensor_layer_filter.currentText()

        type_name = "" if type_text == t("全部类型") else type_text
        layer = "" if layer_text == t("全部层") else layer_text

        self._proxy_tensor.set_filters(text=text, type_name=type_name, layer=layer)

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _meta_context_menu(self, pos):
        index = self._meta_table.indexAt(pos)
        if not index.isValid():
            return
        source_index = self._proxy_metadata.mapToSource(index)
        row = source_index.row()

        menu = QMenu(self)
        copy_key = menu.addAction(t("复制 Key"))
        copy_val = menu.addAction(t("复制值"))
        copy_row = menu.addAction(t("复制行 (JSON)"))
        copy_all = menu.addAction(t("复制全部元数据 (JSON)"))

        action = menu.exec(self._meta_table.viewport().mapToGlobal(pos))
        if action == copy_key:
            QApplication.clipboard().setText(self._metadata_model._data[row][0])
        elif action == copy_val:
            QApplication.clipboard().setText(self._metadata_model._data[row][3])
        elif action == copy_row:
            QApplication.clipboard().setText(
                json.dumps(self._metadata_model.get_row_json(row), ensure_ascii=False, indent=2)
            )
        elif action == copy_all:
            QApplication.clipboard().setText(
                json.dumps(self._metadata_model.get_all_json(), ensure_ascii=False, indent=2)
            )

    def _tensor_context_menu(self, pos):
        index = self._tensor_table.indexAt(pos)
        if not index.isValid():
            return
        source_index = self._proxy_tensor.mapToSource(index)
        row = source_index.row()
        t_obj = self._tensor_model._data[row]

        menu = QMenu(self)
        copy_name = menu.addAction(t("复制张量名称"))
        copy_row = menu.addAction(t("复制行 (JSON)"))
        copy_all = menu.addAction(t("复制全部张量 (CSV)"))

        action = menu.exec(self._tensor_table.viewport().mapToGlobal(pos))
        if action == copy_name:
            QApplication.clipboard().setText(t_obj.name)
        elif action == copy_row:
            row_data = {
                "name": t_obj.name, "shape": "x".join(str(d) for d in t_obj.dims),
                "type": t_obj.type_name, "params": t_obj.n_params,
                "estimated_bytes": t_obj.estimated_nbytes,
                "offset": t_obj.offset, "absolute_offset": t_obj.absolute_offset,
                "layer": t_obj.layer, "module": t_obj.module,
            }
            QApplication.clipboard().setText(json.dumps(row_data, ensure_ascii=False, indent=2))
        elif action == copy_all:
            rows = self._tensor_model.get_tensor_csv_rows()
            if rows:
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
                QApplication.clipboard().setText(output.getvalue())

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_menu(self):
        if not self._info:
            return
        menu = QMenu(self)
        export_json = menu.addAction(t("导出元数据 JSON"))
        export_csv = menu.addAction(t("导出张量 CSV"))
        export_md = menu.addAction(t("导出报告 Markdown"))

        btn = self.sender()
        action = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

        if action == export_json:
            self._export_metadata_json()
        elif action == export_csv:
            self._export_tensors_csv()
        elif action == export_md:
            self._export_report_md()

    def _export_metadata_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出元数据 JSON"), "", "JSON Files (*.json)"
        )
        if not path:
            return
        data = self._metadata_model.get_all_json()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        QMessageBox.information(self, t("导出完成"), t("元数据已导出到 {path}").format(path=path))

    def _export_tensors_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出张量 CSV"), "", "CSV Files (*.csv)"
        )
        if not path:
            return
        rows = self._tensor_model.get_tensor_csv_rows()
        if not rows:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        QMessageBox.information(self, t("导出完成"), t("张量数据已导出到 {path}").format(path=path))

    def _export_report_md(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出报告 Markdown"), "", "Markdown Files (*.md)"
        )
        if not path:
            return
        info = self._info
        m = info.metadata
        arch = m.get("general.architecture", "")

        lines = [f"# GGUF Inspector Report\n"]
        lines.append(f"**File:** `{info.path}`\n")
        lines.append(f"**Date:** {datetime.now().isoformat()}\n")

        lines.append("## File Info\n")
        lines.append(f"| Key | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Filename | {Path(info.path).name} |")
        lines.append(f"| Size | {info.file_size / (1024**3):.2f} GB |")
        lines.append(f"| GGUF Version | {info.header.version} |")
        lines.append(f"| Tensor Count | {info.header.tensor_count} |")
        lines.append(f"| Alignment | {info.alignment} |")
        lines.append(f"| Tensor Data Offset | {info.tensor_data_offset:,} |")
        lines.append("")

        lines.append("## Metadata\n")
        lines.append(f"| Key | Type | Value |")
        lines.append(f"|---|---|---|")
        for key, value in sorted(m.items()):
            vtype = type(value).__name__
            if isinstance(value, list):
                preview = f"array[{len(value)}]"
            elif isinstance(value, str) and len(value) > 100:
                preview = value[:100] + "..."
            else:
                preview = str(value)
            lines.append(f"| `{key}` | {vtype} | {preview} |")
        lines.append("")

        lines.append("## Tensor Summary\n")
        lines.append(f"| Type | Count | Est. Size |")
        lines.append(f"|---|---|---|")
        for tid, count in sorted(info.stats.tensor_type_counts.items()):
            type_name = GGML_TYPES.get(tid, f"UNKNOWN_{tid}")
            est = info.stats.tensor_type_sizes.get(tid, 0)
            lines.append(f"| {type_name} | {count} | {est/(1024**2):.1f} MB |")
        lines.append("")

        lines.append("## Diagnostics\n")
        for d in info.diagnostics:
            icon = {"error": "!!", "warning": "!", "info": "i"}.get(d.level, "?")
            lines.append(f"- **[{icon.upper()}] {d.title}**: {d.message}")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        QMessageBox.information(self, t("导出完成"), t("报告已导出到 {path}").format(path=path))

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)
