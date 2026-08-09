# -*- coding: utf-8 -*-
"""OpenCode Go 使用记录监控 (OCGMonitor)

基于《获取Opencode_Go使用记录原理与注意事项.md》中记录的
SolidStart Server Function + seroval 协议实现数据获取。
"""

APP_NAME = "OCGMonitor"
APP_TITLE = "OpenCode Go 使用记录监控"
APP_VERSION = "1.0.1"

# 默认 Server Function ID（随前端构建变化，失效时可在设置中一键恢复）
SERVER_ID_USAGE = "bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c"
SERVER_ID_COSTS = "15702f3a12ff8bff357f8c2aa154a17e65b746d5f6b96adc9002c86ee0c15205"

# 默认工作区 ID（留空 = 由用户在设置页填写自己的工作区）
DEFAULT_WORKSPACE = ""

# 成本单位：接口原始 cost = 美元 * 1e8
COST_DIVISOR = 1e8
# 分页大小
PAGE_SIZE = 50
# 时间换算：UTC → 中国标准时间
LOCAL_TZ = "Asia/Shanghai"
