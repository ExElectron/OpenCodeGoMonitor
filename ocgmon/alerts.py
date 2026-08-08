# -*- coding: utf-8 -*-
"""花费预警与配额管理。

- 每日/每周/每月 Cost 限额红线
- 达到阈值（80%、100%）触发：托盘气泡（GUI 侧）+ Webhook（钉钉/飞书/企业微信/Telegram/自定义）
- 同一天内同一阈值只通知一次（meta 表记录）
"""
import datetime
import json
import time

import requests


def _period_start(period: str) -> int:
    """返回周期起点 epoch（本地时间）。period: day/week/month"""
    now = datetime.datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start -= datetime.timedelta(days=start.weekday())   # 周一起
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def check_thresholds(db, settings) -> list:
    """检查各周期限额，返回需要通知的消息列表 [{level, period, spent, limit, pct, message}]。

    每条消息带 dedup 键（period + 档位），由调用方决定是否已通知过。
    """
    messages = []
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for period, key in (("day", "daily_limit"), ("week", "weekly_limit"), ("month", "monthly_limit")):
        limit = float(settings.get(key) or 0)
        if limit <= 0:
            continue
        spent = db.spend_since(_period_start(period))
        pct = spent / limit * 100
        for level, marker in ((80, "80%"), (100, "100%")):
            if pct >= level:
                messages.append({
                    "level": level, "marker": marker, "period": period,
                    "spent": spent, "limit": limit, "pct": pct, "time": now,
                    "dedup_key": f"{period}_{marker}_{now[:10]}",
                })
    return messages


def _dedup_key(db, key: str) -> bool:
    last = db.meta_get(f"alert_notify_{key}")
    return last == "1"


def mark_notified(db, key: str):
    db.meta_set(f"alert_notify_{key}", "1")


def send_webhook(settings, message: dict) -> str:
    """发送 Webhook 通知。返回成功/错误文本；webhook 未配置时返回 None。"""
    url = (settings.get("webhook_url") or "").strip()
    kind = settings.get("webhook_type") or "none"
    if kind == "none" or not url:
        return None
    period_cn = {"day": "今日", "week": "本周", "month": "本月"}.get(message["period"], message["period"])
    text = (f"🚨 OpenCode Go 花费预警（达 {message['marker']}）\n"
            f"{period_cn}花费: ${message['spent']:.4f} / 限额 ${message['limit']:.2f} "
            f"({message['pct']:.1f}%)\n时间: {message['time']}")
    try:
        if kind == "dingtalk":
            payload = {"msgtype": "text", "text": {"content": text}}
            headers = {"Content-Type": "application/json"}
        elif kind == "feishu":
            payload = {"msg_type": "text", "content": {"text": text}}
            headers = {"Content-Type": "application/json"}
        elif kind == "wecom":
            payload = {"msgtype": "text", "text": {"content": text}}
            headers = {"Content-Type": "application/json"}
        elif kind == "telegram":
            token, chat = "", ""
            if "?" in url:
                url, qs = url.split("?", 1)
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                token, chat = params.get("token", ""), params.get("chat_id", "")
            if not token and len(url.rsplit("/", 3)) >= 3:
                token = url.rsplit("/", 3)[-2]
            payload, headers = None, None
            send_url = f"https://api.telegram.org/bot{token}/sendMessage"
            r = requests.post(send_url, json={"chat_id": chat, "text": text}, timeout=20)
            return "ok" if r.ok else f"telegram HTTP {r.status_code}"
        else:  # custom
            payload, headers = {"text": text}, {"Content-Type": "application/json"}
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        return "ok" if r.ok else f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"发送失败: {e}"


def send_test_webhook(settings) -> str:
    """发送测试通知。"""
    msg = {"level": 0, "marker": "测试", "period": "test", "spent": 0, "limit": 0,
           "pct": 0, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    return send_webhook(settings, msg)


def format_alert(message: dict) -> str:
    period_cn = {"day": "今日", "week": "本周", "month": "本月"}.get(message["period"], message["period"])
    return (f"⚠️ 花费预警（达 {message['marker']}）\n"
            f"{period_cn}花费 ${message['spent']:.4f}，已达限额 ${message['limit']:.2f} 的 "
            f"{message['pct']:.1f}%\n{message['time']}")
