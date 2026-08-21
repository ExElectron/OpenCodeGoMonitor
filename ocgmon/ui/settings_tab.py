# -*- coding: utf-8 -*-
"""选项卡 5：系统设置（Settings）

- 版本信息 + 检查更新
- Cookie / 工作区 / Server Function ID（支持一键恢复）
- 后台自动同步（间隔可调）
- 窗口关闭行为（退出 / 最小化到托盘）
- 花费预警（日/周/月限额 + Webhook 通知）
- 定时导出报表
- 外观主题
"""
import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton,
                               QVBoxLayout, QWidget)

from ocgmon import APP_NAME, APP_VERSION
from ocgmon.alerts import send_test_webhook
from ocgmon.ui.common import badge, section_title

WEBHOOK_TYPES = [
    ("none", "不使用 Webhook"),
    ("dingtalk", "钉钉机器人"),
    ("feishu", "飞书机器人"),
    ("wecom", "企业微信机器人"),
    ("telegram", "Telegram Bot (URL 带 ?token=&chat_id=)"),
    ("custom", "自定义 JSON 文本"),
]

WEBHOOK_HINTS = {
    "dingtalk": "https://oapi.dingtalk.com/robot/send?access_token=…",
    "feishu": "https://open.feishu.cn/open-apis/bot/v2/hook/…",
    "wecom": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…",
    "telegram": "https://api.telegram.org/bot<token>/sendMessage?chat_id=<id>",
    "custom": "POST JSON: {\"text\": \"…\"}",
}


