# DMShoot 易错点 & 维护指南

> 本文档记录 DMShoot 项目中反复出现的问题、根因和维护注意事项。
> 每次修 bug 后如果发现新的坑，请追加到对应章节。

## 1. 消息去重

### 问题表现
同一条消息在聊天界面重复出现（如"送花花"出现 4 次）。

### 根因分析
消息有 **三个来源**，每个来源可能产生重复：

| 来源 | 入口 | 时间戳 | session_id 格式 |
|------|------|--------|----------------|
| 历史同步 | `sync_messages_to_db` → 直接写 DB | 假时间戳（`base_ts + msg_idx * 60`） | `douyin:0:1:{peer}:{my}:0:` |
| WS 实时 | `_poll_messages` → `_on_message` → bus → DB | 真实时间戳（从 `server_message_id` 推导） | `douyin:{conv_short_id}:0:`（已修复→统一用 peer_uid 格式） |
| B站轮询 | `_poll_session` → bus → DB | 真实时间戳 | `bilibili:{sender_uid}` |

**三个路径有不同的时间戳**，因此 DB 唯一索引不能依赖时间戳。

### 去重防线（三层）

1. **适配器内存** (`_replied` set)：key = `{conv_id}:{msg_index}`，msg_index 是 protobuf 级唯一序号
2. **UI 缓存** (`home_page.py add_message`)：检查最近 5 条的 `sender_name + content`
3. **DB 唯一索引**：`(session_id, content, is_self)` —— 不包含时间戳！

### 维护注意
- ⚠️ 修改 `douyin_msg_sync.py` 的 `sync_messages_to_db` 时，确保不产生与 WS 路径相同的 `(session_id, content, is_self)` 组合
- ⚠️ DB 索引 `idx_messages_dedup` 改为不含时间戳后，`INSERT OR IGNORE` 会静默丢弃（第一条写入的数据保留）
- ⚠️ `_replied` set 持久化到 `douyin_state.json`，重启后恢复，避免 WS 重连后重复推送

## 2. session_id 映射（抖音特有）

### 问题表现
- 自己的消息不显示（点了联系人看不到自己发的）
- 同一对话在不同地方用不同 session_id

### 根因
抖音有两个 ID 体系：

| ID | 来源 | 示例 |
|----|------|------|
| `peer_uid` | 用户唯一 ID（长数字） | `109456910122` |
| `conversation_short_id` | 会话短 ID（WS 消息中） | `7149001234567890` |

- 历史同步用 `peer_uid` 格式：`douyin:0:1:{peer}:{my}:0:`
- WS 消息用 `conversation_short_id` 格式：`douyin:{short_id}:0:`
- **通讯录用 `peer_uid` 格式**，所以 WS 路径必须做映射

### 解决方案
`adapter.py` 维护 `_conv_to_peer` 字典：
```python
_conv_to_peer: dict[str, str] = {}
# 收到对方消息时建立映射: conv_short_id → peer_uid
# 发消息时用 conv_short_id 反查 peer_uid 得到正确的 session_id
```

### 维护注意
- ⚠️ 新增消息推送路径时，必须先做 `conv_short_id → peer_uid` 映射
- ⚠️ 该映射在内存中，重启后丢失——启动时从 DB 重建（`_get_peer_uid_for_conv`）
- ⚠️ 映射假设 `conv_short_id` 和 `peer_uid` 是 1:1 关系，群聊场景需要重新设计

## 3. 消息时间戳

### 问题表现
所有消息显示相同或相近的时间（当前时间）。

### 根因
`douyin_ws.py` `on_message` 使用了 `time.time()` 而非消息的真实时间：
```python
# ❌ 错误
"timestamp": time.time()

# ✅ 正确
"timestamp": server_msg_id / 1000.0  # 从 protobuf server_message_id 推导
```

### 时间戳来源层级
1. **最优**：protobuf 中的 `server_message_id`（毫秒级时间戳，编码在高位）
2. **次优**：protobuf 中的 `conversation_short_id`（同编码方式）
3. **兜底**：`time.time()`（仅用于无法从 proto 提取时）

### 维护注意
- ⚠️ 如果 protobuf 定义更新，检查 `server_message_id` 字段名是否变化
- ⚠️ B站的 timestamp 从 API 响应直接获取，不需要推导

## 4. 侧边栏状态标签

### 问题表现
左下角"抖音 ✕ / B站 ✕ / AI ✕"被裁切，显示不全。

### 根因
- 侧边栏宽度 80px 太窄（已改为 90px）
- 全局 QSS `QWidget { font-size: 14px }` 覆盖了小标签的字体
- 底部 `border-radius: 16px` 圆角遮挡了最后一个标签

