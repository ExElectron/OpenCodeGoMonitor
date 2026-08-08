# -*- coding: utf-8 -*-
"""选项卡 2：所有使用记录（Raw Logs）

- QTableView + 虚拟分页模型（滚动到底部自动加载下一页，200 条/页）
- 实时搜索框（防抖 300ms，匹配 模型/Key/标签/提供方/ID）
- 异常高消耗标红（成本或总Token > 均值 3 倍，整行标红）
- 双击标签列标记 Tag / 右键菜单
"""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMenu, QTableView,
                               QVBoxLayout, QWidget)

COLUMNS = [
    ("timestamp_local", "时间(本地)"),
    ("api_key_masked", "API Key(脱敏)"),
    ("model_name", "模型"),
    ("provider", "提供方"),
    ("prompt_tokens", "总输入"),
    ("completion_tokens", "输出"),
    ("cache_read_tokens", "缓存读"),
    ("total_tokens", "总Tokens"),
    ("cost", "成本($)"),
    ("tag", "标签"),
    ("id", "记录ID"),
]
PAGE = 200


class LogsModel(QAbstractTableModel):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows = []
        self.total = 0
        self.filters = {}
        self.outlier_cost_ids = set()
        self.outlier_token_ids = set()
        self.red_bg = "#5a2323"
        self.red_fg = "#ff8f8f"

    # ---- 数据 ----
    def apply_filters(self, filters: dict):
        self.filters = filters or {}
        self.total = self.db.count(self.filters)
        o = self.db.outliers(self.filters)
        self.outlier_cost_ids, self.outlier_token_ids = o["cost_ids"], o["token_ids"]
        self.beginResetModel()
        self.rows = []
        self.endResetModel()
        self.load_more()

    def load_more(self):
        if len(self.rows) >= self.total:
            return
        n = min(PAGE, self.total - len(self.rows))
        new_rows = self.db.query(self.filters, limit=n, offset=len(self.rows))
        if not new_rows:
            return
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(new_rows) - 1)
        self.rows.extend(new_rows)
        self.endInsertRows()

    def set_tag(self, row: int, tag: str):
        rec = self.rows[row]
        self.db.set_tag(rec["id"], tag)
        rec["tag"] = tag
        idx = self.index(row, 9)
        self.dataChanged.emit(idx, idx)

    def remove_tag(self, row: int):
        self.set_tag(row, "")

    def row_of_id(self, record_id: str) -> int:
        for i, r in enumerate(self.rows):
            if r["id"] == record_id:
                return i
        return -1

    # ---- Qt 模型接口 ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row >= len(self.rows):
            return None
        rec = self.rows[row]
        key = COLUMNS[col][0]
        if role == Qt.DisplayRole:
            v = rec.get(key)
            if key == "cost":
                return f"${v:,.4f}" if v is not None else "-"
            if key in ("prompt_tokens", "completion_tokens", "cache_read_tokens", "total_tokens"):
                return f"{v:,}" if v is not None else "-"
            return v if v not in (None, "") else "-"
        if role == Qt.UserRole:
            return rec.get(key)
        if role == Qt.ForegroundRole:
            if rec["id"] in self.outlier_cost_ids or rec["id"] in self.outlier_token_ids:
                return QColor(self.red_fg)
        if role == Qt.BackgroundRole:
            if rec["id"] in self.outlier_cost_ids or rec["id"] in self.outlier_token_ids:
                return QColor(self.red_bg)
        if role == Qt.ToolTipRole:
            why = []
            if rec["id"] in self.outlier_cost_ids:
                why.append("成本超过均值3倍")
            if rec["id"] in self.outlier_token_ids:
                why.append("Token超过均值3倍")
            if why:
                return "⚠️ 异常高消耗: " + "、".join(why)
        return None


