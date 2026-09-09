# -*- coding: utf-8 -*-
"""E10: dialog to pick and reorder the params shown in the ⚡ 快捷开关 group.

Two panes:
  * left  — "shown" list, current order (drag or ↑/↓/remove buttons)
  * right — available params grouped by schema tab, checkable
            (check = add to the quick toggles, uncheck = remove)
plus a search box (matches key / CLI flag / label) and 恢复默认.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.i18n import t
from core.params_schema import PARAMS_BY_KEY, TAB_TITLES
from ui.quick_params import (
    QUICK_DEFAULT_KEYS, kind_display_name, quick_label_text, quick_short_label,
    quick_eligible, sanitize_quick_keys,
)


class QuickParamsDialog(QDialog):
    """Returns the ordered key list via result_keys() after accept()."""

    def __init__(self, parent=None, current_keys=None):
        super().__init__(parent)
        self.setWindowTitle(t("自定义快捷开关"))
        self.resize(680, 460)
        self._keys = sanitize_quick_keys(current_keys)
        self._tree_items = {}    # key -> QTreeWidgetItem (right pane)
        self._top_items = {}     # tab_key -> QTreeWidgetItem (group header)

        layout = QVBoxLayout(self)

        self._search = QLineEdit()
        self._search.setPlaceholderText(t("搜索参数（名称/flag）…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        center = QHBoxLayout()

        # ---- left: shown (ordered) -------------------------------------
        left_box = QVBoxLayout()
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.addWidget(QLabel(t("已显示")))
        self._sel = QListWidget()
        self._sel.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._sel.setDropIndicatorShown(True)
        self._sel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Qt 6 dropped QListView.itemMoved — watch the model move instead
        self._sel.model().rowsMoved.connect(self._on_sel_rows_moved)
        left_box.addWidget(self._sel, 1)
        btns = QHBoxLayout()
        for text, slot in ((t("上移"), self._move_up),
                           (t("下移"), self._move_down),
                           (t("移除"), self._remove_sel)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch()
        left_box.addLayout(btns)
        left_w = QWidget()
        left_w.setLayout(left_box)
        left_w.setFixedWidth(240)
        center.addWidget(left_w)

        # ---- right: available (grouped, checkable) ----------------------
        right_box = QVBoxLayout()
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.addWidget(QLabel(t("可选参数")))
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([t("参数"), t("类型")])
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        # NB: itemChanged is connected AFTER _populate_tree() below —
        # setFlags() during population fires itemChanged while the check
        # state is still Unchecked, which would make _on_tree_changed
        # treat the pre-selected defaults as unchecked and drop them.
        right_box.addWidget(self._tree, 1)
        hint = QLabel(t("勾选 = 显示在快捷开关；左侧拖拽或点按钮调整顺序"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8f98; font-size: 11px;")
        right_box.addWidget(hint)
        right_w = QWidget()
        right_w.setLayout(right_box)
        center.addWidget(right_w, 1)

        layout.addLayout(center, 1)

        bottom = QHBoxLayout()
        self._btn_default = QPushButton(t("恢复默认"))
        self._btn_default.setToolTip(t("恢复为默认的一组快捷开关"))
        self._btn_default.clicked.connect(self._reset_default)
        bottom.addWidget(self._btn_default)
        bottom.addStretch()
        self._ok = QPushButton(t("确定"))
        self._ok.setDefault(True)
        self._ok.clicked.connect(self.accept)
        cancel = QPushButton(t("取消"))
        cancel.clicked.connect(self.reject)
        bottom.addWidget(self._ok)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)

        self._populate_tree()
        self._tree.itemChanged.connect(self._on_tree_changed)
        self._sync_sel()

    # -- population --------------------------------------------------------

    def _populate_tree(self):
        by_tab = {}
        for p in quick_eligible():
            by_tab.setdefault(p.tab, []).append(p)
        for tab_key, tab_title in TAB_TITLES:
            top = QTreeWidgetItem([t(tab_title)])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._top_items[tab_key] = top
            self._tree.addTopLevelItem(top)
            for p in by_tab.get(tab_key, ()):
                item = QTreeWidgetItem(
                    [quick_label_text(p), kind_display_name(p.widget)])
                item.setData(0, Qt.ItemDataRole.UserRole, p.key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Checked if p.key in self._keys
                    else Qt.CheckState.Unchecked)
                flag = p.flag if isinstance(p.flag, str) else ""
                aliases = " ".join(filter(None,
                                          [flag] + list(p.flags)))
                item.setToolTip(0, f"{aliases}  ({p.key})")
                self._tree_items[p.key] = item
                top.addChild(item)
            top.setExpanded(True)

    # -- syncing the two panes ---------------------------------------------

    def _sync_sel(self):
        """Rebuild the left list from self._keys (single source of order)."""
        self._sel.blockSignals(True)
        self._sel.clear()
        for k in self._keys:
            p = PARAMS_BY_KEY[k]
            item = QListWidgetItem(quick_label_text(p))
            item.setData(Qt.ItemDataRole.UserRole, k)
            flag = p.flag if isinstance(p.flag, str) else ""
            item.setToolTip(f"{k}  {flag}".strip())
            self._sel.addItem(item)
        self._sel.blockSignals(False)
        self._ok.setEnabled(bool(self._keys))

    def _sync_tree(self, key, checked):
        item = self._tree_items.get(key)
        if item is None:
            return
        self._tree.blockSignals(True)
        item.setCheckState(
            0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._tree.blockSignals(False)

    def _on_tree_changed(self, item, col):
        if col != 0 or item.parent() is None:
            return  # group headers / the 类型 column
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            if key not in self._keys:
                self._keys.append(key)
                self._sync_sel()
        elif key in self._keys:
            self._keys.remove(key)
            self._sync_sel()

    def _on_sel_rows_moved(self, _first, _last, _parent, _before):
        # Re-read the order from the widget after a drag move.
        self._keys = [self._sel.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(self._sel.count())]

    # -- left-pane buttons ---------------------------------------------------

    def _sel_row(self):
        return self._sel.currentRow()

    def _move_up(self):
        r = self._sel_row()
        if 0 < r < len(self._keys):
            self._keys[r - 1], self._keys[r] = self._keys[r], self._keys[r - 1]
            self._sync_sel()
            self._sel.setCurrentRow(r - 1)

    def _move_down(self):
        r = self._sel_row()
        if 0 <= r < len(self._keys) - 1:
            self._keys[r], self._keys[r + 1] = self._keys[r + 1], self._keys[r]
            self._sync_sel()
            self._sel.setCurrentRow(r + 1)

    def _remove_sel(self):
        r = self._sel_row()
        if 0 <= r < len(self._keys):
            key = self._keys.pop(r)
            self._sync_sel()
            self._sync_tree(key, False)

    def _reset_default(self):
        self._keys = list(QUICK_DEFAULT_KEYS)
        self._sel.blockSignals(True)
        self._tree.blockSignals(True)
        self._sync_sel()
        for key, item in self._tree_items.items():
            item.setCheckState(
                0, Qt.CheckState.Checked if key in self._keys
                else Qt.CheckState.Unchecked)
        self._sel.blockSignals(False)
        self._tree.blockSignals(False)

    # -- search ----------------------------------------------------------------

    def _match(self, p, text: str) -> bool:
        if not text:
            return True
        flag = p.flag if isinstance(p.flag, str) else ""
        hay = " ".join(filter(None, [
            p.key, flag, *p.flags,
            quick_short_label(p), quick_label_text(p),
        ])).lower()
        return text in hay

    def _apply_filter(self, raw: str):
        text = raw.strip().lower()
        for tab_key, tab_title in TAB_TITLES:
            top = self._top_items[tab_key]
            visible = 0
            for i in range(top.childCount()):
                child = top.child(i)
                p = PARAMS_BY_KEY[child.data(0, Qt.ItemDataRole.UserRole)]
                show = self._match(p, text)
                child.setHidden(not show)
                if show:
                    visible += 1
            title_hits = bool(text) and text in t(tab_title).lower()
            top.setHidden(not (visible or title_hits))
            top.setExpanded(True)

    # -- result -----------------------------------------------------------------

    def result_keys(self):
        return list(self._keys)
