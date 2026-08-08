#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCode Go 使用记录监控 — 程序入口

用法:
    python main.py
"""
import sys

from PySide6.QtWidgets import QApplication

from ocgmon import APP_TITLE, APP_VERSION
from ocgmon.config import Settings, appdata_dir
from ocgmon.db import Database
from ocgmon.main_window import MainWindow, make_app_icon
from ocgmon.theme import build_stylesheet


def main():
    import os
    os.makedirs(appdata_dir(), exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(make_app_icon())

    settings = Settings()
    # 数据库路径固定为 %APPDATA%/OCGMonitor/monitor.db
    from ocgmon.config import db_path
    db = Database(db_path())

    # 主题（跟随系统时用原生样式）
    theme = settings.get("theme", "dark")
    if theme != "system":
        app.setStyleSheet(build_stylesheet(theme))

    win = MainWindow(db, settings)
    win.show()
    exit_code = app.exec()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
