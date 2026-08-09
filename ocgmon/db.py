# -*- coding: utf-8 -*-
"""SQLite 数据层：schema、防重写入、查询、标签、预设。

防重机制（双保险）：
  1) 主键 id（usg_...，API 请求唯一 ID）——INSERT OR IGNORE
  2) 联合唯一索引 (timestamp, model_name, input_raw, output_raw, cost_raw)
     —— 兜底防止缺少 id 的脏数据重复入库
"""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from ocgmon.config import mask_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id                  TEXT PRIMARY KEY,      -- 记录唯一 ID（usg_...）
    request_id          TEXT,                  -- API 请求 ID（同 id，兼容扩展）
    timestamp           TEXT,                  -- UTC ISO 时间
    ts_epoch            INTEGER,               -- UTC epoch 秒（范围查询用）
    timestamp_local     TEXT,                  -- 本地时间字符串（显示用）
    api_key_masked      TEXT,                  -- 脱敏 API Key
    key_id              TEXT,                  -- 原始 API Key
    model_name          TEXT,
    provider            TEXT,
    prompt_tokens       INTEGER,               -- 总输入（含缓存读/写）
    completion_tokens   INTEGER,               -- 输出
    input_raw           INTEGER,               -- 仅 inputTokens
    output_raw          INTEGER,
    reasoning_tokens    INTEGER,
    cache_read_tokens   INTEGER,
    cache_write5m_tokens INTEGER,
    cache_write1h_tokens INTEGER,
    total_tokens        INTEGER,               -- prompt + completion
    cost                REAL,                  -- 美元（cost_raw / 1e8）
    cost_raw            INTEGER,
    status              TEXT DEFAULT 'success',
    workspace_id        TEXT,
    session_id          TEXT,
    enrichment          TEXT,
    tag                 TEXT DEFAULT '',       -- 用户标签
    UNIQUE (timestamp, model_name, input_raw, output_raw, cost_raw)
);
CREATE INDEX IF NOT EXISTS idx_ts      ON usage_records(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_model   ON usage_records(model_name);
CREATE INDEX IF NOT EXISTS idx_key     ON usage_records(key_id);
CREATE INDEX IF NOT EXISTS idx_tag     ON usage_records(tag);
CREATE INDEX IF NOT EXISTS idx_cost    ON usage_records(cost);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    tag         TEXT PRIMARY KEY,
    color       TEXT,
    updated_at  TEXT
);
"""


class Database:
    """线程安全（单写者 + 并发读连接）的 SQLite 封装。"""

    def __init__(self, path: str):
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def _conn(self):
        conn = sqlite3.connect(self._path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def close(self):
        pass  # 连接按需创建，无需显式关闭

    # ------------------------------------------------------------------
    # 写入（防重）
    # ------------------------------------------------------------------
    def insert_records(self, records: list, ret_skipped: bool = False):
        """批量写入清洗后的记录。返回 (inserted, skipped)。

        INSERT OR IGNORE 依据：主键 id + 联合唯一索引。
        """
        if not records:
            return (0, 0)
        inserted = skipped = 0
        sql = """
            INSERT OR IGNORE INTO usage_records
            (id, request_id, timestamp, ts_epoch, timestamp_local, api_key_masked, key_id,
             model_name, provider, prompt_tokens, completion_tokens, input_raw, output_raw,
             reasoning_tokens, cache_read_tokens, cache_write5m_tokens, cache_write1h_tokens,
             total_tokens, cost, cost_raw, status, workspace_id, session_id, enrichment, tag)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        rows = []
        for r in records:
            rows.append((
                r["id"], r["request_id"], r["timestamp"], r["ts_epoch"], r["timestamp_local"],
                mask_key(r["key_id"]), r["key_id"],
                r["model_name"], r["provider"], r["prompt_tokens"], r["completion_tokens"],
                r["input_raw"], r["output_raw"], r["reasoning_tokens"], r["cache_read_tokens"],
                r["cache_write5m_tokens"], r["cache_write1h_tokens"],
                r["total_tokens"], r["cost"], r["cost_raw"], r["status"],
                r["workspace_id"], r["session_id"], r["enrichment"], "",
            ))
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.executemany(sql, rows)
                conn.commit()
                inserted = cur.rowcount
                skipped = len(rows) - inserted
            finally:
                conn.close()
        return (inserted, skipped)

    def import_json(self, records: list) -> tuple:
        """从 usage_raw.json（原始接口字段）导入。"""
        from ocgmon.seroval import normalize_record
        return self.insert_records([normalize_record(r) for r in records])

    # ------------------------------------------------------------------
    # 查询构造
    # ------------------------------------------------------------------
    @staticmethod
    def build_where(f: dict) -> tuple:
        """把筛选字典转成 (where_sql, params)。

        f 支持的键：start_epoch / end_epoch（含端点）、models(list)、keys(list)、
        tags(list)、min_cost / max_cost、min_tokens / max_tokens、search、
        weekday(0-6 本地)/hour(0-23)（图表联动）、record_id（单条定位）。
        """
        clauses, params = [], []
        if f.get("start_epoch") is not None:
            clauses.append("ts_epoch >= ?")
            params.append(int(f["start_epoch"]))
        if f.get("end_epoch") is not None:
            clauses.append("ts_epoch <= ?")
            params.append(int(f["end_epoch"]))
        if f.get("models"):
            ph = ",".join("?" * len(f["models"]))
            clauses.append(f"model_name IN ({ph})")
            params.extend(f["models"])
        if f.get("keys"):
            ph = ",".join("?" * len(f["keys"]))
            clauses.append(f"key_id IN ({ph})")
            params.extend(f["keys"])
        if f.get("tags"):
            ph = ",".join("?" * len(f["tags"]))
            clauses.append(f"tag IN ({ph})")
            params.extend(f["tags"])
        if f.get("weekday") is not None:
            clauses.append("CAST(strftime('%w', datetime(ts_epoch,'unixepoch','localtime')) AS INTEGER) = ?")
            params.append(int(f["weekday"]))
        if f.get("hour") is not None:
            clauses.append("CAST(strftime('%H', datetime(ts_epoch,'unixepoch','localtime')) AS INTEGER) = ?")
            params.append(int(f["hour"]))
        if f.get("record_id"):
            clauses.append("id = ?")
            params.append(f["record_id"])
        if f.get("min_cost") is not None:
            clauses.append("cost >= ?")
            params.append(float(f["min_cost"]))
        if f.get("max_cost") is not None:
            clauses.append("cost <= ?")
            params.append(float(f["max_cost"]))
        if f.get("min_tokens") is not None:
            clauses.append("total_tokens >= ?")
            params.append(int(f["min_tokens"]))
        if f.get("max_tokens") is not None:
            clauses.append("total_tokens <= ?")
            params.append(int(f["max_tokens"]))
        if f.get("search"):
            like = f"%{f['search']}%"
            clauses.append("(model_name LIKE ? OR key_id LIKE ? OR tag LIKE ? OR provider LIKE ? OR id LIKE ?)")
            params.extend([like] * 5)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return (where, params)

    def query(self, f: dict = None, order: str = "ts_epoch DESC", limit: int = None, offset: int = None) -> list:
        where, params = self.build_where(f or {})
        sql = f"SELECT * FROM usage_records {where} ORDER BY {order}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
            if offset is not None:
                sql += f" OFFSET {int(offset)}"
        with self._lock:
            conn = self._conn()
            try:
                conn.row_factory = sqlite3.Row
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
            finally:
                conn.close()

    def all_ids(self) -> set:
        """全部已入库记录的 id 集合（用于增量同步比对，数万条以内内存开销可忽略）。"""
        with self._lock:
            conn = self._conn()
            try:
                return {r[0] for r in conn.execute("SELECT id FROM usage_records")}
            finally:
                conn.close()

    def count(self, f: dict = None) -> int:
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                return conn.execute(f"SELECT COUNT(*) FROM usage_records {where}", params).fetchone()[0]
            finally:
                conn.close()

    def total_records(self) -> int:
        with self._lock:
            conn = self._conn()
            try:
                return conn.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0]
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 聚合（总览/分析）
    # ------------------------------------------------------------------
    def aggregate(self, f: dict = None) -> dict:
        """核心指标：总量、花费、模型分布、调用次数。"""
        where, params = self.build_where(f or {})
        sql = f"""
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens),0) AS in_tokens,
                   COALESCE(SUM(completion_tokens),0) AS out_tokens,
                   COALESCE(SUM(total_tokens),0) AS total_tokens,
                   COALESCE(SUM(cost),0) AS cost,
                   COUNT(DISTINCT model_name) AS models,
                   COUNT(DISTINCT key_id) AS keys,
                   COUNT(DISTINCT tag) AS tags
            FROM usage_records {where}
        """
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(sql, params).fetchone()
            finally:
                conn.close()
        agg = {
            "calls": row[0] or 0, "input_tokens": row[1] or 0, "output_tokens": row[2] or 0,
            "total_tokens": row[3] or 0, "cost": row[4] or 0.0,
            "models": row[5] or 0, "keys": row[6] or 0, "tags": row[7] or 0,
        }
        # 最常用模型
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    f"SELECT model_name, COUNT(*) c, SUM(total_tokens) t, SUM(cost) cost "
                    f"FROM usage_records {where} GROUP BY model_name ORDER BY c DESC LIMIT 1",
                    params).fetchone()
                agg["top_model"] = row[0] if row else "-"
                agg["top_model_calls"] = row[1] if row else 0
                agg["top_model_tokens"] = row[2] if row else 0
                agg["top_model_cost"] = row[3] if row else 0.0
            finally:
                conn.close()
        return agg

    def model_share(self, f: dict = None) -> list:
        """各模型用量（调用次数/总token/成本）。"""
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    f"SELECT model_name, COUNT(*) calls, SUM(total_tokens) tokens, SUM(cost) cost "
                    f"FROM usage_records {where} GROUP BY model_name ORDER BY tokens DESC",
                    params).fetchall()
            finally:
                conn.close()
        return [{"model": r[0], "calls": r[1], "tokens": r[2], "cost": r[3]} for r in rows]

    def by_key(self, f: dict = None) -> list:
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    f"SELECT key_id, api_key_masked, COUNT(*) calls, SUM(total_tokens) tokens, "
                    f"SUM(cost) cost, MIN(ts_epoch) first_ts, MAX(ts_epoch) last_ts "
                    f"FROM usage_records {where} GROUP BY key_id ORDER BY cost DESC",
                    params).fetchall()
            finally:
                conn.close()
        return [dict(zip(["key_id", "api_key_masked", "calls", "tokens", "cost", "first_ts", "last_ts"], r))
                for r in rows]

    def by_model(self, f: dict = None) -> list:
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    f"SELECT model_name, COUNT(*) calls, SUM(total_tokens) tokens, SUM(cost) cost "
                    f"FROM usage_records {where} GROUP BY model_name ORDER BY cost DESC",
                    params).fetchall()
            finally:
                conn.close()
        return [{"model": r[0], "calls": r[1], "tokens": r[2], "cost": r[3]} for r in rows]

    def trend(self, f: dict = None, granularity: str = "day") -> list:
        """时间序列：按小时/日聚合。返回 [{bucket, ts_epoch, in_tokens, out_tokens, tokens, cost, calls}]"""
        if granularity == "hour":
            bucket_sql = "strftime('%Y-%m-%d %H:00', datetime(ts_epoch, 'unixepoch', 'localtime'))"
            group_sql = "strftime('%Y-%m-%d %H:00', datetime(ts_epoch, 'unixepoch', 'localtime'))"
        else:
            bucket_sql = "strftime('%Y-%m-%d', datetime(ts_epoch, 'unixepoch', 'localtime'))"
            group_sql = "strftime('%Y-%m-%d', datetime(ts_epoch, 'unixepoch', 'localtime'))"
        where, params = self.build_where(f or {})
        sql = f"""
            SELECT {bucket_sql} AS bucket, MIN(ts_epoch) AS ts,
                   SUM(prompt_tokens) in_tokens, SUM(completion_tokens) out_tokens,
                   SUM(total_tokens) tokens, SUM(cost) cost, COUNT(*) calls
            FROM usage_records {where}
            GROUP BY {group_sql} ORDER BY ts ASC
        """
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        return [{"bucket": r[0], "ts_epoch": r[1], "input_tokens": r[2], "output_tokens": r[3],
                 "tokens": r[4], "cost": r[5], "calls": r[6]} for r in rows]

    def heatmap(self, f: dict = None) -> dict:
        """星期 × 小时的调用量矩阵（本地时间）。返回 {matrix: 7x24, max_calls}。"""
        where, params = self.build_where(f or {})
        sql = f"""
            SELECT CAST(strftime('%w', datetime(ts_epoch,'unixepoch','localtime')) AS INTEGER) wd,
                   CAST(strftime('%H', datetime(ts_epoch,'unixepoch','localtime')) AS INTEGER) hr,
                   COUNT(*) c
            FROM usage_records {where}
            GROUP BY wd, hr
        """
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        matrix = [[0] * 24 for _ in range(7)]
        mx = 0
        for wd, hr, c in rows:
            matrix[wd][hr] = c
            mx = max(mx, c)
        return {"matrix": matrix, "max_calls": mx}

    def cumulative(self, f: dict = None) -> list:
        """累积成本序列（按时间升序），元素: {ts_epoch, cum_cost, cost}。"""
        rows = self.trend(f, granularity="day")
        cum = 0.0
        out = []
        for r in rows:
            cum += r["cost"]
            out.append({"ts_epoch": r["ts_epoch"], "cost": r["cost"], "cum_cost": cum})
        return out

    def outliers(self, f: dict = None, factor: float = 3.0, top: int = 500) -> dict:
        """成本或总 token 超出均值 factor 倍的记录 ID 集合（用于标红）。"""
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    f"SELECT AVG(cost), AVG(total_tokens) FROM usage_records {where}", params).fetchone()
                ids = conn.execute(
                    f"SELECT id, cost, total_tokens FROM usage_records {where} "
                    f"ORDER BY ts_epoch DESC LIMIT {int(top)}", params).fetchall()
            finally:
                conn.close()
        avg_cost, avg_tokens = row[0] or 0.0, row[1] or 0.0
        cost_ids, token_ids = set(), set()
        if avg_cost > 0:
            cost_ids = {r[0] for r in ids if r[1] > avg_cost * factor}
        if avg_tokens > 0:
            token_ids = {r[0] for r in ids if r[2] > avg_tokens * factor}
        return {"cost_ids": cost_ids, "token_ids": token_ids,
                "avg_cost": avg_cost, "avg_tokens": avg_tokens}

    # ------------------------------------------------------------------
    # 标签
    # ------------------------------------------------------------------
    def set_tag(self, record_id: str, tag: str):
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("UPDATE usage_records SET tag=? WHERE id=?", (tag or "", record_id))
                if tag:
                    conn.execute("INSERT OR IGNORE INTO tags(tag, updated_at) VALUES (?, ?)",
                                 (tag, time.strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
            finally:
                conn.close()

    def all_tags(self) -> list:
        with self._lock:
            conn = self._conn()
            try:
                return [r[0] for r in conn.execute(
                    "SELECT tag FROM usage_records WHERE tag != '' GROUP BY tag ORDER BY tag").fetchall()]
            finally:
                conn.close()

    def key_model_matrix(self, f: dict = None) -> dict:
        """{key_id: {model_name: {calls, tokens, cost}}}，供堆叠柱状图。"""
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    f"SELECT key_id, model_name, COUNT(*) calls, SUM(total_tokens) tokens, "
                    f"SUM(cost) cost FROM usage_records {where} "
                    f"GROUP BY key_id, model_name", params).fetchall()
            finally:
                conn.close()
        out = {}
        for key_id, model, calls, tokens, cost in rows:
            out.setdefault(key_id, {})[model] = {"calls": calls, "tokens": tokens, "cost": cost}
        return out

    def tag_stats(self, f: dict = None) -> list:
        """按标签统计。"""
        where, params = self.build_where(f or {})
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    f"SELECT tag, COUNT(*) calls, SUM(total_tokens) tokens, SUM(cost) cost "
                    f"FROM usage_records {where} AND tag != '' GROUP BY tag ORDER BY cost DESC",
                    params).fetchall()
            finally:
                conn.close()
        return [{"tag": r[0], "calls": r[1], "tokens": r[2], "cost": r[3]} for r in rows]

    # ------------------------------------------------------------------
    # 预设
    # ------------------------------------------------------------------
    def save_preset(self, name: str, filter_json: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "INSERT INTO presets(name, filter_json, created_at) VALUES (?,?,?)",
                    (name, filter_json, time.strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def presets(self) -> list:
        with self._lock:
            conn = self._conn()
            try:
                conn.row_factory = sqlite3.Row
                return [dict(r) for r in conn.execute("SELECT * FROM presets ORDER BY id DESC").fetchall()]
            finally:
                conn.close()

    def delete_preset(self, preset_id: int):
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM presets WHERE id=?", (preset_id,))
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # meta
    # ------------------------------------------------------------------
    def meta_get(self, key: str, default=None):
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                return row[0] if row else default
            finally:
                conn.close()

    def meta_set(self, key: str, value: str):
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, str(value)))
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 时间范围工具
    # ------------------------------------------------------------------
    @staticmethod
    def range_epochs(preset: str, start_dt=None, end_dt=None) -> dict:
        """把时间范围选择换算为 epoch 秒。preset: 1h/24h/7d/30d/all/custom"""
        now = datetime.now().replace(microsecond=0)
        end = now
        if preset == "1h":
            start = now - timedelta(hours=1)
        elif preset == "24h":
            start = now - timedelta(hours=24)
        elif preset == "7d":
            start = now - timedelta(days=7)
        elif preset == "30d":
            start = now - timedelta(days=30)
        elif preset == "custom" and start_dt and end_dt:
            start, end = start_dt, end_dt
        else:  # all
            start = None
        f = {}
        if start is not None:
            f["start_epoch"] = int(start.timestamp())
        if end is not None:
            f["end_epoch"] = int(end.timestamp())
        return f

    # ------------------------------------------------------------------
    # 花费预警
    # ------------------------------------------------------------------
    def spend_since(self, since_epoch: int) -> float:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost),0) FROM usage_records WHERE ts_epoch >= ?",
                    (int(since_epoch),)).fetchone()
            finally:
                conn.close()
        return row[0] or 0.0
