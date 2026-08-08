# -*- coding: utf-8 -*-
"""主窗口：五选项卡 + 系统托盘 + 定时任务（自动同步 / 定时导出 / 花费预警）。"""
import datetime
import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QSystemTrayIcon,
                               QTabWidget)

from ocgmon import APP_NAME, APP_VERSION
from ocgmon import alerts
from ocgmon.config import appdata_dir
from ocgmon.theme import build_stylesheet, palette
from ocgmon.ui.analytics_tab import AnalyticsTab
from ocgmon.ui.export_tab import ExportTab
from ocgmon.ui.logs_tab import LogsTab
from ocgmon.ui.overview import OverviewTab
from ocgmon.ui.settings_tab import SettingsTab


def make_app_icon() -> QIcon:
    """程序化生成托盘/窗口图标（圆形渐变点）。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QColor(79, 140, 255)
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawEllipse(6, 6, 52, 52)
    p.setBrush(QColor(57, 217, 138))
    p.drawEllipse(38, 12, 18, 18)
    p.setBrush(QColor(255, 176, 32))
    p.drawEllipse(12, 38, 16, 16)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, db, settings):
        super().__init__()
        self.db = db
        self.settings = settings
        self._sync_worker = None
        self._export_worker = None
        self._closing = False
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — OpenCode Go 使用记录监控")
        self.setWindowIcon(make_app_icon())
        self.resize(1240, 800)

        # ---- 中央 Tab ----
        self.tabs = QTabWidget()
        self.tab_overview = OverviewTab(db, settings, self)
        self.tab_logs = LogsTab(db, settings, self)
        self.tab_analytics = AnalyticsTab(db, settings, self)
        self.tab_export = ExportTab(db, settings, self)
        self.tab_settings = SettingsTab(db, settings, self)
        self.tabs.addTab(self.tab_overview, "总览")
        self.tabs.addTab(self.tab_logs, "所有使用记录")
        self.tabs.addTab(self.tab_analytics, "高级统计")
        self.tabs.addTab(self.tab_export, "数据导出")
        self.tabs.addTab(self.tab_settings, "系统设置")
        self.tabs.setCurrentIndex(0)
        self.setCentralWidget(self.tabs)

        # ---- 状态栏 ----
        self.status = self.statusBar()
        self.sync_lbl = QLabel("未同步")
        self.status.addWidget(self.sync_lbl)
        self.sync_progress = QProgressBar()
        self.sync_progress.setMaximumWidth(260)
        self.sync_progress.setVisible(False)
        self.status.addPermanentWidget(self.sync_progress)

        # ---- 托盘 ----
        self._build_tray()

        # ---- 定时器 ----
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._on_auto_sync)
        self.sched_timer = QTimer(self)
        self.sched_timer.timeout.connect(self._on_sched_check)
        self.sched_timer.start(30_000)          # 每 30 秒检查定时导出

        self.apply_settings()

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def palette_theme(self) -> dict:
        name = self.settings.get("theme", "dark")
        return palette("dark" if name == "system" and QApplication.style().objectName() else name)

    def apply_settings(self):
        """设置变更后调用：应用主题、托盘、定时器。"""
        name = self.settings.get("theme", "dark")
        if name == "system":
            self.setStyleSheet("")
        else:
            self.setStyleSheet(build_stylesheet(name))
        self.tray.setVisible(self.settings.get("close_action") == "tray")
        # 自动同步定时器
        self.auto_timer.stop()
        if self.settings.get("auto_sync") and self.settings.has_cookie():
            minutes = int(self.settings.get("sync_interval_min", 15))
            self.auto_timer.start(minutes * 60 * 1000)
            self.sync_lbl.setText(f"自动同步已开启（每 {minutes} 分钟）")
        elif self.settings.get("auto_sync") and not self.settings.has_cookie():
            self.sync_lbl.setText("自动同步已开启，但未配置 Cookie")
        # 刷新总览状态徽章
        self.tab_overview.refresh()

    # ------------------------------------------------------------------
    # 同步
    # ------------------------------------------------------------------
    def start_sync(self):
        if self._sync_worker and self._sync_worker.isRunning():
            QMessageBox.information(self, "提示", "同步正在进行中，请稍候…")
            return
        cookie = self.settings.get("cookie", "").strip()
        wid = self.settings.get("workspace_id", "").strip()
        sid = self.settings.get("server_id_usage", "").strip()
        if not cookie:
            QMessageBox.warning(self, "未配置 Cookie",
                                "请先在『系统设置』页粘贴浏览器 Cookie（auth=…）再同步。")
            return
        if not wid:
            QMessageBox.warning(self, "未配置工作区", "请先在『系统设置』页填写工作区 ID。")
            return
        from ocgmon.fetcher import SyncWorker
        self._sync_worker = SyncWorker(cookie, wid, sid, self.db,
                                       delay_ms=int(self.settings.get("request_delay_ms", 300)))
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.stage.connect(self.sync_lbl.setText)
        self._sync_worker.finished_ok.connect(self._on_sync_done)
        self._sync_worker.failed.connect(self._on_sync_failed)
        self.sync_progress.setVisible(True)
        self.sync_progress.setRange(0, 0)
        self.sync_lbl.setText("正在同步…")
        self._sync_worker.start()

    def _on_sync_progress(self, page, n, total):
        self.sync_lbl.setText(f"正在抓取第 {page + 1} 页… 已获取 {total:,} 条")
        self.sync_progress.setRange(0, 0)

    def _on_sync_done(self, summary):
        self.sync_progress.setVisible(False)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        self.settings.update({
            "last_sync": now,
            "last_sync_ok": True,
            "last_sync_message": f"新增 {summary['inserted']:,} 条，去重 {summary['skipped']:,} 条",
        })
        self.sync_lbl.setText(f"✅ 同步完成 {now}: 新增 {summary['inserted']:,} 条，"
                              f"去重跳过 {summary['skipped']:,} 条")
        self.tray.showMessage("同步完成",
                              f"新增 {summary['inserted']:,} 条记录，去重 {summary['skipped']:,} 条",
                              QSystemTrayIcon.Information, 5000)
        self._after_data_change()
        self._check_alerts()

    def _on_sync_failed(self, message, kind):
        self.sync_progress.setVisible(False)
        self.sync_lbl.setText(f"❌ 同步失败（{kind}）")
        self.settings.update({"last_sync_ok": False, "last_sync_message": message})
        if kind == "cookie":
            QMessageBox.critical(self, "Cookie 失效", message)
        elif kind == "server_id":
            ret = QMessageBox.warning(self, "Server Function ID 失效", message,
                                      QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                self.tabs.setCurrentWidget(self.tab_settings)
                self.tab_settings._recover_server_id()
        else:
            QMessageBox.critical(self, "同步失败", message)

    def _after_data_change(self):
        self.tab_overview.refresh()
        self.tab_logs.reload()
        self.tab_analytics.reload_options()
        self.tab_analytics._apply()
        self.tab_export.reload_options()

    def _check_alerts(self):
        messages = alerts.check_thresholds(self.db, self.settings)
        if not messages:
            return
        for m in messages:
            if alerts._dedup_key(self.db, m["dedup_key"]):
                continue
            alerts.mark_notified(self.db, m["dedup_key"])
            text = alerts.format_alert(m)
            self.tray.showMessage("花费预警", text, QSystemTrayIcon.Warning, 10000)
            result = alerts.send_webhook(self.settings, m)
            if result and result != "ok":
                self.sync_lbl.setText(f"预警 Webhook 发送失败: {result}")

    # ------------------------------------------------------------------
    # Cookie 校验
    # ------------------------------------------------------------------
    def validate_cookie_async(self):
        """异步校验 Cookie 有效性；完成后弹窗提示。"""
        from ocgmon.fetcher import UsageFetcher
        cookie = self.settings.get("cookie", "").strip()
        wid = self.settings.get("workspace_id", "").strip()
        if not cookie:
            return None
        import threading

        def work():
            try:
                return UsageFetcher(cookie, wid, "x", delay_ms=200).validate_cookie()
            except Exception:
                return False

        def done(ok):
            if ok:
                QMessageBox.information(self, "Cookie 有效", "Cookie 校验通过 ✅（HTTP 200）")
            else:
                QMessageBox.warning(self, "Cookie 可能已失效",
                                    "访问 usage 页面未返回 200，Cookie 可能已过期或工作区错误。")

        res = {}
        def _worker():
            res["r"] = work()
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        timer = QTimer(self)
        def poll():
            if not t.is_alive():
                timer.stop()
                done(res.get("r"))
        timer.timeout.connect(poll)
        timer.start(100)
        return True

    # ------------------------------------------------------------------
    # 定时任务
    # ------------------------------------------------------------------
    def _on_auto_sync(self):
        if not self.settings.get("auto_sync"):
            return
        if self._sync_worker and self._sync_worker.isRunning():
            return
        self.start_sync()

    def _on_sched_check(self):
        s = self.settings
        if not s.get("sched_export"):
            return
        folder = (s.get("sched_folder") or "").strip()
        if not folder or not os.path.isdir(folder):
            return
        now = datetime.datetime.now()
        period = s.get("sched_period", "weekly")
        hour = int(s.get("sched_hour", 8))
        if now.hour != hour:
            return
        today_key = f"{now:%Y-%m-%d}"
        if period == "weekly":
            want_wd = int(s.get("sched_weekday", 0))
            if now.weekday() != want_wd:
                return
            mark = f"weekly_{want_wd}_{today_key}"
        else:
            want_day = int(s.get("sched_month_day", 1))
            if now.day != want_day:
                return
            mark = f"monthly_{want_day}_{today_key}"
        if self.db.meta_get(f"sched_done_{mark}") == "1":
            return
        self.db.meta_set(f"sched_done_{mark}", "1")
        # 后台执行导出
        f = {}
        rows = self.db.query(f, limit=1_000_000)
        path = os.path.join(folder, f"opencode_usage_report_{now:%Y%m%d_%H%M%S}.xlsx")
        from ocgmon.exporter import ExportWorker
        self._sched_export_worker = ExportWorker(
            rows, path, "xlsx",
            {"workspace_id": s.get("workspace_id"), "exported_at": now.strftime("%Y-%m-%d %H:%M:%S")})
        self._sched_export_worker.finished_ok.connect(
            lambda p: (self.tray.showMessage("定时导出", f"报表已生成:\n{p}",
                                             QSystemTrayIcon.Information, 8000),
                       self.sync_lbl.setText(f"定时导出完成: {p}")))
        self._sched_export_worker.failed.connect(
            lambda e: self.tray.showMessage("定时导出失败", e, QSystemTrayIcon.Warning, 8000))
        self._sched_export_worker.start()

    # ------------------------------------------------------------------
    # 跨页联动
    # ------------------------------------------------------------------
    def show_model_filter(self, model: str):
        """总览环形图点击 → 记录页按模型过滤。"""
        self.tabs.setCurrentWidget(self.tab_logs)
        self.tab_logs.search_box.setText(model)
        self.tab_logs._apply_filters()

    # ------------------------------------------------------------------
    # 托盘
    # ------------------------------------------------------------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} v{APP_VERSION}")
        menu = QMenu()
        act_show = QAction("显示主界面", self)
        act_show.triggered.connect(self.show_and_raise)
        act_sync = QAction("立即同步", self)
        act_sync.triggered.connect(self.start_sync)
        self.act_pause = QAction("暂停自动同步", self)
        self.act_pause.setCheckable(True)
        self.act_pause.triggered.connect(self._toggle_pause)
        act_quit = QAction("退出程序", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_show)
        menu.addAction(act_sync)
        menu.addSeparator()
        menu.addAction(self.act_pause)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.show_and_raise()

    def _toggle_pause(self, paused: bool):
        if paused:
            self.auto_timer.stop()
            self.sync_lbl.setText("自动同步已暂停")
        else:
            self.apply_settings()

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self._closing = True
        self.tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        if self.settings.get("close_action") == "tray" and not self._closing:
            event.ignore()
            self.hide()
            self.tray.showMessage("已在后台驻留",
                                  f"{APP_NAME} 已最小化到系统托盘，右键图标可操作。",
                                  QSystemTrayIcon.Information, 3000)
        else:
            self._closing = True
            self.tray.hide()
            event.accept()
