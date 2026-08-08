# -*- coding: utf-8 -*-
"""内置 SQL 终端：直接对 SQLite 执行 SELECT，结果渲染表格并可导出。"""
import sqlite3

from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

DEFAULT_SQL = """-- 常用示例（只读 SELECT）：
-- 1) 各模型成本排行
-- SELECT model_name AS 模型, COUNT(*) AS 调用次数,
--        SUM(total_tokens) AS 总Token, ROUND(SUM(cost),4) AS 成本美元
-- FROM usage_records GROUP BY model_name ORDER BY 成本美元 DESC;

SELECT model_name AS 模型, COUNT(*) AS 调用次数,
       SUM(total_tokens) AS 总Token, ROUND(SUM(cost), 4) AS 成本美元
FROM usage_records
GROUP BY model_name
ORDER BY 成本美元 DESC
LIMIT 20;
"""


class SqlTerminalDialog(QDialog):
    def __init__(self, db, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SQL 查询终端（只读）")
        self.resize(860, 560)
        self.db = db
        self.main = main_window
        self._last_rows = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("对本地 SQLite 执行 SELECT（表: usage_records / meta / presets / tags）。"
                             "写操作被拒绝。"))
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(DEFAULT_SQL)
        self.editor.setPlaceholderText("SELECT ...")
        self.editor.setMaximumHeight(150)
        lay.addWidget(self.editor)

        row = QHBoxLayout()
        self.btn_run = QPushButton("执行")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.run_sql)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self.editor.clear)
        self.btn_export = QPushButton("导出结果…")
        self.btn_export.clicked.connect(self.export_result)
        self.btn_export.setEnabled(False)
        self.status_lbl = QLabel("")
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_export)
        row.addStretch(1)
        row.addWidget(self.status_lbl)
        lay.addLayout(row)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

    def run_sql(self):
        sql = self.editor.toPlainText().strip().rstrip(";")
        if not sql:
            return
        if not sql.lower().lstrip().startswith("select"):
            QMessageBox.warning(self, "仅支持 SELECT", "为安全起见，只允许执行 SELECT 查询。")
            return
        try:
            import sqlite3 as _s
            with _s.connect(self.db._path, timeout=30) as conn:
                cur = conn.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
        except Exception as e:
            QMessageBox.critical(self, "SQL 执行失败", str(e))
            return
        self._last_rows = [dict(zip(cols, r)) for r in rows]
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(cols)
        for ri, r in enumerate(rows):
            for ci, v in enumerate(r):
                item = QTableWidgetItem(str(v) if v is not None else "")
                item.setFlags(item.flags() & ~2)   # 只读
                self.table.setItem(ri, ci, item)
        self.status_lbl.setText(f"返回 {len(rows)} 行 × {len(cols)} 列")

    def export_result(self):
        if not self._last_rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出查询结果",
                                              "sql_result.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            import pandas as pd
            pd.DataFrame(self._last_rows).to_csv(path, index=False, encoding="utf-8-sig")
            QMessageBox.information(self, "导出成功", f"已导出 {len(self._last_rows)} 行到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
