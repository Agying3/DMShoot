# DMShoot 开发笔记 — 易错点与维护指南

## 1. 消息顺序：上旧下新

### 数据流
```
B站 API → _parse_message(timestamp) → save_message(DB) → get_messages(oldest first) → ChatView(上旧下新)
```

### 关键点
- `database.get_messages()` 返回 **oldest first**（`reversed()` 反转 DB 的 DESC 结果）
- `ChatView.load_messages()` 假设 messages 是 **oldest first**，通过 `insertWidget(count-1)` 插到 stretch 上方
- 渲染结果：`[bubble0(最旧) ... bubbleN(最新) stretch]`，视觉上旧在上新在下
- 打开会话时 `scrollToMaximum()` 定位到底部看最新消息

### 错误排查
- 如果消息**上下颠倒**：检查 `get_messages` 是否返回 oldest first
- 如果切会话后顺序混乱：检查缓存是否被 `sort(key=timestamp)` 了
- **严禁在 load_messages 前做额外反转**

## 2. 消息重复

### 根因
- `_sync_history` 多次调用时重复保存相同消息（没有 DB 去重）
- `handle_message` 和 `_call_ai` 双重触发 AI 回复

### 防护
- DB 层：`CREATE UNIQUE INDEX idx_messages_dedup ON messages(session_id, content, is_self, CAST(timestamp AS INTEGER))`
- 代码层：`INSERT OR IGNORE` 跳过重复
- AI 层：`handle_message` 不再 emit `bus.ai_response`（QThread 的 done 信号已处理）

### 已修复的 Bug
- `backend.py:137` — 删除了多余的 `bus.ai_response.emit()`，避免 AI 回复保存两次
- `database.py:147` — `INSERT` → `INSERT OR IGNORE`
- `database.py:68` — 添加 `idx_messages_dedup` unique index

## 3. 时间戳

### B站消息时间戳字段
B站 API 返回的消息对象可能包含以下字段之一：
- `timestamp` — Unix 秒或毫秒
- `msg_time` — 备用字段
- `mtime` / `ctime` — 额外备用

### 处理逻辑（adapter.py）
```python
ts = msg.get("timestamp", 0) or msg.get("msg_time", 0) or msg.get("mtime", 0) or msg.get("ctime", 0)
if ts > 1000000000000: ts /= 1000  # 毫秒→秒
```

### 如果时间戳全部相同
- 检查 `adapter_debug.txt` 看是否有 "时间戳缺失" 日志
- 检查 B站 API 返回的 message 对象的实际 key（`msg_keys`）

## 4. 适配器参数传递

### 问题历史
`PluginManager.create_adapter()` 从 `config` 读取 `cookie_fields` 并通过 `**kwargs` 传给适配器构造函数。
**字段名必须一致**。

### 正确配置
```python
# __init__.py
PLUGIN_INFO = {
    "cookie_fields": ["bilibili_sessdata", "bilibili_jct"],  # config 属性名
}

# adapter.py  
def __init__(self, bilibili_sessdata, bilibili_jct, bus=None):  # 参数名 = config 属性名
```

### 如果适配器启动后立即崩
- 检查 `adapter_debug.txt` 是否有 "凭证OK" / "凭证创建失败"
- 如果没有日志输出，说明 `_start_adapter` 里的 `except: pass` 吞了错误
- 手动测试：`python -c "from bilibili_api import Credential..."` 验证 cookie 有效性

## 5. SQLite 并发写

### 配置
- WAL 模式：`PRAGMA journal_mode=WAL`
- 超时：`sqlite3.connect(..., timeout=10)`
- 这些在 `database.py` 的 `_get_conn()` 中设置

### 如果遇到 "database is locked"
- 确认 WAL 模式已启用
- 降 `ThreadPoolExecutor` 的 `max_workers` 到 3
- 考虑用 `queue.Queue` 串行化写操作

## 6. QThread 闭包陷阱

### 问题模式
```python
class _V(QThread):
    def run(self):
        self.plugins.get(...)  # ❌ self 是 _V，不是 MainWindow
```

### 修复
```python
plugins = self.plugins  # 闭包捕获外部变量
class _V(QThread):
    def run(self):
        plugins.get(...)  # ✅ 用捕获的变量
```

### 适用场景
`main_window.py` 中的 `_run_async_verify`、`_call_ai` 等方法的内部类

## 7. 数据库重置

### 何时需要
- DB schema 变更后
- 出现大量重复数据后
- 测试时清空重来

