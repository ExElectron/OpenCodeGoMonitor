# -*- coding: utf-8 -*-
"""选项卡 1：总览（Overview）

状态区（脱敏 Cookie / 上次同步 / 实时时钟 / 版本 / 核心设置状态）
+ 时间范围筛选 + 指标卡片 + 模型占比环形图（Tooltip / 点击联动）。
"""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDateTimeEdit, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from ocgmon import APP_VERSION
from ocgmon.ui.common import Card, KeyValueRow, badge, section_title


class OverviewTab(QWidget):
    def __init__(self, db, settings, main_window, parent=None):
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.main = main_window
        self._filters = {}           # 当前时间范围过滤（epoch）
        self._build_ui()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start(1000)
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ---- 顶部：状态区 ----
        status = QWidget()
        status.setObjectName("card")
        slay = QHBoxLayout(status)
        slay.setContentsMargins(16, 12, 16, 12)

        left = QVBoxLayout()
        left.setSpacing(2)
        self.row_cookie = KeyValueRow("脱敏 Cookie")
        self.row_last_sync = KeyValueRow("上次数据同步")
        self.row_clock = KeyValueRow("当前系统时间")
        self.row_version = KeyValueRow("软件版本")
        left.addWidget(self.row_cookie)
        left.addWidget(self.row_last_sync)
        left.addWidget(self.row_clock)
        left.addWidget(self.row_version)

        right = QVBoxLayout()
        right.setSpacing(2)
        row_sync = QHBoxLayout()
        row_sync.setContentsMargins(0, 0, 0, 0)
        row_sync.addWidget(QLabel("自动同步"))
        row_sync.addWidget(badge("—", "off"))
        self._sync_badge = row_sync.itemAt(1).widget()
        row_tray = QHBoxLayout()
        row_tray.setContentsMargins(0, 0, 0, 0)
        row_tray.addWidget(QLabel("后台驻留"))
        row_tray.addWidget(badge("—", "off"))
        self._tray_badge = row_tray.itemAt(1).widget()
        row_theme = QHBoxLayout()
        row_theme.setContentsMargins(0, 0, 0, 0)
        row_theme.addWidget(QLabel("外观主题"))
        row_theme.addWidget(badge("—", "off"))
        self._theme_badge = row_theme.itemAt(1).widget()
        row_alert = QHBoxLayout()
        row_alert.setContentsMargins(0, 0, 0, 0)
        row_alert.addWidget(QLabel("花费预警"))
        row_alert.addWidget(badge("—", "off"))
        self._alert_badge = row_alert.itemAt(1).widget()
        right.addLayout(row_sync)
        right.addLayout(row_tray)
        right.addLayout(row_theme)
        right.addLayout(row_alert)

        slay.addLayout(left, 3)
        slay.addStretch(1)
        slay.addLayout(right, 2)

        root.addWidget(status)

        # ---- 时间范围筛选 + 刷新 ----
        filter_row = QHBoxLayout()
        filter_row.addWidget(section_title("核心指标"))
        filter_row.addStretch(1)
        filter_row.addWidget(QLabel("时间范围"))
        self.range_combo = QComboBox()
        self.range_combo.addItems(["近1小时", "近24小时", "近7天", "近30天", "全部记录", "自定义时间范围"])
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        filter_row.addWidget(self.range_combo)
        self.custom_from = QDateTimeEdit(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        self.custom_from.setCalendarPopup(True)
        self.custom_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.custom_to = QDateTimeEdit(datetime.now())
        self.custom_to.setCalendarPopup(True)
        self.custom_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.custom_from.setVisible(False)
        self.custom_to.setVisible(False)
        filter_row.addWidget(self.custom_from)
        filter_row.addWidget(QLabel("→"))
        filter_row.addWidget(self.custom_to)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("primary")
        self.btn_refresh.clicked.connect(self.refresh)
        filter_row.addWidget(self.btn_refresh)
        root.addLayout(filter_row)

        # ---- 指标卡片 ----
        cards = QHBoxLayout()
        self.card_in = Card("总输入 Tokens")
        self.card_out = Card("总输出 Tokens")
        self.card_total = Card("总 Tokens")
        self.card_cost = Card("花费额度")
        self.card_top = Card("使用最多模型")
        self.card_calls = Card("调用总次数")
        for c in (self.card_in, self.card_out, self.card_total, self.card_cost,
                  self.card_top, self.card_calls):
            cards.addWidget(c, 1)
        root.addLayout(cards)

        # ---- 图表 ----
        chart_area = QWidget()
        chart_area.setObjectName("card")
        clay = QVBoxLayout(chart_area)
        clay.setContentsMargins(12, 10, 12, 10)
        clay.addWidget(section_title("模型使用占比（悬停查看详情，点击联动明细）"))
        self.chart_holder = QHBoxLayout()
        clay.addLayout(self.chart_holder, 1)
        root.addWidget(chart_area, 1)

        self.hint_lbl = QLabel("")
        self.hint_lbl.setObjectName("cardSub")
        root.addWidget(self.hint_lbl)

    # ------------------------------------------------------------------
    def _tick(self):
        self.row_clock.set_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _on_range_changed(self, idx):
        custom = idx == 5
        self.custom_from.setVisible(custom)
        self.custom_to.setVisible(custom)
        if custom:
            self.custom_from.setDateTime(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
            self.custom_to.setDateTime(datetime.now())
        self.refresh()

    def current_filters(self) -> dict:
        """当前时间范围的数据库筛选条件（供导出/联动复用）。"""
        presets = ["1h", "24h", "7d", "30d", "all", "custom"]
        p = presets[self.range_combo.currentIndex()]
        if p == "custom":
            return self.db.range_epochs("custom",
                                        self.custom_from.dateTime().toPython(),
                                        self.custom_to.dateTime().toPython())
        return self.db.range_epochs(p)

    def refresh(self):
        self._filters = self.current_filters()
        agg = self.db.aggregate(self._filters)
        self.card_in.set_value(f"{agg['input_tokens']:,}", "含缓存读/写")
        self.card_out.set_value(f"{agg['output_tokens']:,}", "")
        self.card_total.set_value(f"{agg['total_tokens']:,}",
                                  f"{agg['calls']:,} 次调用")
        self.card_cost.set_value(f"${agg['cost']:,.4f}", "美元")
        self.card_top.set_value(agg["top_model"],
                                f"{agg['top_model_calls']:,} 次 | {agg['top_model_tokens']:,} T")
        self.card_calls.set_value(f"{agg['calls']:,}",
                                  f"{agg['models']} 个模型 / {agg['keys']} 个 Key")

        # 状态区
        self.row_cookie.set_text(self.settings.masked_cookie())
        last = self.settings.get("last_sync")
        self.row_last_sync.set_text(last or "从未同步")
        self.row_version.set_text(f"v{APP_VERSION}")
        auto = self.settings.get("auto_sync")
        self._sync_badge.setText("已开启" if auto else "已关闭")
        self._sync_badge.setObjectName("badgeOk" if auto else "badgeOff")
        self._sync_badge.style().unpolish(self._sync_badge)
        self._sync_badge.style().polish(self._sync_badge)
        tray = self.settings.get("close_action") == "tray"
        self._tray_badge.setText("已开启" if tray else "已关闭")
        self._tray_badge.setObjectName("badgeOk" if tray else "badgeOff")
        self._tray_badge.style().unpolish(self._tray_badge)
        self._tray_badge.style().polish(self._tray_badge)
        alerts = any((self.settings.get(k) or 0) > 0 for k in
                     ("daily_limit", "weekly_limit", "monthly_limit"))
        self._alert_badge.setText("已开启" if alerts else "未配置")
        self._alert_badge.setObjectName("badgeOk" if alerts else "badgeOff")
        self._alert_badge.style().unpolish(self._alert_badge)
        self._alert_badge.style().polish(self._alert_badge)

        # 图表
        self._draw_donut()
        self.hint_lbl.setText(f"当前范围: {self._filters or '全部记录'} | "
                              f"数据库共 {self.db.total_records():,} 条")

    def _draw_donut(self):
        while self.chart_holder.count():
            item = self.chart_holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        share = self.db.model_share(self._filters)
        if not share:
            from PySide6.QtWidgets import QLabel
            lbl = QLabel("当前时间范围暂无数据，请先同步或调整时间范围")
            lbl.setObjectName("cardSub")
            lbl.setAlignment(Qt.AlignCenter)
            self.chart_holder.addWidget(lbl, 1)
            return
        from ocgmon.charts import build_donut
        chart = build_donut(share, self.main.palette_theme(),
                            click_handler=self._on_donut_click)
        self.chart_holder.addWidget(chart, 1)

    def _on_donut_click(self, model: str):
        """点击扇形 → 通知主窗口在记录页联动显示该模型。"""
        self.main.show_model_filter(model)
