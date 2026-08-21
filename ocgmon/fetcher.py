# -*- coding: utf-8 -*-
"""网络抓取层：调用 opencode.ai 的 usage Server Function 并分页拉取全部记录。

协议细节见《获取Opencode_Go使用记录原理与注意事项.md》：
  POST https://opencode.ai/_server
  请求头: Cookie / X-Server-Id(64位hex) / X-Server-Instance(server-fn:N) / Content-Type
  请求体: seroval v1 编码的参数数组 [workspaceId, page]
  响应  : seroval vanilla JS（需解析，见 seroval.py）
  分页  : 每页 50 条，返回 < 50 条即最后一页
"""
import re
import threading
import time

import requests
from PySide6.QtCore import QThread, Signal

from ocgmon import PAGE_SIZE
from ocgmon import seroval

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0")
ENDPOINT = "https://opencode.ai/_server"


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------
class FetchError(Exception):
    KIND = "generic"

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint

    @property
    def friendly(self) -> str:
        return f"{self}\n\n{self.hint}" if self.hint else str(self)


class CookieInvalidError(FetchError):
    KIND = "cookie"
    hint_default = "请到『系统设置』页更新 Cookie（浏览器 F12 → Network → 请求头中复制整行）。"


class ServerIdError(FetchError):
    KIND = "server_id"
    hint_default = "Server Function ID 已随前端更新失效，请在『系统设置』点击『恢复函数ID』自动重新提取。"


class RateLimitedError(FetchError):
    KIND = "rate_limit"
    hint_default = "接口限流，请稍后重试，或增大『设置 → 请求间隔』。"


class HttpError_(FetchError):
    KIND = "http"


