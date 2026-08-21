# 获取 OpenCode Go 使用记录（Usage）原理与注意事项

> 本文档详细记录如何从 opencode.ai 云平台（Zen）工作区导出全部 API 调用记录（usage）的原理、完整操作步骤与注意事项。
> 文档基于 2026-08-08 实测完成（工作区以 `<WORKSPACE_ID>` 占位，成功导出全部调用记录）。

---

## 目录

1. [总体思路](#一总体思路)
2. [技术原理](#二技术原理)
   - 2.1 前端架构：SolidStart + Server Function
   - 2.2 Server Function 调用协议
   - 2.3 如何定位 Server Function ID
   - 2.4 seroval 序列化格式（请求体）
   - 2.5 响应格式与解析
   - 2.6 分页机制
   - 2.7 认证机制
   - 2.8 数据模型与单位换算
3. [完整操作步骤](#三完整操作步骤)
4. [注意事项](#四注意事项)
5. [故障排查](#五故障排查)
6. [附录](#六附录)

---

## 一、总体思路

opencode.ai 的 usage 页面数据**不是通过传统 REST API 返回的**，而是基于 SolidStart 框架的 **Server Function（服务端函数，RPC 机制）**在服务端执行查询后以流式序列化结果返回。

因此导出数据的核心路径是：

```
1. 获取登录 Cookie（认证）
2. 从前端 JS Bundle 中定位 usage 对应的 Server Function ID
3. 构造 seroval 序列化的请求体，POST 到 /_server 端点
4. 按页（每页 50 条）循环拉取全部数据
5. 解析 seroval 响应 → 清洗 → 生成 Excel
```

---

## 二、技术原理

### 2.1 前端架构：SolidStart + Server Function

- opencode.ai 前端是 **SolidStart**（SolidJS 的全栈框架）应用，构建产物位于 `/_build/assets/*.js`。
- SolidStart 提供了 **Server Function** 机制：前端代码通过 `createServerReference` 注册一个"服务端函数"，前端可以直接像调用本地函数一样调用它，框架底层自动完成 HTTP 请求与序列化。
- usage 页面的组件代码中定义了两个服务端函数：
  - `getUsageInfo(workspaceId, page)` —— 调用记录列表（分页）
  - `getCosts(...)` —— 成本图表数据（需要额外时间范围参数）

这些函数在浏览器端实际执行时，会被编译为对 `/_server` 端点的 POST 请求。

### 2.2 Server Function 调用协议

所有 Server Function 的调用统一发送到：

```
POST https://opencode.ai/_server
```

**请求头（Headers）**

| Header | 说明 |
|---|---|
| `Cookie` | 登录凭证（`auth=Fe26.2**...`） |
| `X-Server-Id` | 目标函数的唯一标识，**64 位十六进制哈希**（函数名的 hash，随构建变化） |
| `X-Server-Instance` | 请求实例标识，形如 `server-fn:0`、`server-fn:1`…（每次调用递增，用于关联流式响应） |
| `Content-Type` | `application/json` |

实测中 usage 列表函数（`usage.list`）的 ID 为：

```
bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c
```

成本图表函数（`getCosts`）的 ID 为：

```
15702f3a12ff8bff357f8c2aa154a17e65b746d5f6b96adc9002c86ee0c15205
```

> ⚠️ 这两个 ID 是构建期的哈希，**前端每次发版后可能变化**，失效时需按 2.3 重新提取。

### 2.3 如何定位 Server Function ID

当前端更新导致函数 ID 失效时，需要从前端产物中重新提取。

> ⚠️ **2026-08 实测修正（重要）**：
> 1. **不能按出现顺序取 ID**。早期版本 usage 组件 bundle 中 `usage.list` 排在第一个，
>    但 2026-08 版本 `getCosts` 排在了前面。必须**按赋值目标变量名识别**：
>    `const getUsageInfo_1 = createServerReference("<64hex>")` → usage.list；
>    `const getCosts_1 = createServerReference("<64hex>")` → getCosts。
> 2. **chunk 文件名不再含 "usage" 字样**。新版入口 bundle 中 chunk 是纯哈希名
>    （如 `./index-CtXx_w0m.js`），需从路由表定位：
>    找到 `"src": "src/routes/workspace/[id]/usage/index.tsx?..."` 后就近的
>    `import("./index-CtXx_w0m.js")` 即为 usage 组件 chunk。
>
> 把 getCosts 的 ID 当成 usage.list 调用时，服务端返回
> `Object.assign(new RangeError("Invalid time value"), {...})`（因为 getCosts 需要时间范围参数），
> 表现为"同步失败/响应解析失败"而非 404，容易误判为 Cookie 问题。

```bash
# ① 下载 usage 页面 HTML（需带 Cookie，否则只会拿到登录页）
curl -s "https://opencode.ai/workspace/<WORKSPACE_ID>/usage" \
  -H "Cookie: auth=Fe26.2**..." \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ..." \
  -o page.html

# ② 从 HTML 中找出入口 bundle 地址
grep -oE 'src="[^"]*\.js"' page.html

# ③ 下载入口 bundle，从路由表中定位 usage 组件 chunk
#    搜索 "workspace/[id]/usage/index.tsx"，其后不远处的 import("./xxx.js") 就是 chunk 名
curl -s "https://opencode.ai/_build/assets/<entry-client-xxx>.js" -o entry.js

# ④ 下载 usage 组件 bundle，按变量名提取 server function ID
curl -s "https://opencode.ai/_build/assets/index-CtXx_w0m.js" -o usage.js
grep -oE '\w+ ?= ?createServerReference\("[a-f0-9]{64}"\)' usage.js
#    getUsageInfo_* = createServerReference(...)  → usage.list（调用记录）
#    getCosts_*     = createServerReference(...)  → getCosts（成本图表）
```

2026-08-21 实测值（会随发版变化）：

```
usage.list: bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c
getCosts  : 15702f3a12ff8bff357f8c2aa154a17e65b746d5f6b96adc9002c86ee0c15205
usage 组件 chunk: index-CtXx_w0m.js（纯哈希命名，不含 "usage" 字样）
```

同时可在 bundle 中搜索以下关键信息：
- `PAGE_SIZE` 常量（分页大小，实测 50）
- `(cost ?? 0) / 1e8` 的显示逻辑（确认成本单位）
- `createServerReference` 附近的函数定义与参数结构

### 2.4 seroval 序列化格式（请求体）

Server Function 的参数通过 **seroval** 库序列化。SolidStart 旧版（vanilla 模式）使用的 seroval v1 格式如下：

**请求体整体结构**

```json
{
  "t": "<序列化参数树>",
  "f": 31,
  "m": []
}
```

- `t`（tree）：参数数组的序列化树
- `f`（features）：功能特性位掩码，`31 ^ (disabledFeatures || 0)`，默认 31
- `m`（marked）：被标记的特殊引用集合，普通参数为空数组

**seroval v1 节点类型表**

节点为对象 `{ t, i, s, l, c, a, o, ... }`，关键字段：

| `t` | 类型 | 结构 | 说明 |
|---|---|---|---|
| `0` | Number | `{"t":0,"s":<数字>}` | 普通数字 |
| `1` | String | `{"t":1,"s":"<字符串>"}` | 字符串（含转义） |
| `2` | Enum | `{"t":2,"s":<0-7>}` | 枚举：0=null、1=undefined、2=true、3=false、4=-0、5=+Infinity、6=-Infinity、7=NaN |
| `3` | BigInt | `{"t":3,"s":"<字符串>"}` | BigInt（字符串形式） |
| `9` | Array | `{"t":9,"i":<refId>,"l":<长度>,"a":[<子节点>],"o":<0-3>}` | 数组；`i` 为引用索引（首个被引用对象为 0），`o` 为可扩展性（0=可扩展/1=不可扩展/2=封闭/3=冻结） |
| 其他 | Object/Date/RegExp/Map/Set 等 | ... | 复杂对象有各自的节点类型编号 |

**参数 `["<workspaceId>", 0]`（第 0 页）的完整编码示例**

```json
{
  "t": {
    "t": 9,
    "i": 0,
    "l": 2,
    "a": [
      { "t": 1, "s": "<WORKSPACE_ID>" },
      { "t": 0, "s": 0 }
    ],
    "o": 0
  },
  "f": 31,
  "m": []
}
```

> 关键点：外层数组是唯一被注册引用的对象，`i: 0`；字符串与数字不注册引用，直接内联。
> 换页时仅需把 `a[1].s` 改为页码（1、2、3…）。

### 2.5 响应格式与解析

**响应内容**不是 JSON，而是 **seroval vanilla 模式的 JS 代码**（可执行的自解引用脚本），形如：

```js
;0x00006093;((self.$R=self.$R||{})["server-fn:0"]=[],($R=>$R[0]=[$R[1]={id:"usg_...",...},...])($R["server-fn:0"]))
```

其执行逻辑：
1. `self.$R["server-fn:0"] = []` —— 在全局对象上创建引用表
2. 通过 IIFE 把记录数组填充到 `$R[0]`，记录中的嵌套对象（如 `new Date(...)`、`enrichment`）用 `$R[N]` 引用去重存储
3. 末尾 `($R["server-fn:0"])` 引用裸的 `$R` —— 在浏览器中 `self === window`，因此 `self.$R` 赋值后全局变量 `$R` 自动可见

**Node.js 中解析的坑**：Node 的 `vm` 沙箱中 `self` 不是全局对象别名，直接 eval 会抛 `ReferenceError: $R is not defined`，且由于错误发生在**最后一个逗号表达式**，前面的数据赋值已完成——所以只需捕获异常即可，数据已经填充。

**推荐的解析方法**（关键：先注入 `self === globalThis`）：

```js
const vm = require('vm');

function parseSeroval(text) {
  const ctx = vm.createContext({});
  // ★ 关键：让 self 指向沙箱全局，裸 $R 才能解析成功
  vm.runInContext(
    'Object.defineProperty(globalThis, "self", { value: globalThis, configurable: true, writable: true });',
    ctx
  );
  try {
    vm.runInContext(text, ctx, { timeout: 5000 });
  } catch (e) {
    // 尾表达式可能抛错（$R 未定义），但数据已填充，忽略
  }
  const SR = vm.runInContext('typeof $R === "undefined" ? null : $R', ctx);
  if (!SR) return null;
  for (const k of Object.keys(SR)) {
    const v = SR[k];
    // ★ 数据在 $R["server-fn:N"][0]，外层是空数组
    if (Array.isArray(v) && Array.isArray(v[0])) return v[0];
    if (Array.isArray(v) && v.length && typeof v[0] === 'object' && v[0] !== null) return v;
  }
  return null;
}
```

**数据位置速记**：

```
self.$R["server-fn:0"] = []          ← 空数组（外层容器）
self.$R["server-fn:0"][0] = [...50条记录]  ← 真正的数据
self.$R[1], $R[3]... = 记录中的 Date/enrichment 等引用对象
```

### 2.6 分页机制

- `getUsageInfo(workspaceId, page)` 按页返回，**每页 50 条**（`PAGE_SIZE = 50`）。
- 判断逻辑：**返回条数 == 50 时继续请求下一页**，返回条数 < 50 说明已是最后一页。
- 实测：52 页共 2569 条（51 页满 50 条 + 最后 1 页 19 条）。
- 翻页参数是 `page`（0 起始），不是游标。

### 2.7 认证机制

- opencode.ai 使用 OAuth（GitHub / Google）登录，登录后下发名为 `auth` 的 Cookie。
- Cookie 值以 `Fe26.2**` 开头 —— 这是 **@hapi/iron 加密格式**（HMAC + 对称加密），内容包含会话信息与时间戳，无法本地伪造或解密。
- 服务端校验 Cookie：未登录或过期时，页面跳转登录页，`/_server` 接口拒绝服务。
- 因此**必须**从用户已登录的浏览器中获取 Cookie：
  1. 打开 usage 页面（已登录）
  2. `F12` → Network → 刷新 → 点任意请求
  3. 复制 Request Headers 中的 `Cookie: auth=Fe26.2**...` 整行

### 2.8 数据模型与单位换算

**记录字段字典**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 记录 ID（`usg_...`） |
| `workspaceID` | string | 工作区 ID（`wrk_...`） |
| `timeCreated` | ISO 时间 | 调用创建时间（**UTC**） |
| `timeUpdated` | ISO 时间 | 最后更新时间（UTC） |
| `timeDeleted` | null | 软删除标记（正常为空） |
| `model` | string | 模型名（如 `deepseek-v4-flash`） |
| `provider` | string | 提供方（如 `inf-go.oa-compat`） |
| `inputTokens` | int | 本次输入 token 数 |
| `outputTokens` | int | 本次输出 token 数 |
| `reasoningTokens` | int | 推理（思考）token 数 |
| `cacheReadTokens` | int | 命中缓存的输入 token 数 |
| `cacheWrite5mTokens` | int/null | 5 分钟缓存写入 token 数 |
| `cacheWrite1hTokens` | int/null | 1 小时缓存写入 token 数 |
| `cost` | int | **成本原始值，单位 = 1/1e8 美元** |
| `keyID` | string | 发起调用的 API Key（`key_...`） |
| `sessionID` | string | 会话 ID（当前为空） |
| `enrichment` | object | 附加信息（如 `{plan:"lite"}`，lite 即 go 计划） |

**成本单位换算（重要）**

页面显示的金额为：`(cost ?? 0) / 1e8`，保留 4 位小数（从 bundle 代码 `((usage2.cost ?? 0) / 1e8).toFixed(4)` 确认）。

| cost 原始值 | 换算美元 |
|---|---|
| 41,201 | $0.0004 |
| 11,892,420 | $0.1189 |
| 370,560,467（总计） | $3.7056 |

**页面口径的 token 汇总公式**（与页面表格一致）：

```
总输入Tokens = inputTokens + cacheReadTokens + cacheWrite5mTokens + cacheWrite1hTokens
总Tokens     = 总输入Tokens + outputTokens
```

**时间换算**：接口时间为 UTC（ISO 8601，`Z` 结尾），页面显示浏览器本地时间。中国用户（GMT+8）需 **+8 小时**。

---

## 三、完整操作步骤

### 步骤 1：获取登录 Cookie

按 2.7 的方法从浏览器 DevTools 复制 `Cookie: auth=...` 整行。

### 步骤 2：验证访问有效

```bash
curl -s -o /dev/null -w "%{http_code}" \
  "https://opencode.ai/workspace/<WORKSPACE_ID>/usage" \
  -H "Cookie: auth=Fe26.2**..."
# 返回 200 表示 Cookie 有效；返回 3xx/401 表示需重新登录
```

### 步骤 3：确认 Server Function ID（如失效则按 2.3 重新提取）

确认 `X-Server-Id` 为 usage 列表函数的 64 位哈希（当前版本见 2.2）。

### 步骤 4：编写脚本循环拉取

参考脚本（Node.js 原版；本项目以纯 Python 实现了相同逻辑，见 `ocgmon/seroval.py` 与 `ocgmon/fetcher.py`）：

```js
const fs = require('fs');
const vm = require('vm');

const WORKSPACE_ID = 'wrk_...';
const COOKIE = 'auth=Fe26.2**...';
const SERVER_ID_USAGE = 'bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c';
const PAGE_SIZE = 50;

// 构造 seroval v1 请求体（参数: [workspaceId, page]）
function encodeArgs(workspaceId, page) {
  return JSON.stringify({
    t: { t: 9, i: 0, l: 2, a: [{ t: 1, s: workspaceId }, { t: 0, s: page }], o: 0 },
    f: 31,
    m: []
  });
}

async function callServer(serverId, body, instance) {
  const res = await fetch('https://opencode.ai/_server', {
    method: 'POST',
    headers: {
      'Cookie': COOKIE,
      'X-Server-Id': serverId,
      'X-Server-Instance': `server-fn:${instance}`,
      'Content-Type': 'application/json',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...'
    },
    body
  });
  return { status: res.status, text: await res.text() };
}

// parseSeroval：见 2.5 节

async function main() {
  let all = [], page = 0, instance = 0;
  while (true) {
    const r = await callServer(SERVER_ID_USAGE, encodeArgs(WORKSPACE_ID, page), instance++);
    if (r.status !== 200) { console.error('HTTP', r.status, 'page', page); break; }
    const records = parseSeroval(r.text);
    console.log(`page ${page}: ${records.length} records`);
    all = all.concat(records);
    if (records.length < PAGE_SIZE) break;   // ★ 分页终止条件
    page++;
    await new Promise(res => setTimeout(res, 300));  // 请求间隔，防限流
  }
  fs.writeFileSync('usage_raw.json', JSON.stringify(all, (k, v) => v instanceof Date ? v.toISOString() : v, 2));
  console.log('total:', all.length);
}
main();
```

### 步骤 5：清洗数据并生成 Excel

建议使用 Python + openpyxl（本项目由 `ocgmon/exporter.py` 实现）：

- **Sheet「调用记录」**：明细表（19 列），冻结首行 + 自动筛选 + 总计行
- **Sheet「按模型汇总」**：模型 × 次数/token/成本/占比
- **Sheet「按日期汇总」**：每日调用量与成本
- **Sheet「按API Key汇总」**：各 Key 的使用分布
- **Sheet「说明」**：字段口径、单位说明
- 成本列格式 `0.0000`，token 列 `#,##0`，时间转北京时间

---

## 四、注意事项

### 安全类（最重要）

1. **Cookie 是敏感凭据**：`auth` Cookie 等效于账号登录态，任何持有者都能读取全部数据。获取、传输、存储都要小心：
   - 不要在对话/日志中复述完整 Cookie
   - 工作目录中的 cookie 文件使用后及时删除
   - 建议在隔离环境执行脚本，脚本中的 Cookie 用环境变量或单独配置文件（加入 `.gitignore`）注入
2. **仅做只读操作**：本方案只调用查询类 Server Function，不修改任何数据。

### 稳定性类

3. **Server Function ID 会失效**：`X-Server-Id` 是构建期哈希，前端发版后变化。发现 `404`/函数不存在时，按 2.3 重新从前端 bundle 提取。
4. **Cookie 会过期**：iron 加密的会话带时间戳，过期后请求返回跳转登录页。需用户重新提供。
5. **接口可能限流**：循环拉取时建议请求间隔 200–500ms；如遇 `429` 或大量 `500`，增大间隔并重试。

### 数据类

6. **成本单位是 1/1e8 美元**：不是整数美元、不是美分。换算错误会导致金额差 8 个数量级。
7. **时间是 UTC**：导出到 Excel 时需转北京时间（+8h），否则每条记录显示比实际早 8 小时。
8. **字段可能为 null**：`cacheWrite5mTokens`/`cacheWrite1hTokens` 大多为 null（本次仅 1 条非空），`sessionID`/`timeDeleted` 为空；清洗时统一按 0/空处理。
9. **总输入口径**：页面"总输入"含缓存读+缓存写，与 `inputTokens` 单列不同，注意区分。
10. **分页终止条件**：必须用「返回条数 < 50」判断结束，不能假设固定页数；使用游标翻页（page+1）而不是依赖时间排序。

### 工程类

11. **响应不是 JSON**：是 seroval JS 代码，必须用 vm/eval 解析（见 2.5）；直接 `JSON.parse` 会失败。
12. **Node 解析必须注入 `self`**：忘记注入 `self === globalThis` 时数据不会填充（IIFE 未执行），表现为返回空数组而非报错，容易误判为"没有数据"。
13. **请求头要带浏览器 UA**：部分 CDN/网关对非浏览器 UA 请求有拦截风险。
14. **getCosts 参数不同**：成本图表函数需要时间范围参数（实测传 `[workspaceId]` 会报 `Invalid time value`）；如需图表数据，需从 bundle 中反推其完整参数结构。

---

## 五、故障排查

| 现象 | 原因 | 解决方案 |
|---|---|---|
| `GET /usage` 返回登录页（OpenAuth） | Cookie 缺失/过期 | 重新获取有效 Cookie |
| `POST /_server` 返回 `{"status":500,"message":"HTTPError"}` | seroval 请求体格式错误（节点类型/features 不对）或函数 ID 失效 | 核对 2.4 的节点格式；确认 `X-Server-Id` |
| 响应为 `new RangeError("Invalid time value")` | 函数 ID 实际指向 getCosts（参数结构不同），常见于按顺序提取 ID 的新版前端 | 按 2.3 用变量名重新识别 usage.list 的 ID |
| 解析报「不支持的构造函数 new RangeError()」 | 解析器未处理非 Error 的错误构造函数（旧版本缺陷，v1.0.3 已修复） | 升级到 v1.0.3+ |
| 解析时 `ReferenceError: $R is not defined` | 未注入 `self === globalThis` | 按 2.5 注入后重试（数据其实已填充，可忽略异常） |
| 解析返回 0 条 | 读取了 `$R["server-fn:N"]`（空容器）而不是 `[...][0]` | 数据在 `$R["server-fn:N"][0]` |
| `Invalid time value`（RangeError） | 调用了 `getCosts` 但参数结构不对 | 从 bundle 反推参数，或忽略（不影响列表数据） |
| 某页请求 429/超时 | 请求过快 | 增大间隔、加重试 |
| 页数与预期不符 | 分页终止条件写错 | 以「返回 < 50」为终止条件 |

---

## 六、附录

### 6.1 实测要点（2026-08-08 验证通过）

- 协议链路：`Cookie 校验 → POST /_server → seroval 解析 → 分页循环 → 数据入库` 全流程可用。
- 分页终止条件「返回 < 50 条」实测可靠；请求间隔 300ms 未触发限流。
- 同一协议在 [OpenCodeGoMonitor](https://github.com/WSShuibuzhao/OpenCodeGoMonitor) 中由
  纯 Python 实现（`ocgmon/seroval.py` 编解码 + `ocgmon/fetcher.py` 分页抓取），无需 Node.js。

### 6.2 参考实现文件清单

| 文件 | 说明 |
|---|---|
| `ocgmon/seroval.py` | seroval v1 请求体编码 + 响应解析（纯 Python） |
| `ocgmon/fetcher.py` | 分页抓取、错误分类、函数 ID 自动恢复 |
| `ocgmon/db.py` | SQLite 入库（防重）+ 聚合查询 |
| `ocgmon/exporter.py` | 多 Sheet Excel / CSV 导出 |

### 6.3 参考链接

- opencode.ai 工作区 usage 页面：`https://opencode.ai/workspace/<WORKSPACE_ID>/usage`
- SolidStart Server Function 文档（概念参考）：`https://docs.solidjs.com/solidstart/concepts/server-functions`
- seroval 序列化库：`https://github.com/lxsmnsyc/seroval`
