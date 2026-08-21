#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCode Go 使用记录监控 — 程序入口

用法:
    python main.py

打包版（PyInstaller --windowed）无控制台，任何未捕获异常都会写入
%APPDATA%/OCGMonitor/error.log，便于排查。
"""
import os
import sys
import traceback


def _log_crash(exc: BaseException):
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "OCGMonitor")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as f:
            f.write("---- %s ----\n" % __import__("datetime").datetime.now().isoformat())
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        pass


def main():
    try:
        _run()
    except Exception as e:
        _log_crash(e)
        raise


def _run():
    from PySide6.QtWidgets import QApplication

    from ocgmon import APP_TITLE, APP_VERSION
    from ocgmon.config import Settings, appdata_dir
    from ocgmon.db import Database
    from ocgmon.main_window import MainWindow, make_app_icon
    from ocgmon.theme import build_stylesheet

    os.makedirs(appdata_dir(), exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(make_app_icon())

    settings = Settings()
    # 数据库路径固定为 %APPDATA%/OCGMonitor/monitor.db（Linux 为 XDG 数据目录）
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
