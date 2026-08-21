# -*- coding: utf-8 -*-
"""seroval v1 协议编解码（纯 Python 实现，无需 Node.js）

依据《获取Opencode_Go使用记录原理与注意事项.md》2.4/2.5 节：

编码（请求体）: {"t": <序列化参数树>, "f": 31, "m": []}
    t = {"t":9, "i":0, "l":2, "a":[{t:1,s:<workspaceId>},{t:0,s:<page>}], "o":0}

解码（响应）: 不是 JSON，而是 seroval vanilla JS 代码：
    ;0x....;((self.$R=self.$R||{})["server-fn:N"]=[],($R=>$R[0]=[<records>])($R["server-fn:N"]))
    - $R 为引用表，$R[0] 是记录数组
    - 嵌套对象（Date / enrichment）提升为 $R[N]=xxx 引用，可内联赋值或后续引用
    - 错误响应为 Object.assign(new Error("msg"), {...})
"""
import json
import re

from ocgmon import COST_DIVISOR


class SerovalError(Exception):
    """响应解析失败（非网络层错误）。"""


class ApiError(Exception):
    """服务端返回的业务错误（Cookie 无效 / 工作区无权限 / 函数 ID 失效等）。"""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------

def encode_args(workspace_id: str, page: int) -> str:
    """构造 getUsageInfo(workspaceId, page) 的 seroval v1 请求体。"""
    return json.dumps({
        "t": {
            "t": 9, "i": 0, "l": 2,
            "a": [
                {"t": 1, "s": workspace_id},
                {"t": 0, "s": int(page)},
            ],
            "o": 0,
        },
        "f": 31,
        "m": [],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 解码
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:\\.|[^"\\])*")
  | (?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<id>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<punct>[{}[\](),:=.;])
""", re.VERBOSE)


def _js_str_decode(s: str) -> str:
    """解码 JS 字符串字面量（json.loads 兼容绝大多数 JS 转义）。"""
    try:
        return json.loads(s)
    except Exception:
        # 个别不合规转义：手工处理
        out = []
        i = 1
        n = len(s) - 1
        while i < n:
            ch = s[i]
            if ch == "\\" and i + 1 < n:
                nxt = s[i + 1]
                table = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}
                if nxt in table:
                    out.append(table[nxt]); i += 2; continue
                if nxt == "u" and i + 5 < n:
                    try:
                        out.append(chr(int(s[i + 2:i + 6], 16))); i += 6; continue
                    except ValueError:
                        pass
                out.append(nxt); i += 2; continue
            out.append(ch)
            i += 1
        return "".join(out)


class _Parser:
    """递归下降解析 seroval vanilla 输出的 JS 字面量子集。"""

    def __init__(self, text: str):
        self.text = text
        self.tokens = []
        pos = 0
        for m in _TOKEN_RE.finditer(text):
            if m.group("ws"):
                continue
            self.tokens.append((m.lastgroup, m.group()))
        self.i = 0
        self.refs = {}          # $R[N] -> 值
        self.warnings = []

    # ---- 工具 ----
    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def expect(self, kind, val=None):
        k, v = self.next()
        if k != kind or (val is not None and v != val):
            raise SerovalError(f"解析失败: 期望 {val or kind}，实际得到 {v!r}（位置 {self.i}）")
        return v

    # ---- 入口 ----
    def parse(self):
        """解析整个响应文本，返回 $R[0]（记录数组）。"""
        body = self.text.strip()
        # 剥离 ";0x....;" 前缀
        m = re.match(r"^;0x[0-9a-fA-F]+;", body)
        if m:
            body = body[m.end():]
        if not body.startswith("((") or "self.$R" not in body:
            raise SerovalError("响应不是预期的 seroval 格式")
        # 定位 IIFE 主体: ($R=> CHAIN )($R[...])
        start = body.find("($R=>")
        if start < 0:
            raise SerovalError("响应中找不到 ($R=> 主体")
        chain_start = start + len("($R=>")
        depth = 0
        chain_end = None
        for k, v in self._iter_text_tokens(body[chain_start:]):
            if v == "(":
                depth += 1
            elif v == ")":
                depth -= 1
                if depth < 0:
                    chain_end = chain_start + self._tok_pos
                    break
            elif depth < 0:
                break
        if chain_end is None:
            raise SerovalError("响应主体括号不匹配")
        chain = body[chain_start:chain_end]
        self._parse_chain(chain)
        data = self.refs.get(0)
        if data is None:
            # 错误响应（new Error）在解析链中已抛出；此处兜底
            raise SerovalError("响应中没有数据（$R[0] 缺失）")
        return data

    def _iter_text_tokens(self, text):
        """仅用于括号配平：按字符扫描字符串字面量与括号。"""
        self._tok_pos = 0
        i = 0
        n = len(text)
        in_str = False
        while i < n:
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    in_str = False
                i += 1
                continue
            if c == '"':
                in_str = True
                i += 1
                continue
            if c in "()":
                self._tok_pos = i
                yield None, c
            i += 1

    def _parse_chain(self, chain: str):
        """逗号分隔的赋值链: $R[0]=<值>, $R[1]=<值>, ..."""
        self.tokens = []
        for m in _TOKEN_RE.finditer(chain):
            if m.group("ws"):
                continue
            self.tokens.append((m.lastgroup, m.group()))
        self.i = 0
        while self.i < len(self.tokens):
            k, v = self.peek()
            if k != "id" or v != "$R":
                # 允许结尾无意义的空语句
                if k is None:
                    break
                raise SerovalError(f"响应主体异常: 期望 $R 赋值，实际 {v!r}")
            self.next()
            self.expect("punct", "[")
            num_tok = self.next()
            if num_tok[0] != "num":
                raise SerovalError(f"引用索引非数字: {num_tok!r}")
            idx = int(float(num_tok[1]))
            self.expect("punct", "]")
            eq = self.peek()
            if eq[0] == "punct" and eq[1] == "=":
                self.next()
                self.refs[idx] = self.parse_value()
            else:
                # 孤立引用（理论不应出现在链中）
                self.warnings.append(f"孤立引用 $R[{idx}]")
                self.refs.setdefault(idx, None)
            # 逗号或结束
            k, v = self.peek()
            if k == "punct" and v == ",":
                self.next()

    # ---- 值解析 ----
    def parse_value(self):
        k, v = self.peek()
        if k is None:
            raise SerovalError("意外结束")
        if k == "str":
            self.next()
            return _js_str_decode(v)
        if k == "num":
            self.next()
            return float(v) if ("." in v or "e" in v or "E" in v) else int(v)
        if k == "punct":
            if v == "{":
                return self.parse_object()
            if v == "[":
                return self.parse_array()
            if v == "(":
                self.next()
                val = self.parse_value()
                self.expect("punct", ")")
                return val
        if k == "id":
            self.next()
            if v == "null":
                return None
            if v in ("true",):
                return True
            if v in ("false",):
                return False
            if v == "undefined":
                return None
            if v in ("NaN", "Infinity", "-Infinity"):
                return None
            if v == "new":
                return self.parse_new()
            if v == "Object":
                # Object.assign(a, b)
                self.expect("punct", ".")
                self.expect("id", "assign")
                self.expect("punct", "(")
                a = self.parse_value()
                b = None
                if self.peek()[0] == "punct" and self.peek()[1] == ",":
                    self.next()
                    b = self.parse_value()
                self.expect("punct", ")")
                if isinstance(b, dict) and isinstance(a, dict):
                    a.update(b)
                    return a
                return a if b is None else b
            if v == "$R":
                # $R[N] 或 $R[N]=<值>
                self.expect("punct", "[")
                num_tok = self.next()
                idx = int(float(num_tok[1]))
                self.expect("punct", "]")
                if self.peek()[0] == "punct" and self.peek()[1] == "=":
                    self.next()
                    val = self.parse_value()
                    self.refs[idx] = val
                    return val
                return self.refs.get(idx)
            raise SerovalError(f"未知标识符 {v!r}")
        raise SerovalError(f"无法解析的值: {v!r}")

    def parse_new(self):
        k, v = self.next()
        if k != "id":
            raise SerovalError(f"new 后应为构造函数，实际 {v!r}")
        self.expect("punct", "(")
        if v == "Date":
            s = self.parse_value()
            self.expect("punct", ")")
            if isinstance(s, str):
                return s          # ISO 时间字符串
            return ""
        if v == "Error" or v.endswith("Error"):
            # 服务端业务错误：new Error / new RangeError / new TypeError ...
            # 例如函数 ID 指向 getCosts 被误调用时返回 new RangeError("Invalid time value")
            msg = self.parse_value()
            self.expect("punct", ")")
            raise ApiError(f"{v}: {msg}" if v != "Error" else str(msg),
                           hint="服务端返回错误（可能 Cookie 无权限或 Server Function ID 失效）")
        if v == "Number":
            s = self.parse_value()
            self.expect("punct", ")")
            return s
        raise SerovalError(f"不支持的构造函数 new {v}()")

    def parse_object(self):
        self.expect("punct", "{")
        obj = {}
        while True:
            k, v = self.peek()
            if k == "punct" and v == "}":
                self.next()
                break
            if k == "str":
                key = _js_str_decode(v)
                self.next()
            elif k == "id":
                key = v
                self.next()
            else:
                raise SerovalError(f"对象键异常: {v!r}")
            if self.peek()[0] == "punct" and self.peek()[1] == ":":
                self.next()
            obj[key] = self.parse_value()
            k, v = self.peek()
            if k == "punct" and v == ",":
                self.next()
            elif k == "punct" and v == "}":
                self.next()
                break
            else:
                raise SerovalError(f"对象缺少逗号/右括号: {v!r}")
        return obj

    def parse_array(self):
        self.expect("punct", "[")
        arr = []
        while True:
            k, v = self.peek()
            if k == "punct" and v == "]":
                self.next()
                break
            arr.append(self.parse_value())
            k, v = self.peek()
            if k == "punct" and v == ",":
                self.next()
            elif k == "punct" and v == "]":
                self.next()
                break
            else:
                raise SerovalError(f"数组缺少逗号/右括号: {v!r}")
        return arr


def parse_response(text: str) -> list:
    """解析 seroval 响应文本，返回记录列表（原始字段，见 ocgmon.db.normalize_record）。

    返回 [] 表示最后一页（空数组）。
    抛 ApiError：服务端业务错误（含 Error 响应 / JSON 错误体）。
    抛 SerovalError：格式解析失败。
    """
    text = (text or "").strip()
    if not text:
        raise SerovalError("空响应")
    # 服务端也可能直接返回 JSON 错误体（如函数不存在时）
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            raise SerovalError(f"响应不是 seroval/JSON: {text[:120]!r}")
        status = obj.get("status")
        message = obj.get("message") or obj.get("error") or ""
        if status == 401 or "unauthenticated" in str(message).lower():
            raise ApiError(f"认证失败（HTTP {status}）：{message}", hint="Cookie 已失效，请在设置中更新 Cookie")
        if message:
            raise ApiError(f"服务端错误（HTTP {status or '-'}）：{message}",
                           hint="可能 Server Function ID 已失效，请到设置页点击『恢复函数ID』")
        raise SerovalError(f"未知 JSON 响应: {text[:200]}")
    parser = _Parser(text)
    try:
        data = parser.parse()
    except ApiError:
        raise
    except SerovalError:
        raise
    except Exception as e:
        raise SerovalError(f"解析失败: {e}")
    if not isinstance(data, list):
        raise SerovalError("响应数据不是数组")
    return data


# ---------------------------------------------------------------------------
# 记录清洗（字段映射 / 单位换算 / 时间转换）
# ---------------------------------------------------------------------------

def normalize_record(raw: dict) -> dict:
    """把接口原始记录清洗为标准入库字段（依据文档 2.8 口径）。

    成本：cost / 1e8 美元；token 口径：
      总输入 = inputTokens + cacheReadTokens + cacheWrite5mTokens + cacheWrite1hTokens
      总Token = 总输入 + outputTokens
    时间：timeCreated 为 UTC，同时保留 epoch 与本地(北京)字符串。
    """
    import datetime

    def _n(v, default=0):
        return int(v) if v is not None and str(v).lstrip("-").isdigit() else default

    input_raw = _n(raw.get("inputTokens"))
    output_raw = _n(raw.get("outputTokens"))
    cache_read = _n(raw.get("cacheReadTokens"))
    cache_5m = _n(raw.get("cacheWrite5mTokens"))
    cache_1h = _n(raw.get("cacheWrite1hTokens"))
    prompt = input_raw + cache_read + cache_5m + cache_1h
    total = prompt + output_raw
    cost_raw = _n(raw.get("cost"))
    cost = cost_raw / COST_DIVISOR if cost_raw else 0.0

    ts_utc = raw.get("timeCreated") or raw.get("timeUpdated") or ""
    ts_epoch = 0
    ts_local = ""
    if ts_utc:
        try:
            dt = datetime.datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
            ts_epoch = int(dt.timestamp())
            ts_local = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_epoch = 0
            ts_local = ts_utc

    enrichment = raw.get("enrichment") or {}
    return {
        "id": raw.get("id") or "",
        "request_id": raw.get("id") or "",
        "timestamp": ts_utc,                      # UTC ISO
        "ts_epoch": ts_epoch,
        "timestamp_local": ts_local,              # 本地时间字符串
        "api_key_masked": "",                     # 入库时由 key_id 生成
        "key_id": raw.get("keyID") or "",
        "model_name": raw.get("model") or "unknown",
        "provider": raw.get("provider") or "",
        "prompt_tokens": prompt,                  # 总输入（含缓存）
        "completion_tokens": output_raw,
        "input_raw": input_raw,
        "output_raw": output_raw,
        "reasoning_tokens": _n(raw.get("reasoningTokens")),
        "cache_read_tokens": cache_read,
        "cache_write5m_tokens": cache_5m,
        "cache_write1h_tokens": cache_1h,
        "total_tokens": total,
        "cost": cost,                             # 美元
        "cost_raw": cost_raw,
        "status": "success",
        "workspace_id": raw.get("workspaceID") or "",
        "session_id": raw.get("sessionID") or "",
        "enrichment": json.dumps(enrichment, ensure_ascii=False) if enrichment else "",
    }