### 解决方案
1. `sidebar.py`：`setFixedWidth(90)`、标签设 `objectName="statusLabel"`
2. `styles.qss`：`QLabel#statusLabel { font-size: 10px; padding-bottom: 10px }` 用高特异性选择器覆盖
3. `lbl.raise_()` 确保 Z 序在最上层

### 维护注意
- ⚠️ 全局 `QWidget { font-size: 14px }` 会影响所有没单独设 objectName 的 QLabel
- ⚠️ 修改侧边栏高度时确保底部标签有足够的 padding

## 5. _enrich_all 函数

### 问题表现
抖音通讯录昵称显示为 `用户XXXX`，头像为空。

### 根因
`douyin_im_sync.py` 中 `_enrich_all()` 被调用但从未定义，`NameError` 被 `except: pass` 吞掉。

### 解决方案
实现了 `_enrich_all()` 用 requests 调抖音用户 API 补全昵称和头像。
**关键**：全部是占位名时抛 `RuntimeError` 阻止脏缓存写入。

### 维护注意
- ⚠️ 抖音用户 API 的 `Referer` 必须设为 `https://www.douyin.com/`
- ⚠️ 头像下载也要带 `Referer`，否则可能返回 100×100 占位图
- ⚠️ `contact.py` 的头像缓存会检查文件大小（<4KB 丢弃），避免缓存占位图

## 6. 缓存层级（抖音）

```
L1: JSON 缓存 (dy_conv_{key}.json) — 完整结果，秒级加载
L2: Protobuf 缓存 (im_init_{key}.bin) — 需解析+API补全昵称
L3: Playwright 子进程 — 首次/重登时拉取
```

### 维护注意
- ⚠️ L1 缓存只在昵称非占位名时才写入（`has_names` 检查）
- ⚠️ L2 缓存 `_enrich_all` 成功后单独保存 JSON 缓存，失败则保留原始数据待下次重试
- ⚠️ 删 JSON 缓存文件即可强制重新拉取（protobuf 缓存可保留）

## 7. 数据库唯一索引变更

### 历史
```
v1: (session_id, content, is_self, CAST(timestamp AS INTEGER))
v2: (session_id, content, is_self)  — 去掉 timestamp
```

### 变更原因
不同消息路径给同一消息分配不同的时间戳（假时间戳 vs 真实时间戳），导致同一消息被当作两条记录插入。

### 维护注意
- ⚠️ 修改唯一索引需要 `DROP INDEX IF EXISTS` 再 `CREATE UNIQUE INDEX IF NOT EXISTS`
- ⚠️ 先清理已有重复数据再创建新索引
- ⚠️ `save_message` 使用 `INSERT OR IGNORE`，所以第一条插入的数据保留

## 8. 终端日志格式

### 标准格式
```
MM-DD HH:MM:SS [LEVEL] module.name | content
```

### 级别
- `INFO` (白) — 常规信息
- `SUCCESS` (绿) — 操作成功
- `THINKING` (青) — AI 思考过程
- `WARNING` (黄) — 警告
- `ERROR` (红) — 错误

### 特殊方法
- `logger.ai_thinking(msg)` → `<Thinking>` 前缀，青色
- `logger.ai_msg(msg)` → `<msg>` 前缀，绿色
- `logger.recv(平台, 发送者, 内容)` → `[抖音] 名字: 内容`

### 维护注意
- ⚠️ `setup_console_logging()` 在 `main.py` 最早调用
- ⚠️ 三方库日志设 `WARNING` 及以上（`websocket` 设 `CRITICAL` 完全静默）
- ⚠️ `_WrappedWS` 的 `on_error/on_close/on_open` 用 lambda 包装，不走 SDK 的 `print()`

## 新增 2026-05-30

### sync_messages_to_db 已禁用
- **问题**：用正则从 protobuf 二进制提取中文，生成假时间戳（base_ts + idx * 60）
- **后果**：假时间戳进 DB → 同一条消息因 timestamp 不同被唯一索引放过 → 重复显示
- **决策**：完全禁用。消息只走 WS 实时路径，时间戳用 time.time() 做实时消息近似
- **TODO**：未来从 protobuf server_message_id（snowflake编码）解码真实时间戳

### 侧边栏状态标签位置
- **问题**：标签在侧边栏底部，被 border-bottom-left-radius: 16px 圆角裁切
- **解决**：移到顶部（logo 下方、导航按钮上方），彻底避开底部圆角区域
