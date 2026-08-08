# -*- coding: utf-8 -*-
"""筛选预设对话框：保存 / 应用 / 删除常用筛选组合。"""
import json

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout)


class PresetDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("筛选预设方案")
        self.resize(460, 360)
        self.db = db
        self.selected_preset = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("已保存的预设方案（点击『应用』一键生效）"))
        self.listw = QListWidget()
        self._reload()
        lay.addWidget(self.listw, 1)

        row = QHBoxLayout()
        self.btn_save = QPushButton("保存当前筛选…")
        self.btn_save.clicked.connect(self._save)
        self.btn_apply = QPushButton("应用")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.clicked.connect(self._apply)
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(self._delete)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

    def _reload(self):
        self.listw.clear()
        for p in self.db.presets():
            item = QListWidgetItem(f"{p['name']}  ({p['created_at']})")
            item.setData(0x0100 + 1, p)     # Qt.UserRole
            self.listw.addItem(item)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _current_preset(self):
        item = self.listw.currentItem()
        return item.data(0x0100 + 1) if item else None

    def _save(self):
        from ocgmon.ui.analytics_tab import AnalyticsTab
        parent = self.parent()
        name, ok = QInputDialog.getText(self, "保存预设", "预设名称:",
                                        text="我的筛选方案")
        if not ok or not name.strip():
            return
        if isinstance(parent, AnalyticsTab):
            parent.save_current_as_preset(name.strip())
        self._reload()

    def _apply(self):
        p = self._current_preset()
        if not p:
            QMessageBox.information(self, "提示", "请先选择要应用的预设")
            return
        self.selected_preset = json.loads(p["filter_json"])
        self.accept()

    def _delete(self):
        p = self._current_preset()
        if not p:
            return
        self.db.delete_preset(p["id"])
        self._reload()
