# -*- coding: utf-8 -*-
"""选项卡 3：高级统计与分析（Analytics）

- 多维度筛选面板：时间范围 / API Key 多选 / 模型多选 / 成本范围 / Token 范围 / 标签
- 5 类动态图表（筛选后实时更新）：
  双轴时间趋势 / 星期×小时热力图 / Key×模型堆叠柱状图 / 累积成本+月底预测 / 单次请求散点
- 图表-表格反向联动：点击图表区域 → 底部明细表自动筛选
- 筛选预设保存/加载；SQL 终端入口
"""
import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateTimeEdit, QDoubleSpinBox,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPushButton, QSpinBox, QTableView,
                               QTabWidget, QVBoxLayout, QWidget)

from ocgmon.charts import (build_cumulative, build_dual_trend, build_heatmap,
                           build_scatter, build_stacked_bar, WD_LABELS)
from ocgmon.ui.common import section_title
from ocgmon.ui.preset_dialog import PresetDialog
from ocgmon.ui.sql_terminal import SqlTerminalDialog


class CheckableCombo(QComboBox):
    """带复选框的多选下拉框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QStandardItemModel
        self._smodel = QStandardItemModel(self)
        self.setModel(self._smodel)
        self.setMaxVisibleItems(12)
        self.currentIndexChanged.connect(self._keep_text)
        self.setMinimumWidth(180)

    def set_items(self, items: list, all_checked=True):
        from PySide6.QtGui import QStandardItem
        self._smodel.clear()
        for it in items:
            si = QStandardItem(it)
            si.setCheckable(True)
            si.setCheckState(Qt.Checked if all_checked else Qt.Unchecked)
            self._smodel.appendRow(si)
        self.setCurrentIndex(-1)

    def _keep_text(self, *a):
        pass

    def selected(self) -> list:
        out = []
        for i in range(self._smodel.rowCount()):
            it = self._smodel.item(i)
            if it and it.checkState() == Qt.Checked:
                out.append(it.text())
        return out

    def all_items(self) -> list:
        return [self._smodel.item(i).text() for i in range(self._smodel.rowCount())]

    def check_all(self, checked: bool):
        for i in range(self._smodel.rowCount()):
            self._smodel.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.setCurrentIndex(-1)

    def showPopup(self):
        super().showPopup()
        self.setCurrentIndex(-1)


class LinkTableModel(QAbstractTableModel):
    """联动明细表模型（最多 500 行）。"""

    COLS = [("timestamp_local", "时间(本地)"), ("api_key_masked", "API Key"),
            ("model_name", "模型"), ("total_tokens", "总Tokens"),
            ("cost", "成本($)"), ("tag", "标签")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        rec = self.rows[index.row()]
        key = self.COLS[index.column()][0]
        if role == Qt.DisplayRole:
            v = rec.get(key)
            if key == "cost":
                return f"${v:,.4f}"
            if key == "total_tokens":
                return f"{v:,}"
            return v if v not in (None, "") else "-"
        return None


class AnalyticsTab(QWidget):
    def __init__(self, db, settings, main_window, parent=None):
        super().__init__(parent)
        self.db = db
        self.main = main_window
        self._build_ui()
        self.reload_options()
        self._apply()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ---- 筛选面板 ----
        panel = QFrame()
        panel.setObjectName("card")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 10, 12, 10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("时间范围"))
        self.from_edit = QDateTimeEdit(datetime.datetime.now() - datetime.timedelta(days=7))
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.to_edit = QDateTimeEdit(datetime.datetime.now())
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        row1.addWidget(self.from_edit)
        row1.addWidget(QLabel("→"))
        row1.addWidget(self.to_edit)
        self.quick_combo = QComboBox()
        self.quick_combo.addItems(["近24小时", "近7天", "近30天", "自定义"])
        self.quick_combo.setCurrentIndex(1)
        self.quick_combo.currentIndexChanged.connect(self._on_quick_range)
        row1.addWidget(self.quick_combo)
        row1.addSpacing(12)
        row1.addWidget(QLabel("API Key"))
        self.key_combo = CheckableCombo()
        row1.addWidget(self.key_combo)
        row1.addSpacing(12)
        row1.addWidget(QLabel("模型"))
        self.model_combo = CheckableCombo()
        row1.addWidget(self.model_combo)
        pl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("成本范围 $"))
        self.min_cost = QDoubleSpinBox()
        self.min_cost.setRange(0, 100000); self.min_cost.setDecimals(4); self.min_cost.setPrefix("$")
        self.max_cost = QDoubleSpinBox()
        self.max_cost.setRange(0, 100000); self.max_cost.setDecimals(4); self.max_cost.setPrefix("$")
        self.max_cost.setValue(100000)
        row2.addWidget(self.min_cost)
        row2.addWidget(QLabel("~"))
        row2.addWidget(self.max_cost)
        row2.addSpacing(12)
        row2.addWidget(QLabel("Token 范围"))
        self.min_tokens = QSpinBox(); self.min_tokens.setRange(0, 10 ** 9)
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(0, 10 ** 9); self.max_tokens.setValue(10 ** 9)
        row2.addWidget(self.min_tokens)
        row2.addWidget(QLabel("~"))
        row2.addWidget(self.max_tokens)
        row2.addSpacing(12)
        row2.addWidget(QLabel("标签"))
        self.tag_list = QComboBox()
        self.tag_list.addItem("全部")
        row2.addWidget(self.tag_list)
        row2.addStretch(1)
        pl.addLayout(row2)

        row3 = QHBoxLayout()
        self.btn_apply = QPushButton("应用筛选")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.clicked.connect(self._apply)
        self.btn_reset = QPushButton("重置")
        self.btn_reset.clicked.connect(self._reset)
        self.btn_preset = QPushButton("预设方案…")
        self.btn_preset.clicked.connect(self._open_presets)
        self.btn_sql = QPushButton("SQL 终端")
        self.btn_sql.clicked.connect(self._open_sql)
        row3.addWidget(self.btn_apply)
        row3.addWidget(self.btn_reset)
        row3.addWidget(self.btn_preset)
        row3.addWidget(self.btn_sql)
        row3.addStretch(1)
        self.link_lbl = QLabel("")
        self.link_lbl.setObjectName("badgeWarn")
        row3.addWidget(self.link_lbl)
        self.btn_clear_link = QPushButton("清除联动")
        self.btn_clear_link.setVisible(False)
        self.btn_clear_link.clicked.connect(self._clear_link)
        row3.addWidget(self.btn_clear_link)
        pl.addLayout(row3)
        root.addWidget(panel)

        # ---- 图表区 + 联动表 ----
        split = QTabWidget()
        self.charts_tab = split
        split.addTab(QWidget(), "双轴趋势")
        split.addTab(QWidget(), "热力图")
        split.addTab(QWidget(), "Key×模型堆叠")
        split.addTab(QWidget(), "累积成本预测")
        split.addTab(QWidget(), "单次请求散点")
        self._chart_holder = {}
        for i in range(5):
            lay = QVBoxLayout(split.widget(i))
            lay.setContentsMargins(4, 4, 4, 4)
            self._chart_holder[i] = lay
        split.setMinimumHeight(330)
        root.addWidget(split, 3)

        # 联动明细表
        link_frame = QFrame()
        link_frame.setObjectName("card")
        ll = QVBoxLayout(link_frame)
        ll.setContentsMargins(10, 8, 10, 8)
        ll.addWidget(section_title("联动明细（点击图表区域自动筛选）"))
        self.link_table = QTableView()
        self._link_model = LinkTableModel()
        self.link_table.setModel(self._link_model)
        self.link_table.verticalHeader().setVisible(False)
        ll.addWidget(self.link_table, 1)
        root.addWidget(link_frame, 2)

    # ------------------------------------------------------------------
    def reload_options(self):
        keys = [r["key_id"] for r in self.db.by_key()]
        models = [r["model"] for r in self.db.by_model()]
        self.key_combo.set_items(keys if keys else ["(无)"])
        self.model_combo.set_items(models if models else ["(无)"])
        self.tag_list.clear()
        self.tag_list.addItem("全部")
        self.tag_list.addItems(self.db.all_tags())

    def _on_quick_range(self, idx):
        now = datetime.datetime.now()
        presets = [datetime.timedelta(hours=24), datetime.timedelta(days=7),
                   datetime.timedelta(days=30), None]
        d = presets[idx]
        if d is not None:
            self.from_edit.setDateTime(now - d)
            self.to_edit.setDateTime(now)

    def _filters(self, with_link: bool = True) -> dict:
        f = {
            "start_epoch": int(self.from_edit.dateTime().toPython().timestamp()),
            "end_epoch": int(self.to_edit.dateTime().toPython().timestamp()),
        }
        keys = self.key_combo.selected()
        if keys and keys != self.key_combo.all_items():
            f["keys"] = keys
        models = self.model_combo.selected()
        if models and models != self.model_combo.all_items():
            f["models"] = models
        if self.min_cost.value() > 0:
            f["min_cost"] = self.min_cost.value()
        if self.max_cost.value() < 100000:
            f["max_cost"] = self.max_cost.value()
        if self.min_tokens.value() > 0:
            f["min_tokens"] = self.min_tokens.value()
        if self.max_tokens.value() < 10 ** 9:
            f["max_tokens"] = self.max_tokens.value()
        if self.tag_list.currentIndex() > 0:
            f["tags"] = [self.tag_list.currentText()]
        if with_link and getattr(self, "_link_filters", None):
            f.update(self._link_filters)
        return f

    def _apply(self):
        f = self._filters()
        p = self.main.palette_theme()
        total = self.db.count(f)

        def clear(lay):
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        for i in range(5):
            clear(self._chart_holder[i])

        # 1) 双轴趋势
        granularity = "hour" if (f.get("end_epoch", 0) - f.get("start_epoch", 0)) < 172800 else "day"
        trend = self.db.trend(f, granularity)
        w = build_dual_trend(trend, granularity, p)
        self._chart_holder[0].addWidget(w)

        # 2) 热力图
        hm = self.db.heatmap(f)
        w = build_heatmap(hm["matrix"], hm["max_calls"], p,
                          click_handler=self._on_chart_click)
        self._chart_holder[1].addWidget(w)

        # 3) 堆叠柱状
        matrix = self.db.key_model_matrix(f)
        keys = list(matrix.keys())
        models = sorted({m for kv in matrix.values() for m in kv})
        w = build_stacked_bar(keys, models, matrix, p, click_handler=self._on_chart_click)
        self._chart_holder[2].addWidget(w)

        # 4) 累积成本
        cum = self.db.cumulative(f)
        w = build_cumulative(cum, p)
        self._chart_holder[3].addWidget(w)

        # 5) 散点
        rows = self.db.query(f, limit=3000)
        w = build_scatter(rows, p, click_handler=self._on_chart_click)
        self._chart_holder[4].addWidget(w)

        # 联动表（若存在联动条件）
        if getattr(self, "_link_filters", None):
            self._refresh_link_table()
        else:
            self._link_model.set_rows([])
        self.link_lbl.setText(f"当前筛选: {total:,} 条记录")

    def _reset(self):
        self._link_filters = None
        self.btn_clear_link.setVisible(False)
        self.key_combo.check_all(True)
        self.model_combo.check_all(True)
        self.min_cost.setValue(0); self.max_cost.setValue(100000)
        self.min_tokens.setValue(0); self.max_tokens.setValue(10 ** 9)
        self.tag_list.setCurrentIndex(0)
        self._apply()

    # ---- 图表联动 ----
    def _on_chart_click(self, payload):
        self._link_filters = {}
        desc = ""
        if payload.get("kind") == "heatmap":
            self._link_filters = {"weekday": payload["weekday"], "hour": payload["hour"]}
            desc = f"{WD_LABELS[payload['weekday']]} {payload['hour']:02d}:00-{payload['hour'] + 1:02d}:00"
        elif payload.get("kind") == "stack":
            self._link_filters = {"keys": [payload["key"]], "models": [payload["model"]]}
            desc = f"Key {payload['key'][:12]}… × {payload['model']}"
        elif payload.get("kind") == "scatter":
            self._link_filters = {"record_id": payload["record_id"]}
            desc = f"记录 {payload['record_id']}"
        elif isinstance(payload, str):
            self._link_filters = {"models": [payload]}
            desc = f"模型 {payload}"
        self.link_lbl.setText(f"🔗 已联动筛选: {desc}")
        self.btn_clear_link.setVisible(True)
        self._apply()

    def _clear_link(self):
        self._link_filters = None
        self.btn_clear_link.setVisible(False)
        self.link_lbl.setText("")
        self._apply()

    def _refresh_link_table(self):
        rows = self.db.query(self._filters(), limit=500)
        self._link_model.set_rows(rows)

    # ---- 预设 & SQL ----
    def _open_presets(self):
        dlg = PresetDialog(self.db, self)
        if dlg.exec():
            f = dlg.selected_preset
            if f is None:
                return
            # 应用预设
            if f.get("start_epoch"):
                self.from_edit.setDateTime(datetime.datetime.fromtimestamp(f["start_epoch"]))
            if f.get("end_epoch"):
                self.to_edit.setDateTime(datetime.datetime.fromtimestamp(f["end_epoch"]))
            if f.get("keys"):
                self.key_combo.check_all(False)
                for i, it in enumerate(self.key_combo.all_items()):
                    if it in f["keys"]:
                        from PySide6.QtGui import QStandardItem
                        self.key_combo._smodel.item(i).setCheckState(Qt.Checked)
            if f.get("models"):
                self.model_combo.check_all(False)
                for i, it in enumerate(self.model_combo.all_items()):
                    if it in f["models"]:
                        self.model_combo._smodel.item(i).setCheckState(Qt.Checked)
            self.min_cost.setValue(f.get("min_cost") or 0)
            self.max_cost.setValue(f.get("max_cost") or 100000)
            self.min_tokens.setValue(f.get("min_tokens") or 0)
            self.max_tokens.setValue(f.get("max_tokens") or 10 ** 9)
            self._apply()

    def _open_sql(self):
        dlg = SqlTerminalDialog(self.db, self.main, self)
        dlg.exec()

    def save_current_as_preset(self, name: str):
        import json
        self.db.save_preset(name, json.dumps(self._filters(with_link=False), ensure_ascii=False))