### 操作
```bash
rm dmshoot/data/dmshoot.db dmshoot/data/dmshoot.db-wal dmshoot/data/dmshoot.db-shm
# 然后重启 App，重新扫码登录
```

### 注意
- 删除 DB 会**同时删除配置（API Key、Cookie）**
- 如果只想清聊天记录保留配置，用 SQL 删除 sessions/messages 表数据

## 8. 测试

```bash
cd H:\DMShoot
python test_dmshoot.py
```

7 项测试覆盖：数据模型、数据库、提示词、AI Backend、消息模型、插件、双提示词拼接。

## 9. 抖音适配器架构

### 文件结构
```
dmshoot/plugins/douyin/
├── __init__.py          # PLUGIN_INFO 注册
└── adapter.py           # DouyinAdapter（QThread，轮询模式）

dmshoot/utils/
├── douyin_sdk.py        # SDK 桥接层（绕过 execjs，用 monkey-patch 导入 SDK）
└── douyin_signer.py     # JS 签名（subprocess 调 Node.js 执行 dy_ab.js）

external/DouYin_Spider/  # 第三方 SDK（仅引用其 protobuf + API 逻辑）
├── builder/             # auth, header, params, proto
├── dy_apis/             # douyin_api.py（send_msg, get_notice_list）
├── static/              # dy_ab.js（JS 签名算法）
└── node_modules/        # jsrsasign（npm 依赖）
```

### 签名链路 (2026-06-22 重构)
```
Python adapter → douyin_signer.py
  ├── generate_req_sign()  → Python cryptography (纯 ECDSA, 无 Node 依赖)
  ├── generate_ree_key()   → Python cryptography (纯公钥导出, 无 Node 依赖)
  └── generate_a_bogus()   → subprocess Node.js → dy_ab.js (唯一需要 JS 的函数)
                                ↑ LRU 缓存 512 条, 重复调用免开销
```

### JS 签名失效排查
1. Node.js 不可用：检查 `douyin_signer.py` 的 `_find_node()` 自动发现逻辑
2. jsrsasign 缺失：`npm install jsrsasign` 在 external/DouYin_Spider（仅 a_bogus 需要）
3. NODE_OPTIONS 干扰：subprocess 显式传 `NODE_OPTIONS=""`，不受 Git Bash 影响
4. `generate_req_sign` / `generate_ree_key` 已移植到 Python，不再依赖 Node

### session_id 格式
```
douyin:{conversation_id}:{short_id}:{ticket}
```
四段冒号分隔，`send_message` 依赖此格式解析。

### 已知限制
- 发消息需要 `create_conversation` 先建立会话（如果之前没聊过）
- 通知列表 API 只返回最近 ~20 条，旧会话可能不可见
- WebSocket 实时消息已集成，通过 `wss://frontier-im.douyin.com/ws/v2` 推送 → protobuf 解码 → 本地队列 → 适配器消费

## 11. 抖音 Cookie 缺失 s_v_web_id（2026-05-29 修复）

### 根因
Playwright 扫码登录只在 `creator.douyin.com` 操作，提取的 cookie 缺少 `s_v_web_id`。
SDK 的 `get_my_uid()`、`get_notice_list()`、`send_msg()` 等多处硬依赖 `auth.cookie['s_v_web_id']`，导致 `KeyError` 崩溃。

`s_v_web_id` 只在 `www.douyin.com` 域下设置。

### 修复（双重保护）
1. **cookie_reader.py**: 登录成功后补充访问 `www.douyin.com` 获取完整 cookie
2. **douyin_sdk.py** `create_auth()`: 如果 cookie 仍缺 `s_v_web_id`，自动生成 `verify_{random}_{random}` 伪值兜底

### 排查
```bash
python -c "
from dmshoot.utils.douyin_sdk import create_auth
# ... 用 DB 中的 cookie 测试
auth = create_auth(cookie)
print(auth.cookie.get('s_v_web_id'))  # None → 需要重新扫码
"
```

## 10. protobuf_to_dict Python3 兼容

原包使用 Python2 的 `long` 和 `unicode` 类型，需手动修复：
```bash
# 修复文件: Lib/site-packages/protobuf_to_dict.py
# TYPE_INT64: long,    → TYPE_INT64: int,
# TYPE_STRING: unicode, → TYPE_STRING: str,
# TYPE_BYTES: str,     → TYPE_BYTES: bytes,
# long(                → int(
```