# ---------------------------------------------------------------------------
# 同步抓取核心（在 worker 线程中调用）
# ---------------------------------------------------------------------------
class UsageFetcher:
    def __init__(self, cookie: str, workspace_id: str, server_id: str,
                 delay_ms: int = 300, timeout: int = 60):
        self.cookie = (cookie or "").strip()
        self.workspace_id = workspace_id
        self.server_id = server_id
        self.delay = max(100, int(delay_ms)) / 1000.0
        self.timeout = timeout
        self._session = None

    def _session_get(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update({
                "Cookie": self.cookie,
                "X-Server-Id": self.server_id,
                "Content-Type": "application/json",
                "User-Agent": UA,
                "Accept": "*/*",
                "Origin": "https://opencode.ai",
                "Referer": f"https://opencode.ai/workspace/{self.workspace_id}/usage",
            })
            self._session = s
        return self._session

    def validate_cookie(self) -> bool:
        """按文档步骤2：GET usage 页面，200 视为有效。"""
        try:
            r = requests.get(
                f"https://opencode.ai/workspace/{self.workspace_id}/usage",
                headers={"Cookie": self.cookie, "User-Agent": UA},
                timeout=30, allow_redirects=False)
            return r.status_code == 200
        except Exception:
            return False

    def fetch_page(self, page: int) -> list:
        """抓取单页并解析。返回记录列表（可能为空 = 最后一页）。"""
        body = seroval.encode_args(self.workspace_id, page)
        headers = {"X-Server-Instance": f"server-fn:{page}"}
        try:
            r = self._session_get().post(ENDPOINT, data=body.encode("utf-8"),
                                         headers=headers, timeout=self.timeout)
        except requests.Timeout:
            raise FetchError(f"第 {page} 页请求超时（{self.timeout}s）",
                             "网络不稳定或服务端无响应，可增大超时/重试。")
        except requests.ConnectionError as e:
            raise FetchError(f"网络连接失败: {e}", "请检查网络连接。")
        except Exception as e:
            raise FetchError(f"请求异常: {e}")

        if r.status_code == 429:
            raise RateLimitedError(f"接口限流（HTTP 429），第 {page} 页请求被拒绝")
        if r.status_code == 401:
            raise CookieInvalidError(f"认证失败（HTTP 401）")
        if r.status_code == 404:
            raise ServerIdError(f"Server Function 不存在（HTTP 404）")
        if r.status_code >= 400:
            # 某些 500 错误响应体包含业务错误信息
            raise FetchError(f"HTTP {r.status_code}", r.text[:300])
        try:
            return seroval.parse_response(r.text)
        except seroval.ApiError as e:
            if "workspace" in str(e).lower() and "not associated" in str(e).lower():
                raise CookieInvalidError(f"Cookie 对应的账号与工作区不匹配：{e}")
            if "unauthor" in str(e).lower() or "login" in str(e).lower() or "session" in str(e).lower():
                raise CookieInvalidError(f"{e}")
            if "time value" in str(e).lower() or "rangeerror" in str(e).lower():
                # 函数 ID 实际指向 getCosts（参数结构不同）时的典型错误
                raise ServerIdError(
                    "Server Function ID 指向了错误的函数（getCosts）",
                    "请点击『恢复函数ID』重新提取 usage.list 的函数 ID。")
            raise ServerIdError(f"服务端业务错误：{e}")
        except seroval.SerovalError as e:
            raise FetchError(f"响应解析失败：{e}", "接口格式可能已变更，可尝试『恢复函数ID』。")

    def fetch_all(self, on_progress=None, cancel_flag: threading.Event = None,
                  start_page: int = 0, max_pages: int = 2000,
                  known_ids: set = None) -> tuple:
        """分页拉取全部记录（增量感知）。

        on_progress(page, new_records_this_page, total_so_far) 回调。

        known_ids：已入库记录的 id 集合。接口按时间**最新→最旧**分页，
        当某一页的记录**全部**命中 known_ids 时，说明后续页必然已同步，
        立即提前停止（增量同步优化）。

        返回 (records, early_stopped)；records 仅包含未入库的新记录。
        """
        all_records = []
        page = start_page
        consecutive_fail = 0
        early_stopped = False
        while page < max_pages:
            if cancel_flag is not None and cancel_flag.is_set():
                raise FetchError("同步已由用户取消")
            try:
                records = self.fetch_page(page)
                consecutive_fail = 0
            except RateLimitedError:
                consecutive_fail += 1
                if consecutive_fail > 3:
                    raise
                time.sleep(2 * consecutive_fail)
                continue
            except (requests.Timeout, FetchError):
                # 偶发错误重试 2 次
                consecutive_fail += 1
                if consecutive_fail > 2:
                    raise
                time.sleep(1.5 * consecutive_fail)
                continue
            if not records:                       # 空页 = 最后一页
                break
            # 增量过滤：区分新记录与已同步记录
            new_page = []
            dup = 0
            for r in records:
                if known_ids is not None and r.get("id") in known_ids:
                    dup += 1
                else:
                    new_page.append(r)
            all_records.extend(new_page)
            if on_progress:
                try:
                    on_progress(page, len(new_page), len(all_records))
                except Exception:
                    pass
            if len(records) < PAGE_SIZE:          # ★ 分页终止条件（文档 2.6）
                break
            # ★ 增量停止条件：整页全部为已同步记录 → 后续页必然已同步
            if known_ids is not None and dup == len(records):
                early_stopped = True
                break
            page += 1
            time.sleep(self.delay)
        return all_records, early_stopped


# ---------------------------------------------------------------------------
# 函数 ID 自动恢复（文档 2.3：从前端 bundle 提取）
#
# 2026-08 实测修正：
# 1. chunk 发现：入口 bundle 中 usage 路由注册形如
#      "src": "src/routes/workspace/[id]/usage/index.tsx?pick=...",
#      "build": () => __vitePreload(() => import("./index-CtXx_w0m.js"), ...)
#    chunk 文件名是纯哈希（不含 "usage"），必须从路由 src 就近向后找 import("./xxx.js")。
# 2. ID 识别：usage 组件 chunk 中两个 createServerReference 的**顺序不固定**
#    （2026-08 版本 getCosts 在前）。必须按赋值目标变量名识别：
#      const getCosts_1     = createServerReference("<64hex>");   → getCosts
#      const getUsageInfo_1 = createServerReference("<64hex>");   → usage.list
# ---------------------------------------------------------------------------
RE_ENTRY_BUNDLE = re.compile(r'src="([^"]*\.js)"')
# 路由表：usage 路由的组件源路径 + 其后不远处的动态 import chunk
RE_USAGE_ROUTE_CHUNK = re.compile(
    r'workspace/\[id\]/usage/index\.tsx.{0,600}?import\(\s*(?:/\*[^*]*\*/)?\s*"([^"]+\.js)"',
    re.S)
# 旧版兜底：名字里直接含 usage 的 chunk / -index- chunk
RE_USAGE_CHUNK = re.compile(r'"([^"]*usage[^"]*\.js)"|"([a-z0-9-]+-index-[^"]*\.js)"')
# createServerReference 及其赋值目标变量名：const getUsageInfo_1 = createServerReference("<hex>")
RE_SERVER_REF_NAMED = re.compile(
    r'(?:const\s+|var\s+|let\s+)?(\w+)(?:_\d+)?\s*=\s*createServerReference\("([a-f0-9]{64})"\)')


def _resolve_asset_url(entry_url: str, chunk: str) -> str:
    """把 bundle 内的相对 chunk 引用（'./index-x.js'、'_build/assets/x.js'）解析为绝对 URL。"""
    if chunk.startswith("http"):
        return chunk
    chunk = chunk.lstrip("./")
    if chunk.startswith("_build/"):
        return f"https://opencode.ai/{chunk}"
    base = entry_url.rsplit("/", 1)[0]          # 入口 bundle 所在目录
    return f"{base}/{chunk}"


def _find_usage_chunk(entry: str) -> str:
    """从入口 bundle 中定位 usage 路由组件 chunk 文件名。"""
    m = RE_USAGE_ROUTE_CHUNK.search(entry)
    if m and m.group(1):
        return m.group(1)
    for m in RE_USAGE_CHUNK.finditer(entry):     # 旧版兜底
        chunk = m.group(1) or m.group(2)
        if chunk:
            return chunk
    raise FetchError("入口 bundle 中未找到 usage 组件 chunk")


def _classify_server_refs(chunk_src: str) -> dict:
    """按变量名识别 usage.list 与 getCosts 的函数 ID。"""
    refs = {}
    for name, hex_id in RE_SERVER_REF_NAMED.findall(chunk_src):
        low = name.lower()
        if "usageinfo" in low or "usagelist" in low or "getusage" in low:
            refs.setdefault("usage.list", hex_id)
        elif "cost" in low:
            refs.setdefault("getCosts", hex_id)
        else:
            refs.setdefault(f"_other:{name}", hex_id)
    if "usage.list" not in refs:
        # 兜底：变量名不可识别时，取全部裸 ID，约定第一个非 costs 的为 usage.list
        all_refs = re.findall(r'createServerReference\("([a-f0-9]{64})"\)', chunk_src)
        named_costs = {v for k, v in refs.items() if k.startswith("getCosts")}
        rest = [x for x in all_refs if x not in named_costs]
        if rest:
            refs["usage.list"] = rest[0]
    return refs


def extract_server_ids(cookie: str, workspace_id: str) -> dict:
    """从前端产物中重新提取 usage 相关 Server Function ID。

    返回 {"usage.list": <64hex>, "getCosts": <64hex>}。
    """
    session = requests.Session()
    session.headers.update({"Cookie": (cookie or "").strip(), "User-Agent": UA})
    try:
        page_html = session.get(
            f"https://opencode.ai/workspace/{workspace_id}/usage", timeout=30).text
        if "<html" not in page_html.lower() or "login" in page_html.lower()[:2000]:
            raise CookieInvalidError("无法访问 usage 页面（Cookie 无效或未登录）")
        assets = RE_ENTRY_BUNDLE.findall(page_html)
        if not assets:
            raise FetchError("页面中未找到 JS bundle")
        entry_path = assets[0]
        if not entry_path.startswith("http"):
            entry_path = ("https://opencode.ai" + entry_path) \
                if entry_path.startswith("/") else f"https://opencode.ai/_build/assets/{entry_path}"
        entry = session.get(entry_path, timeout=30).text
        chunk = _find_usage_chunk(entry)
        chunk_src = session.get(_resolve_asset_url(entry_path, chunk), timeout=30).text
        refs = _classify_server_refs(chunk_src)
        if "usage.list" not in refs:
            raise FetchError("usage bundle 中未找到 createServerReference（usage.list）")
        return {"usage.list": refs["usage.list"],
                "getCosts": refs.get("getCosts", "")}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# QThread Worker
# ---------------------------------------------------------------------------
class SyncWorker(QThread):
    """后台同步线程：抓取 → 清洗 → 入库 → 结果上报。"""

    progress = Signal(int, int, int)          # page, page_records, total_so_far
    finished_ok = Signal(dict)                # {inserted, skipped, total_fetched, pages}
    failed = Signal(str, str)                 # message, kind
    stage = Signal(str)                       # 状态文本
    id_recovered = Signal(str)                # 自动恢复出的新 usage.list 函数 ID

    def __init__(self, cookie, workspace_id, server_id, db,
                 delay_ms=300, parent=None):
        super().__init__(parent)
        self._cfg = (cookie, workspace_id, server_id, delay_ms)
        self._db = db
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        cookie, wid, sid, delay = self._cfg
        try:
            self.stage.emit("正在连接 opencode.ai 并抓取调用记录…")

            # 自动恢复：函数 ID 失效/指向错误函数时，从前端 bundle 重新提取并重试一次
            raw, early_stopped, sid = self._fetch_with_heal(cookie, wid, sid, delay)

            if early_stopped:
                self.stage.emit(
                    f"检测到后续页均为已同步记录，提前停止；本次共 {len(raw)} 条新记录，正在写入数据库…")
            else:
                self.stage.emit(f"抓取完成，共 {len(raw)} 条，正在写入数据库…")
            inserted, skipped = self._db.insert_records(
                [seroval.normalize_record(r) for r in raw])
            self.finished_ok.emit({
                "inserted": inserted, "skipped": skipped,
                "total_fetched": len(raw), "pages": (len(raw) // PAGE_SIZE) + 1,
                "workspace_id": wid, "early_stopped": early_stopped,
            })
        except FetchError as e:
            self.failed.emit(e.friendly, e.KIND)
        except Exception as e:
            self.failed.emit(f"同步异常：{e}", "unknown")

    def _fetch_with_heal(self, cookie, wid, sid, delay):
        """执行分页抓取；遇 ServerIdError 时自动重新提取函数 ID 并重试一次。"""
        fetcher = UsageFetcher(cookie, wid, sid, delay_ms=delay)

        def on_progress(page, n, total):
            self.progress.emit(page, n, total)

        known_ids = self._db.all_ids()
        try:
            raw, early_stopped = fetcher.fetch_all(
                on_progress=on_progress, cancel_flag=self._cancel, known_ids=known_ids)
            return raw, early_stopped, sid
        except ServerIdError:
            if self._cancel.is_set():
                raise
            self.stage.emit("函数 ID 失效，正在从前端 bundle 自动恢复…")
            ids = extract_server_ids(cookie, wid)
            new_sid = (ids.get("usage.list") or "").strip()
            if not new_sid or new_sid == sid:
                raise
            self.id_recovered.emit(new_sid)
            self.stage.emit("已恢复函数 ID，重新开始同步…")
            fetcher2 = UsageFetcher(cookie, wid, new_sid, delay_ms=delay)
            raw, early_stopped = fetcher2.fetch_all(
                on_progress=on_progress, cancel_flag=self._cancel, known_ids=known_ids)
            return raw, early_stopped, new_sid
