from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QGroupBox
)
from PyQt6.QtCore import pyqtSignal, QThread
from core.i18n import t


class ModelScanner(QThread):
    scan_finished = pyqtSignal(list, list, list)
    scan_progress = pyqtSignal(str)

    def __init__(self, search_dir):
        super().__init__()
        self.search_dir = search_dir
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        models = []
        mmprojs = []
        loras = []

        if not self.search_dir.exists():
            self.scan_finished.emit(models, mmprojs, loras)
            return

        for f in sorted(self.search_dir.rglob("*.gguf"), key=lambda x: x.name):
            if self._stop_flag:
                return
            if f.is_file():
                name = f.name
                size_mb = f.stat().st_size / (1024 * 1024)
                if size_mb > 1024:
                    size_str = f"{size_mb/1024:.1f} GB"
                else:
                    size_str = f"{size_mb:.0f} MB"
                if "mmproj" in name.lower():
                    mmprojs.append((str(f), name, size_str))
                elif "lora" in name.lower():
                    loras.append(str(f))
                else:
                    models.append((str(f), name, size_str))

        self.scan_finished.emit(models, mmprojs, loras)


class ModelBrowser(QWidget):
    model_selected = pyqtSignal(str)
    mmproj_selected = pyqtSignal(str)

    def __init__(self, search_dir=None, parent=None):
        super().__init__(parent)
        self.search_dir = Path(search_dir) if search_dir else Path.cwd()
        self.models = []
        self.mmprojs = []
        self.loras = []
        self._scanner_thread = None
        self.init_ui()
        self.scan_models()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._models_group = QGroupBox(t("📦 模型文件"))
        models_layout = QVBoxLayout(self._models_group)
        self.model_list = QListWidget()
        self.model_list.itemClicked.connect(self._on_model_click)
        models_layout.addWidget(self.model_list)
        layout.addWidget(self._models_group)

        self._mmproj_group = QGroupBox(t("🖼️ 多模态投影"))
        mmproj_layout = QVBoxLayout(self._mmproj_group)
        self.mmproj_list = QListWidget()
        self.mmproj_list.itemClicked.connect(self._on_mmproj_click)
        mmproj_layout.addWidget(self.mmproj_list)
        layout.addWidget(self._mmproj_group)

        self.status_label = QLabel(t("未扫描"))
        self.status_label.setStyleSheet("color: #565f89; font-size: 11px;")
        layout.addWidget(self.status_label)

    def scan_models(self):
        self.status_label.setText(t("扫描中..."))
        self.model_list.clear()
        self.mmproj_list.clear()

        if self._scanner_thread and self._scanner_thread.isRunning():
            self._scanner_thread.stop()
            self._scanner_thread.wait()

        self._scanner_thread = ModelScanner(self.search_dir)
        self._scanner_thread.scan_finished.connect(self._on_scan_finished)
        self._scanner_thread.start()

    def _on_scan_finished(self, models, mmprojs, loras):
        self.models = [m[0] for m in models]
        self.mmprojs = [m[0] for m in mmprojs]
        self.loras = loras

        for path, name, size_str in models:
            item = QListWidgetItem(f"{name}  ({size_str})")
            item.setToolTip(path)
            self.model_list.addItem(item)

        for path, name, size_str in mmprojs:
            item = QListWidgetItem(name)
            item.setToolTip(path)
            self.mmproj_list.addItem(item)

        self.status_label.setText(t("已扫描: {n_models} 个模型, {n_mmprojs} 个 mmproj", n_models=len(self.models), n_mmprojs=len(self.mmprojs)))

    def _on_item_click(self, item, items_list, signal):
        idx = self.model_list.row(item) if items_list is self.models else self.mmproj_list.row(item)
        if 0 <= idx < len(items_list):
            signal.emit(items_list[idx])

    def _on_model_click(self, item):
        self._on_item_click(item, self.models, self.model_selected)

    def _on_mmproj_click(self, item):
        self._on_item_click(item, self.mmprojs, self.mmproj_selected)

    def set_search_dir(self, path):
        self.search_dir = Path(path)
        self.scan_models()

    def retranslate_ui(self):
        self._models_group.setTitle(t("📦 模型文件"))
        self._mmproj_group.setTitle(t("🖼️ 多模态投影"))
        if self.models or self.mmprojs:
            self.status_label.setText(t("已扫描: {n_models} 个模型, {n_mmprojs} 个 mmproj", n_models=len(self.models), n_mmprojs=len(self.mmprojs)))
        else:
            self.status_label.setText(t("未扫描"))

    def auto_select_mmproj(self, model_path):
        if not model_path:
            return
        model_name = Path(model_path).stem.lower()
        fallback = None
        for mmproj in self.mmprojs:
            mmproj_name = Path(mmproj).stem.lower()
            if model_name in mmproj_name:
                self.mmproj_selected.emit(mmproj)
                return
            if fallback is None and "mmproj" in mmproj_name:
                fallback = mmproj
        if fallback is not None:
            self.mmproj_selected.emit(fallback)
