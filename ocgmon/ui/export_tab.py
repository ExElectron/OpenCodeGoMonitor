# -*- coding: utf-8 -*-
"""选项卡 4：数据导出（Export）

支持 .csv / .xlsx；xlsx 含 5 个 Sheet（Raw_Data / Summary_Charts / By_API_Key /
By_Model / 说明）。导出在后台线程执行，不阻塞界面。
"""
import datetime
import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ocgmon.exporter import ExportWorker, export_csv, export_xlsx
from ocgmon.ui.common import section_title
from ocgmon.ui.analytics_tab import CheckableCombo


class ExportTab(QWidget):
    def __init__(self, db, settings, main_window, parent=None):
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.main = main_window
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        panel = QFrame()
        panel.setObjectName("card")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)

        pl.addWidget(section_title("导出范围"))

        row1 = QHBoxLayout()
        self.rb_all = QRadioButton("全部记录")
        self.rb_all.setChecked(True)
        self.rb_recent = QRadioButton("最近")
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 365)
        self.spin_days.setValue(7)
        self.spin_days.setSuffix(" 天")
        self.rb_custom = QRadioButton("自定义时间范围")
        from PySide6.QtWidgets import QDateTimeEdit
        self.custom_from = QDateTimeEdit(datetime.datetime.now() - datetime.timedelta(days=7))
        self.custom_from.setCalendarPopup(True)
        self.custom_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.custom_to = QDateTimeEdit(datetime.datetime.now())
        self.custom_to.setCalendarPopup(True)
        self.custom_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        row1.addWidget(self.rb_all)
        row1.addSpacing(16)
        row1.addWidget(self.rb_recent)
        row1.addWidget(self.spin_days)
        row1.addSpacing(16)
        row1.addWidget(self.rb_custom)
        row1.addWidget(self.custom_from)
        row1.addWidget(QLabel("→"))
        row1.addWidget(self.custom_to)
        row1.addStretch(1)
        pl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("API Key 筛选"))
        self.key_combo = CheckableCombo()
        row2.addWidget(self.key_combo)
        row2.addSpacing(12)
        row2.addWidget(QLabel("模型筛选"))
        self.model_combo = CheckableCombo()
        row2.addWidget(self.model_combo)
        row2.addWidget(QLabel("（留空 = 不限制）"))
        row2.addStretch(1)
        pl.addLayout(row2)

        pl.addWidget(section_title("导出格式与路径"))
        row3 = QHBoxLayout()
        self.rb_csv = QRadioButton(".csv")
        self.rb_xlsx = QRadioButton(".xlsx（多 Sheet：明细/汇总/按Key/按模型）")
        self.rb_xlsx.setChecked(True)
        row3.addWidget(self.rb_csv)
        row3.addWidget(self.rb_xlsx)
        row3.addStretch(1)
        pl.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("保存到"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("默认保存到 %APPDATA%/OCGMonitor/exports/")
        row4.addWidget(self.path_edit, 1)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._browse)
        row4.addWidget(self.btn_browse)
        self.btn_export = QPushButton("开始导出")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self._export)
        row4.addWidget(self.btn_export)
        pl.addLayout(row4)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        pl.addWidget(self.progress)
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("cardSub")
        pl.addWidget(self.status_lbl)
        root.addWidget(panel)
        root.addStretch(1)

        # 默认路径
        self.path_edit.setText(os.path.join(
            os.path.expanduser("~"), "Desktop",
            f"opencode_usage_export_{time.strftime('%Y%m%d_%H%M%S')}"))

    def reload_options(self):
        self.key_combo.set_items([r["key_id"] for r in self.db.by_key()] or ["(无)"])
        self.model_combo.set_items([r["model"] for r in self.db.by_model()] or ["(无)"])

    def _browse(self):
        fmt = "csv" if self.rb_csv.isChecked() else "xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "选择导出文件", self.path_edit.text() or "opencode_usage_export",
            f"{'CSV 文件' if fmt == 'csv' else 'Excel 文件'} (*.{fmt})")
        if path:
            self.path_edit.setText(path)

    def _filters(self) -> dict:
        f = {}
        if self.rb_recent.isChecked():
            now = datetime.datetime.now()
            f = self.db.range_epochs("custom",
                                     now - datetime.timedelta(days=self.spin_days.value()),
                                     now)
        elif self.rb_custom.isChecked():
            f = self.db.range_epochs("custom",
                                     self.custom_from.dateTime().toPython(),
                                     self.custom_to.dateTime().toPython())
        keys = self.key_combo.selected()
        if keys and keys != self.key_combo.all_items():
            f["keys"] = keys
        models = self.model_combo.selected()
        if models and models != self.model_combo.all_items():
            f["models"] = models
        return f

    def _export(self):
        fmt = "csv" if self.rb_csv.isChecked() else "xlsx"
        base = self.path_edit.text().strip()
        if not base:
            QMessageBox.warning(self, "提示", "请先选择导出路径")
            return
        if not base.lower().endswith(("." + fmt)):
            base += "." + fmt
        self.path_edit.setText(base)

        # 后台线程取数 + 导出
        f = self._filters()
        total = self.db.count(f)
        if total == 0:
            QMessageBox.information(self, "提示", "当前筛选范围没有可导出的数据")
            return
        rows = self.db.query(f, limit=1_000_000)
        meta = {"workspace_id": self.settings.get("workspace_id"),
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.progress.setVisible(True)
        self.progress.setValue(5)
        self.btn_export.setEnabled(False)
        self._worker = ExportWorker(rows, base, fmt, meta)
        self._worker.progress.connect(lambda text, pct: (self.progress.setValue(pct),
                                                         self.status_lbl.setText(text)))
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_done(self, path):
        self.progress.setVisible(False)
        self.btn_export.setEnabled(True)
        self.status_lbl.setText(f"✅ 导出完成: {path}（{os.path.getsize(path):,} 字节）")
        ret = QMessageBox.information(self, "导出完成", f"已导出到:\n{path}\n\n打开所在文件夹？",
                                      QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            os.startfile(os.path.dirname(path))

    def _on_fail(self, msg):
        self.progress.setVisible(False)
        self.btn_export.setEnabled(True)
        self.status_lbl.setText(f"❌ {msg}")
        QMessageBox.critical(self, "导出失败", msg)