class LogsTab(QWidget):
    record_clicked = Signal(str)          # record_id

    def __init__(self, db, settings, main_window, parent=None):
        super().__init__(parent)
        self.db = db
        self.main = main_window
        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filters)
        self.reload()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("快速搜索"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索模型 / API Key / 标签 / 提供方 / 记录ID …（实时过滤）")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(lambda _: self._search_timer.start(300))
        bar.addWidget(self.search_box, 3)
        bar.addWidget(QLabel("标签"))
        self.tag_combo = QComboBox()
        self.tag_combo.addItem("全部")
        self.tag_combo.currentIndexChanged.connect(lambda _: self._apply_filters())
        bar.addWidget(self.tag_combo)
        self.count_lbl = QLabel("")
        bar.addWidget(self.count_lbl)
        root.addLayout(bar)

        self.table = QTableView()
        self.model = LogsModel(self.db)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        for i, (_, label) in enumerate(COLUMNS):
            self.table.setColumnWidth(i, {0: 160, 1: 150, 2: 130, 3: 130, 4: 90,
                                          5: 90, 6: 90, 7: 100, 8: 100, 9: 110, 10: 200}.get(i, 100))
        self.table.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    def reload(self, filters: dict = None):
        """外部调用（同步完成/联动）时刷新。filters 为 None 时保留当前条件。"""
        if filters is not None:
            self._stored_filters = filters
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("全部")
        self.tag_combo.addItems(self.db.all_tags())
        self.tag_combo.blockSignals(False)
        self._apply_filters()

    def _current_filters(self) -> dict:
        f = dict(getattr(self, "_stored_filters", {}) or {})
        if self.tag_combo.currentIndex() > 0:
            f["tags"] = [self.tag_combo.currentText()]
        search = self.search_box.text().strip()
        if search:
            f["search"] = search
        return f

    def _apply_filters(self):
        self.model.apply_filters(self._current_filters())
        # 预加载数页直到铺满视口
        for _ in range(3):
            if len(self.model.rows) >= self.model.total:
                break
            self.model.load_more()
        self.count_lbl.setText(f"共 {self.model.total:,} 条（已加载 {len(self.model.rows):,}）")

    def _on_scroll(self, value):
        bar = self.table.verticalScrollBar()
        if value >= bar.maximum() - 60:
            before = len(self.model.rows)
            self.model.load_more()
            if len(self.model.rows) != before:
                self.count_lbl.setText(f"共 {self.model.total:,} 条（已加载 {len(self.model.rows):,}）")

    def _on_double_click(self, index):
        if index.column() == 9:   # 标签列
            row = index.row()
            current = self.model.rows[row].get("tag") or ""
            text, ok = QInputDialog.getText(self, "设置标签",
                                            "输入自定义标签（留空清除）:", text=current)
            if ok:
                self.model.set_tag(row, text.strip())
        else:
            rec = self.model.rows[index.row()]
            self.record_clicked.emit(rec["id"])

    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        rec = self.model.rows[row]
        menu = QMenu(self)
        act_tag = menu.addAction("设置标签…")
        act_clear = menu.addAction("清除标签")
        if not rec.get("tag"):
            act_clear.setEnabled(False)
        act_copy = menu.addAction("复制记录ID")
        act_detail = menu.addAction("在分析页查看此记录")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_tag:
            text, ok = QInputDialog.getText(self, "设置标签",
                                            "输入自定义标签:", text=rec.get("tag") or "")
            if ok:
                self.model.set_tag(row, text.strip())
        elif chosen == act_clear:
            self.model.remove_tag(row)
        elif chosen == act_copy:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(rec["id"])
        elif chosen == act_detail:
            self.record_clicked.emit(rec["id"])

    def show_tag(self, tag: str):
        """外部联动：按标签过滤。"""
        idx = self.tag_combo.findText(tag)
        if idx >= 0:
            self.tag_combo.setCurrentIndex(idx)
        else:
            self.tag_combo.addItem(tag)
            self.tag_combo.setCurrentIndex(self.tag_combo.count() - 1)
        self._apply_filters()

    def show_model(self, model: str):
        """外部联动（总览点击扇形）：按模型过滤。"""
        self.search_box.setText(model)
        self._apply_filters()
