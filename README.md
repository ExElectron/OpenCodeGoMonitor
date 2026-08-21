# OpenCodeGoMonitor

> [!IMPORTANT]
> **💡 AI 提示 / AI Generation Notice**  
> 本项目的核心架构、代码重构、安全校验流程与 GUI 均由 **Claude Code + DeepSeek-V4-Flash-0731** 协同生成；人类作者负责创意把控、需求定义、技术 Review 与最终决策。  
> 本项目仍应被视为一个由人类维护的开源项目：任何安全相关用途都建议先进行独立审计与充分测试。

> **一款基于 PySide6 的 OpenCode Go（opencode.ai）使用记录监控桌面工具。**  
> 实时抓取云端 API 调用记录，本地 SQLite 存储并防重，提供 5 大功能页：总览看板、明细检索、高级统计分析、多 Sheet 报表导出与系统设置。数据获取严格遵循 opencode.ai 的 **SolidStart Server Function + seroval** 私有协议（详见 [`获取Opencode_Go使用记录原理与注意事项.md`](获取Opencode_Go使用记录原理与注意事项.md)），全程纯 Python 实现，无需 Node.js。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52.svg)](https://www.qt.io/qt-for-python)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg)](https://microsoft.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ 功能特性

| 功能页 | 亮点 |
|---|---|
| 📊 **总览** | 脱敏 Cookie / 上次同步 / 秒级时钟 / 版本 / 核心设置状态；时间范围筛选（近1小时 ~ 自定义）；6 项指标卡；**模型占比环形图**（悬停 Tooltip、点击联动明细） |
| 📋 **所有使用记录** | 虚拟分页表格（滚动加载，万条不卡）；实时搜索；**异常高消耗自动标红**（成本或 Token > 均值 3 倍）；双击 / 右键打标签 |
| 📈 **高级统计** | 时间 / API Key / 模型 / 成本 / Token / 标签 **六维组合筛选**；5 类交互图表（见下）；**图表-表格反向联动**（点击热力格 / 柱段 / 散点，底部明细自动筛选）；筛选预设；内置 SQL 终端 |
| 💾 **数据导出** | CSV / **多 Sheet Excel**（`Raw_Data` / `Summary_Charts` / `By_API_Key` / `By_Model` / `说明`），后台线程执行，界面不卡顿 |
| ⚙️ **系统设置** | Cookie 管理（含文件导入）；工作区与 Server Function ID（**失效后一键从前端 bundle 恢复**）；自动同步；托盘驻留；**日 / 周 / 月花费预警 + Webhook**（钉钉 / 飞书 / 企业微信 / Telegram / 自定义）；定时导出报表；暗色 / 亮色主题 |

**高级统计页的 5 类交互图表**（均支持缩放 / 框选 / 拖拽 / 悬浮 Tooltip）：

1. 🕐 **双轴时间趋势图** —— 左轴 Token（输入/输出堆叠面积），右轴 Cost（$）折线，叠加看成本效率
2. 🔥 **调用热力图** —— 星期 × 24 小时矩阵，精准定位使用高峰期
3. 🧱 **Key × 模型堆叠柱状图** —— 直观对比各 API Key 的模型消耗结构
4. 📉 **累积成本曲线** —— 含**月底预计总花费**虚线预测
5. 💠 **单次请求散点图** —— Token × 成本，识别高消耗异常调用（标红阈值线）

---

## 🚀 快速开始

### 环境要求

- **Windows 10 / 11**（其他平台理论可运行，未充分测试）
- **Python 3.10+**
- 一个已登录 opencode.ai 的浏览器（用于复制 Cookie）

### 安装

```bash
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

### 首次配置（3 步）

1. 打开 `https://opencode.ai/workspace/<你的工作区ID>/usage`（需已登录）
2. 浏览器按 `F12` → `Network` → 刷新页面 → 复制任意请求头中的 **`Cookie: auth=...` 整行**
3. 在「系统设置 → 数据同步」粘贴保存，填入工作区 ID，点击 **立即同步**

> 首次同步会分页拉取全部历史调用记录（约每页 50 条，间隔 300ms 防限流）；**之后同步自动增量**——检测到某页全部为已同步记录即停止，通常 1-3 页 / 数秒内完成。

---

## 🧠 技术架构

### 数据获取协议（核心）

opencode.ai 的 usage 页面**没有传统 REST API**，而是基于 SolidStart 的 **Server Function（RPC）**：

```
POST https://opencode.ai/_server
请求头: Cookie / X-Server-Id(64位hex哈希) / X-Server-Instance(server-fn:N)
请求体: seroval v1 序列化的参数数组 [workspaceId, page]
响应  : seroval vanilla JS 代码（非 JSON！）
```

- **请求体编码**：`{"t":{"t":9,"i":0,"l":2,"a":[…],"o":0},"f":31,"m":[]}`
- **响应解析**：seroval 引用表 `$R[N]` + `new Date()` + `Object.assign(new Error(...))` 错误体，由 `ocgmon/seroval.py` **纯 Python 递归下降解析器**处理
- **分页**：每页 50 条，**返回 < 50 条即最后一页**
- **增量同步**：记录按时间最新→最旧排序，同步前加载已入库 ID 集合，**整页全部命中即提前停止**（实测空闲期同步 1.4s / 2 页完成）
- **函数 ID 自愈**：前端发版后 `X-Server-Id` 会失效；同步时若检测到失效/指向错误函数，
  应用会**自动从前端 bundle 重新提取并重试**，新 ID 自动保存，无需人工干预
  （也可在设置页手动点击**恢复函数ID**）

### 数据口径（与页面一致）

| 项 | 说明 |
|---|---|
| 成本 | 接口原始值单位 = **1/1e8 美元**（如 `41,201` = $0.0004），应用内已换算 |
| 总输入 Tokens | `inputTokens + cacheReadTokens + cacheWrite5mTokens + cacheWrite1hTokens` |
| 总 Tokens | 总输入 + `outputTokens` |
| 时间 | 接口返回 UTC，应用内转换为本地时间（+8） |

### 防重机制（双保险）

1. 记录 `id`（`usg_...`，API 请求唯一 ID）作为**主键**
2. 联合唯一索引 `(timestamp, model, input, output, cost)` 兜底防脏数据

批量 `INSERT OR IGNORE` 写入，重复同步自动跳过，实测重复导入 0 误插。

### 线程模型

- 所有网络请求（QThread）与 Excel 导出（QThread）均在**后台线程**执行，GUI 永不阻塞
- 错误分类处理：Cookie 失效 / 函数 ID 失效 / 接口限流 / 网络超时，均给出友好提示与修复入口

---

## 📁 项目结构

```text
OpenCodeGoMonitor/
|-- main.py                  # 程序入口
|-- requirements.txt         # 依赖清单
|-- ocgmon/
|   |-- seroval.py           # seroval v1 编解码（纯 Python，协议核心）
|   |-- fetcher.py           # 分页抓取 + 错误分类 + 函数ID恢复 + QThread Worker
|   |-- db.py                # SQLite 层（防重写入 / 聚合查询 / 标签 / 预设）
|   |-- exporter.py          # CSV / 多 Sheet Excel 导出（后台线程）
|   |-- alerts.py            # 花费预警阈值 + Webhook 通知
|   |-- theme.py             # 暗/亮主题 QSS 与 matplotlib 配色
|   |-- charts.py            # 5 类交互图表（Tooltip / 缩放 / 点击联动）
|   |-- main_window.py       # 主窗口 + 系统托盘 + 定时任务
|   `-- ui/                  # 五个选项卡 + SQL 终端 + 预设对话框
`-- 获取Opencode_Go使用记录原理与注意事项.md   # 协议逆向原理文档
```

---

## 🔍 常见问题

### 同步提示「Cookie 失效」？

Cookie 为 `@hapi/iron` 加密会话，会过期。重新从浏览器复制最新 `Cookie: auth=...` 更新即可。

### 同步提示「Server Function ID 失效」？

前端每次发版函数哈希都会变化。**v1.0.2 起同步会自动恢复并重试，通常无需任何操作**；
如仍需手动处理，可点击「系统设置」中的**恢复函数ID**按钮，应用会按赋值变量名
（`getUsageInfo_*`）从前端 bundle 精确提取 usage.list 的最新 ID。

### 接口返回 429 限流？

在「系统设置」增大请求间隔（建议 ≥ 300ms），稍后重试。

### 表格中的红字记录是什么？

单次调用成本或 Token 超过全部记录均值 **3 倍**的异常高消耗调用，被自动标红警示。

### 我的数据安全吗？

- Cookie 仅保存在本机 `%APPDATA%\OCGMonitor\config.json`，**绝不会上传**或写入日志
- 程序只做**只读**查询，不修改云端任何数据
- 本仓库不含任何真实使用记录 / Cookie / 工作区 ID（已完全脱敏）

---

## 📄 License

本项目采用 **[MIT License](LICENSE)** 开源。
欢迎 Fork、修改或集成到自己的项目中，保留版权声明即可。