class SettingsTab(QWidget):
    def __init__(self, db, settings, main_window, parent=None):
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.main = main_window
        self._build_ui()
        self.load_settings()

    # ------------------------------------------------------------------
    def _group(self, title: str, layout) -> QGroupBox:
        g = QGroupBox(title)
        g.setLayout(layout)
        return g

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ============ 1. 版本 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel(f"{APP_NAME} v{APP_VERSION}"))
        self.btn_check_update = QPushButton("检查更新")
        self.btn_check_update.clicked.connect(self._check_update)
        row.addWidget(self.btn_check_update)
        row.addStretch(1)
        vbox.addLayout(row)
        root.addWidget(self._group("软件信息", vbox))

        # ============ 2. 数据同步 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Cookie (auth=…)"))
        self.cookie_edit = QLineEdit()
        self.cookie_edit.setEchoMode(QLineEdit.Password)
        self.cookie_edit.setPlaceholderText("浏览器 F12 → Network → 请求头 Cookie 整行粘贴")
        row.addWidget(self.cookie_edit, 1)
        self.btn_save_cookie = QPushButton("保存 Cookie")
        self.btn_save_cookie.setObjectName("primary")
        self.btn_save_cookie.clicked.connect(self._save_cookie)
        row.addWidget(self.btn_save_cookie)
        self.btn_import_cookie = QPushButton("从文件导入…")
        self.btn_import_cookie.setToolTip("从本地文本文件读取 Cookie（文件首行）")
        self.btn_import_cookie.clicked.connect(self._import_cookie)
        row.addWidget(self.btn_import_cookie)
        vbox.addLayout(row)
        self.cookie_preview = QLabel()
        self.cookie_preview.setObjectName("cardSub")
        vbox.addWidget(self.cookie_preview)

        row = QHBoxLayout()
        row.addWidget(QLabel("工作区 ID"))
        self.workspace_edit = QLineEdit()
        row.addWidget(self.workspace_edit, 1)
        row.addWidget(QLabel("Server Function ID"))
        self.server_id_edit = QLineEdit()
        self.server_id_edit.setToolTip("usage.list 函数 ID，前端发版后可能失效")
        row.addWidget(self.server_id_edit, 1)
        self.btn_recover_id = QPushButton("恢复函数ID")
        self.btn_recover_id.setToolTip("从前端 bundle 自动重新提取（需有效 Cookie）")
        self.btn_recover_id.clicked.connect(self._recover_server_id)
        row.addWidget(self.btn_recover_id)
        vbox.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("请求间隔"))
        self.delay_combo = QComboBox()
        self.delay_combo.addItems(["200ms", "300ms", "500ms", "1s"])
        row.addWidget(self.delay_combo)
        row.addWidget(QLabel("（防限流，文档建议 200-500ms）"))
        row.addStretch(1)
        self.btn_sync_now = QPushButton("立即同步")
        self.btn_sync_now.clicked.connect(self.main.start_sync)
        row.addWidget(self.btn_sync_now)
        vbox.addLayout(row)
        root.addWidget(self._group("数据同步", vbox))

        # ============ 3. 自动同步 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        self.chk_auto = self._check("开启后台自动同步")
        row.addWidget(self.chk_auto)
        row.addWidget(QLabel("间隔"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["每5分钟", "每15分钟", "每30分钟", "每1小时"])
        row.addWidget(self.interval_combo)
        row.addStretch(1)
        vbox.addLayout(row)
        root.addWidget(self._group("自动同步", vbox))

        # ============ 4. 窗口行为 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        self.rb_close_exit = QRadioButton("直接退出程序")
        self.rb_close_tray = QRadioButton("最小化到系统托盘（驻留后台）")
        self.rb_close_tray.setChecked(True)
        row.addWidget(self.rb_close_exit)
        row.addWidget(self.rb_close_tray)
        row.addStretch(1)
        vbox.addLayout(row)
        root.addWidget(self._group("关闭按钮行为", vbox))

        # ============ 5. 外观 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        self.rb_theme_dark = QRadioButton("暗色")
        self.rb_theme_light = QRadioButton("亮色")
        self.rb_theme_system = QRadioButton("跟随系统")
        self.rb_theme_dark.setChecked(True)
        row.addWidget(self.rb_theme_dark)
        row.addWidget(self.rb_theme_light)
        row.addWidget(self.rb_theme_system)
        row.addStretch(1)
        self.btn_apply_theme = QPushButton("应用主题")
        self.btn_apply_theme.clicked.connect(self._apply_theme)
        row.addWidget(self.btn_apply_theme)
        vbox.addLayout(row)
        root.addWidget(self._group("外观主题", vbox))

        # ============ 6. 花费预警 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        for label, key, in (("每日限额 $", "daily_limit"), ("每周限额 $", "weekly_limit"),
                            ("每月限额 $", "monthly_limit")):
            row.addWidget(QLabel(label))
            sb = QDoubleSpinBox()
            sb.setRange(0, 1_000_000)
            sb.setDecimals(2)
            sb.setPrefix("$")
            sb.setSpecialValueText("不启用")
            setattr(self, f"sb_{key}", sb)
            row.addWidget(sb)
        row.addStretch(1)
        vbox.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Webhook 类型"))
        self.webhook_combo = QComboBox()
        for val, label in WEBHOOK_TYPES:
            self.webhook_combo.addItem(label, val)
        row.addWidget(self.webhook_combo)
        row.addWidget(QLabel("Webhook URL"))
        self.webhook_url = QLineEdit()
        self.webhook_url.setPlaceholderText(WEBHOOK_HINTS["dingtalk"])
        row.addWidget(self.webhook_url, 1)
        self.btn_test_webhook = QPushButton("发送测试通知")
        self.btn_test_webhook.clicked.connect(self._test_webhook)
        row.addWidget(self.btn_test_webhook)
        vbox.addLayout(row)
        vbox.addWidget(QLabel("达 80% / 100% 阈值时：托盘气泡提醒 + Webhook 推送（同一天同一档位仅提醒一次）"))
        root.addWidget(self._group("花费预警与配额", vbox))

        # ============ 7. 定时导出 ============
        vbox = QVBoxLayout()
        row = QHBoxLayout()
        self.chk_sched = self._check("开启定时自动导出 Excel 报表")
        row.addWidget(self.chk_sched)
        self.sched_period_combo = QComboBox()
        self.sched_period_combo.addItems(["每周", "每月"])
        row.addWidget(self.sched_period_combo)
        self.sched_wd_combo = QComboBox()
        self.sched_wd_combo.addItems(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
        row.addWidget(self.sched_wd_combo)
        self.sched_day_spin = self._spin(1, 28)
        row.addWidget(QLabel("每月第"))
        row.addWidget(self.sched_day_spin)
        row.addWidget(QLabel("日"))
        row.addWidget(QLabel("执行时间"))
        self.sched_hour_combo = QComboBox()
        self.sched_hour_combo.addItems([f"{h:02d}:00" for h in range(0, 24)])
        row.addWidget(self.sched_hour_combo)
        row.addStretch(1)
        vbox.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("保存文件夹"))
        self.sched_folder = QLineEdit()
        row.addWidget(self.sched_folder, 1)
        self.btn_sched_browse = QPushButton("浏览…")
        self.btn_sched_browse.clicked.connect(self._browse_sched_folder)
        row.addWidget(self.btn_sched_browse)
        vbox.addLayout(row)
        root.addWidget(self._group("定时导出", vbox))

        # ============ 保存 ============
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_save = QPushButton("保存全部设置")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self.save_settings)
        row.addWidget(self.btn_save)
        self.saved_lbl = QLabel("")
        self.saved_lbl.setObjectName("badgeOk")
        row.addWidget(self.saved_lbl)
        root.addLayout(row)
        root.addStretch(1)

    @staticmethod
    def _check(text: str):
        from PySide6.QtWidgets import QCheckBox
        return QCheckBox(text)

    @staticmethod
    def _spin(lo, hi):
        from PySide6.QtWidgets import QSpinBox
        s = QSpinBox()
        s.setRange(lo, hi)
        return s

    # ------------------------------------------------------------------
    # 加载 / 保存
    # ------------------------------------------------------------------
    def load_settings(self):
        s = self.settings
        self.cookie_edit.setText(s.get("cookie", ""))
        self.workspace_edit.setText(s.get("workspace_id", ""))
        self.server_id_edit.setText(s.get("server_id_usage", ""))
        self.cookie_preview.setText(f"当前脱敏: {s.masked_cookie()}")
        self.chk_auto.setChecked(bool(s.get("auto_sync")))
        self.interval_combo.setCurrentIndex({5: 0, 15: 1, 30: 2, 60: 3}.get(s.get("sync_interval_min"), 1))
        delay = s.get("request_delay_ms", 300)
        self.delay_combo.setCurrentIndex({200: 0, 300: 1, 500: 2, 1000: 3}.get(delay, 1))
        self.rb_close_tray.setChecked(s.get("close_action") == "tray")
        self.rb_close_exit.setChecked(s.get("close_action") != "tray")
        theme = s.get("theme", "dark")
        self.rb_theme_dark.setChecked(theme == "dark")
        self.rb_theme_light.setChecked(theme == "light")
        self.rb_theme_system.setChecked(theme == "system")
        for key in ("daily_limit", "weekly_limit", "monthly_limit"):
            getattr(self, f"sb_{key}").setValue(float(s.get(key) or 0))
        wt = s.get("webhook_type", "none")
        for i in range(self.webhook_combo.count()):
            if self.webhook_combo.itemData(i) == wt:
                self.webhook_combo.setCurrentIndex(i)
                break
        self.webhook_url.setText(s.get("webhook_url", ""))
        self.chk_sched.setChecked(bool(s.get("sched_export")))
        self.sched_period_combo.setCurrentIndex(0 if s.get("sched_period") == "weekly" else 1)
        self.sched_wd_combo.setCurrentIndex(int(s.get("sched_weekday", 0)))
        self.sched_day_spin.setValue(int(s.get("sched_month_day", 1)))
        hour = int(s.get("sched_hour", 8))
        if 0 <= hour < 24:
            self.sched_hour_combo.setCurrentIndex(hour)
        self.sched_folder.setText(s.get("sched_folder", ""))

    def save_settings(self):
        s = self.settings
        cookie = self.cookie_edit.text().strip()
        s.set("cookie", cookie)
        s.set("workspace_id", self.workspace_edit.text().strip())
        s.set("server_id_usage", self.server_id_edit.text().strip())
        s.set("auto_sync", self.chk_auto.isChecked())
        s.set("sync_interval_min", {0: 5, 1: 15, 2: 30, 3: 60}[self.interval_combo.currentIndex()])
        s.set("request_delay_ms", {0: 200, 1: 300, 2: 500, 3: 1000}[self.delay_combo.currentIndex()])
        s.set("close_action", "tray" if self.rb_close_tray.isChecked() else "exit")
        theme = ("dark" if self.rb_theme_dark.isChecked()
                 else "light" if self.rb_theme_light.isChecked() else "system")
        s.set("theme", theme)
        for key in ("daily_limit", "weekly_limit", "monthly_limit"):
            s.set(key, getattr(self, f"sb_{key}").value())
        s.set("webhook_type", self.webhook_combo.currentData())
        s.set("webhook_url", self.webhook_url.text().strip())
        s.set("sched_export", self.chk_sched.isChecked())
        s.set("sched_period", "weekly" if self.sched_period_combo.currentIndex() == 0 else "monthly")
        s.set("sched_weekday", self.sched_wd_combo.currentIndex())
        s.set("sched_month_day", self.sched_day_spin.value())
        s.set("sched_hour", self.sched_hour_combo.currentIndex())
        s.set("sched_folder", self.sched_folder.text().strip())
        s.save()
        self.main.apply_settings()
        self.cookie_preview.setText(f"当前脱敏: {s.masked_cookie()}")
        self.saved_lbl.setText("✓ 已保存")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: self.saved_lbl.setText(""))

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def _save_cookie(self):
        self.save_settings()
        ok = self.main.validate_cookie_async()
        if ok is None:
            QMessageBox.information(self, "Cookie 已保存", "Cookie 已保存，可在『立即同步』时验证有效性。")

    def _import_cookie(self):
        from PySide6.QtWidgets import QFileDialog
        cand, _ = QFileDialog.getOpenFileName(self, "选择包含 Cookie 的文本文件",
                                              "", "文本文件 (*.txt);;所有文件 (*)")
        if not cand:
            return
        try:
            with open(cand, encoding="utf-8", errors="replace") as f:
                cookie = f.read().strip().splitlines()[0].strip()
        except Exception as e:
            QMessageBox.critical(self, "读取失败", str(e))
            return
        if not cookie:
            QMessageBox.warning(self, "文件为空", "cookie.txt 内容为空")
            return
        self.cookie_edit.setText(cookie)
        self.cookie_preview.setText(f"已导入，脱敏显示: {cookie[:4] + '****' + cookie[-4:] if len(cookie) > 8 else '****'}")
        self.save_settings()
        QMessageBox.information(self, "导入成功", "Cookie 已导入并保存。建议立即点击『立即同步』验证有效性。")

    def _recover_server_id(self):
        from ocgmon.fetcher import extract_server_ids, CookieInvalidError, FetchError
        cookie = self.settings.get("cookie", "")
        if not cookie:
            QMessageBox.warning(self, "提示", "请先保存有效 Cookie 再恢复函数 ID")
            return
        self.btn_recover_id.setEnabled(False)
        self.btn_recover_id.setText("正在提取…")

        def work():
            try:
                return extract_server_ids(cookie, self.workspace_edit.text().strip())
            except (CookieInvalidError, FetchError) as e:
                return str(e)

        def done(result):
            self.btn_recover_id.setEnabled(True)
            self.btn_recover_id.setText("恢复函数ID")
            if isinstance(result, dict):
                new_id = result.get("usage.list", "")
                if new_id:
                    self.server_id_edit.setText(new_id)
                    self.settings.set("server_id_usage", new_id)
                    QMessageBox.information(self, "恢复成功",
                                            f"已提取新的 Server Function ID:\n{new_id}\n"
                                            f"（getCosts: {result.get('getCosts') or '未找到'}）")
                else:
                    QMessageBox.warning(self, "未找到", "bundle 中未找到函数 ID，可能页面结构已变化")
            else:
                QMessageBox.critical(self, "提取失败", result)

        import threading
        res = {}
        def _worker():
            res["r"] = work()
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        # 用 QTimer 轮询线程结果，避免跨线程操作 UI
        from PySide6.QtCore import QTimer
        timer = QTimer(self)
        def poll():
            if t.is_alive():
                return
            timer.stop()
            done(res.get("r"))
        timer.timeout.connect(poll)
        timer.start(100)

    def _check_update(self):
        QMessageBox.information(
            self, "检查更新",
            f"当前版本: v{APP_VERSION}\n\n本工具为本地应用，暂无在线更新源。\n"
            "如需更新，请重新获取最新源码运行。")

    def _apply_theme(self):
        theme = ("dark" if self.rb_theme_dark.isChecked()
                 else "light" if self.rb_theme_light.isChecked() else "system")
        self.settings.set("theme", theme)
        self.main.apply_settings()

    def _test_webhook(self):
        self.save_settings()
        msg = send_test_webhook(self.settings)
        if msg is None:
            QMessageBox.warning(self, "未配置", "请选择 Webhook 类型并填写 URL")
        elif msg == "ok":
            QMessageBox.information(self, "发送成功", "测试通知已发送 ✅")
        else:
            QMessageBox.critical(self, "发送失败", msg)

    def _browse_sched_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择定时导出文件夹",
                                                  self.sched_folder.text() or os.path.expanduser("~"))
        if folder:
            self.sched_folder.setText(folder)
