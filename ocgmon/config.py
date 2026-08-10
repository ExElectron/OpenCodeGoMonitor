# -*- coding: utf-8 -*-
"""配置持久化。

平台路径约定：
- Windows：%APPDATA%/OCGMonitor/（config.json / monitor.db / exports 同目录）
- Linux（XDG 规范）：配置在 ~/.config/OCGMonitor/，数据在 ~/.local/share/OCGMonitor/
首次在 Linux 运行时会把旧的 ~/OCGMonitor 数据自动迁移到 XDG 目录。

注意：Cookie 属于敏感凭据，明文保存在本机配置文件中（与浏览器保存 Cookie 同级别），
请勿将 config.json 分享给他人。
"""
import json
import os
import shutil
import threading
import time

from ocgmon import APP_NAME, DEFAULT_WORKSPACE, SERVER_ID_USAGE

_LOCK = threading.Lock()

DEFAULTS = {
    # ---- 数据同步 ----
    "cookie": "",                       # 浏览器复制的完整 Cookie 行（auth=...）
    "workspace_id": DEFAULT_WORKSPACE,
    "server_id_usage": SERVER_ID_USAGE,
    "auto_sync": False,                 # 后台自动同步开关
    "sync_interval_min": 15,            # 同步间隔（分钟）：5/15/30/60
    "request_delay_ms": 300,            # 分页请求间隔（防限流）
    # ---- 界面 ----
    "theme": "dark",                    # dark / light / system
    "close_action": "tray",             # exit / tray（点关闭按钮的行为）
    "show_tray_balloons": True,
    # ---- 花费预警 ----
    "daily_limit": 0.0,                 # 0 = 不启用
    "weekly_limit": 0.0,
    "monthly_limit": 0.0,
    "webhook_type": "none",             # none / dingtalk / feishu / wecom / telegram / custom
    "webhook_url": "",
    # ---- 定时导出 ----
    "sched_export": False,
    "sched_period": "weekly",           # weekly / monthly
    "sched_weekday": 0,                 # 0=周一 ... 6=周日
    "sched_month_day": 1,               # 每月第几天
    "sched_hour": 8,                    # 每天几时
    "sched_folder": "",
    # ---- 运行时状态（也存这里，方便查看）----
    "last_sync": None,                  # ISO 时间
    "last_sync_ok": False,
    "last_sync_message": "",
    "last_import": None,
}


def _legacy_dir() -> str:
    """Linux 上早期版本写入的 ~/OCGMonitor 目录（供迁移）。"""
    p = os.path.join(os.path.expanduser("~"), APP_NAME)
    return p if os.path.isdir(p) else ""


def _migrate_if_needed(target: str, name: str) -> None:
    """把旧 ~/OCGMonitor 中的数据迁移到 XDG 目标目录（仅 Linux、仅首次）。"""
    if os.name == "nt":
        return
    src = os.path.join(_legacy_dir(), name) if _legacy_dir() else ""
    if not src or not os.path.exists(src) or os.path.exists(target):
        return
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
    except OSError:
        pass  # 迁移失败不影响启动，仅本次会话读不到旧数据


def config_dir() -> str:
    """配置目录：Windows=%APPDATA%/OCGMonitor；Linux=$XDG_CONFIG_HOME/OCGMonitor。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def data_dir() -> str:
    """数据目录：Windows=%APPDATA%/OCGMonitor；Linux=$XDG_DATA_HOME/OCGMonitor。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def appdata_dir() -> str:
    """兼容入口：返回数据目录。"""
    return data_dir()


def db_path() -> str:
    target = os.path.join(data_dir(), "monitor.db")
    _migrate_if_needed(target, "monitor.db")
    return target


def config_path() -> str:
    target = os.path.join(config_dir(), "config.json")
    _migrate_if_needed(target, "config.json")
    return target


def exports_dir() -> str:
    target = os.path.join(data_dir(), "exports")
    _migrate_if_needed(target, "exports")
    os.makedirs(target, exist_ok=True)
    return target


class Settings:
    """轻量 JSON 配置存储（线程安全）。"""

    def __init__(self, path: str = None):
        self._path = path or config_path()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._data.update({k: v for k, v in data.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except Exception as e:  # 配置损坏时回退默认
            print(f"[config] 读取配置失败，使用默认值: {e}")

    def save(self):
        with _LOCK:
            try:
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[config] 保存配置失败: {e}")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value, save=True):
        self._data[key] = value
        if save:
            self.save()

    def update(self, mapping: dict, save=True):
        self._data.update(mapping)
        if save:
            self.save()

    def as_dict(self) -> dict:
        return dict(self._data)

    # ---- 便捷方法 ----
    def masked_cookie(self) -> str:
        """脱敏 Cookie：仅显示前4位和后4位（如 sess_****abcd）。"""
        c = (self._data.get("cookie") or "").strip()
        if not c:
            return "未配置"
        if "=" in c:
            c = c.split("=", 1)[1]
        if len(c) <= 8:
            return c[:2] + "****"
        return c[:4] + "****" + c[-4:]

    def has_cookie(self) -> bool:
        return bool((self._data.get("cookie") or "").strip())


def mask_key(key_id: str) -> str:
    """API Key 脱敏：key_01KZXXXXXXXXXXXXXXXXW96 → key_01KZ****W96"""
    if not key_id:
        return "-"
    if len(key_id) <= 10:
        return key_id[:4] + "****"
    return key_id[:7] + "****" + key_id[-4:]


def now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
