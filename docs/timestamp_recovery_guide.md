# DMShoot 抖音历史消息真实时间戳恢复指南

> 最后更新：2026-06-01
> 涉及文件：`dmshoot/utils/proto_msg_parser.py`、`dmshoot/utils/douyin_ws.py`

---

## 1. 当前现状

`proto_msg_parser.py` 已能从 protobuf 缓存（`dmshoot/data/cache/im_init_*.bin`）中提取消息正文，但时间戳可能不准确。当前时间戳来源是：

```python
# proto_msg_parser.py 当前逻辑
ts = _decode_timestamp(server_msg_id or 0, conv_short_id or 0)
```

`_decode_timestamp` 函数（`douyin_ws.py:17-40`）对 WS 实时消息有效，但对历史 protobuf 中的 ID 可能使用了不同的 ID 格式。

---

## 2. 根因：Protobuf 中的 ID 值不是标准的 Unix 时间戳

以下是你的 protobuf 缓存文件中提取的三条真实数据：

| 字段 | 样本值（十进制） | 十六进制 |
|------|-----------------|----------|
| server_message_id | 7645676067076097573 | `0x6a1ae5dfddc6c625` |
| ▸ 下一条 | 7645686933779678769 | `0x6a1aefc1f7c88631` |
| ▸ 差值 | 10866670361296 | — |
| index (field 0x20) | 1672502400020000 | — |
| conversation_short_id | 48 | `0x30` |

**关键发现**：
- `server_message_id` 相邻两条差值 ≈ 10.8 秒（微秒级），说明**时间戳编码在 ID 内部**，但不是直接 `/1e6` 能解的
- `index` 字段（field 0x20）值 `1672502400xxxxxx` 看起来更像一个微秒级时间戳，1672502400 秒 ≈ 2023-01-01 00:00 UTC
- 单纯 `/1e6`、`/1e3`、`/1` 都得到超出范围的值，说明 ID 用了**自定义 epoch（基准时间）** 或 **位偏移编码**

---

## 3. 抖音 ID 编码方案推断

抖音的 `server_message_id` 很可能采用 **Snowflake 风格** 分布式 ID：

```
┌─────────────────────────────────────────────────────────┐
│  timestamp_delta  │  worker_id  │  datacenter  │  seq  │
│   (41 bits)       │  (5 bits)   │  (5 bits)    │ (12)  │
└─────────────────────────────────────────────────────────┘
   ↑ Bit 63                                                  Bit 0 ↑
```

时间戳不是完整的 Unix 毫秒，而是 **自定义 epoch 之后的毫秒数**，存储在 ID 的高位。

### 如何解码

以样本 `0x6a1ae5dfddc6c625` 为例：

```python
sid = 7645676067076097573

# 方案 A：右移 22 位（经典 Snowflake）+ 自定义 epoch
delta = sid >> 22            # 1822778733044 毫秒

# 方案 B：右移 23 位
delta = sid >> 23            # 911389366522

# 方案 C：前 6 个 hex 字符 = 时间戳秒（某些抖音变体）
hex(sid)[:6]                 # "6a1ae5" → 旧字节序
```

### epoch（基准时间）推断

Snowflake 常用的 epoch：
| 平台 | epoch | 说明 |
|------|-------|------|
| Twitter | 1288834974657 | 2010-11-04 (ms) |
| Discord | 1420070400000 | 2015-01-01 (ms) |
| 抖音 | ? | 需实验确定 |

如果 `delta = sid >> 22 = 1822778733044`（毫秒），echo 可能是抖音 IM 上线的时间点：

```
(1822778733044 / 1000) - (2026年中某个日期的 Unix 秒) = 抖音 epoch
```

---

## 4. 诊断方法：提取原始值并反推编码

### 步骤 4.1：运行诊断脚本

```bash
cd H:\DMShoot
python scripts/test_proto_parse.py
```

观察输出中每一条消息的 `srv_id`、`short_id`、`index` 字段值。

### 步骤 4.2：手动计算时间戳

取前 3 条消息的 `srv_id`，用多种方案尝试还原：

```python
sid = 7645676067076097573  # 替换为实际值

# 方案 1：右移 22 位 + 尝试 epoch
ts_ms = (sid >> 22)
# 假设 epoch = 某个抖音内部时间
# ts = epoch + ts_ms
# print(datetime.fromtimestamp(ts / 1000))

# 方案 2：右移 23 位
ts_ms = (sid >> 23)

# 方案 3：直接取前 48 位
ts_ms = (sid >> 16)

# 方案 4：按字节解析（大头序）
import struct
ts_bytes = sid.to_bytes(8, 'big')
ts = struct.unpack('>Q', ts_bytes)[0]
```

### 步骤 4.3：用对话内容反推

如果你记得某条消息的大致发送时间（比如"昨天下午 3 点左右发的"），可以：
1. 查到这条消息的 `srv_id`
2. 用各种 delta + epoch 组合去试
3. 找到 delta 能匹配到"昨天下午 3 点"的那个公式

这就是正确的解码方式。

### 步骤 4.4：对比 WS 时间戳

WS 实时消息的时间戳是准确的（`douyin_ws.py` 已验证）。同一条消息如果在 WS 和历史 protobuf 里都有，可以对比两边的 ID 值来反推编码差异。

---

## 5. 修复方案

### 方案 A：精确解码（推荐）

确定抖音的 Snowflake epoch 后，在 `proto_msg_parser.py` 中硬编码正确公式。

```python
# proto_msg_parser.py 中修改时间戳提取

DOUYIN_SNOWFLAKE_EPOCH_MS = ?  # 待确定

def _decode_snowflake_timestamp(sid: int) -> float:
    """从 抖音 Snowflake ID 提取 Unix 秒时间戳"""
    if sid == 0:
        return time.time()
    ts_ms = (sid >> 22)          # 经典 Snowflake：移位 22
    unix_ms = DOUYIN_SNOWFLAKE_EPOCH_MS + ts_ms
    return unix_ms / 1000.0
```

### 方案 B：试探性解码（兜底）

如果找不到确切的 epoch，可以用消息间的相对时间 + 最新消息的已知时间反推：

```python
def _decode_fallback(ids: list[int], latest_known_ts: float) -> list[float]:
    """已知最新一条的时间，用 ID 差值反推前面的时间"""
    latest_id = ids[-1]
    results = []
    for sid in ids:
        delta_us = (latest_id - sid) / 1e6      # 微秒差值
        results.append(latest_known_ts - delta_us)
    return results
```

### 方案 C：使用 index 字段作为时间戳

从诊断数据来看，`index`（field 0x20）的值 `1672502400xxxxxx` 可能本身就是微秒级 Unix 时间戳：

```python
if index and index > 1_600_000_000_000_000:  # > 2020年的微秒时间戳
    ts = index / 1_000_000
```

---

## 6. 验证修复

修完后用 SQLite 直接查 DB 确认：

```bash
sqlite3 dmshoot/data/dmshoot.db "
  SELECT sender_name, content, datetime(timestamp, 'unixepoch', 'localtime') as msg_time
  FROM messages WHERE platform='douyin'
  ORDER BY timestamp DESC LIMIT 20;
"
```

对比 App 里的实际聊天时间，如果误差在 ±1 分钟内就算准确。

---

## 7. 附录：已知的抖音 protobuf MessageBody 字段

从实际数据反推的字段映射（可能与 SDK 定义有出入）：

| 字段号 | Wire Tag | 类型 | 推测含义 | 样本值 |
|--------|----------|------|---------|--------|
| 1 | `0x0a` | string | conversation_id | `"0:1:xxx:xxx"` |
| 3 | `0x18` | varint | server_message_id | `7645676067076097573` |
| 4 | `0x20` | varint | create_time (μs?) | `1672502400020000` |
| 5 | `0x28` | varint | conversation_short_id | `48` 或 `7638138921724936746` |
| 7 | `0x38` | varint | sender_uid | `1028742494552135` |
| 8 | `0x42` | bytes | content (JSON) | `{"text":"你好"}` |

**注意**：field 4（`0x20`）在当前代码中被标记为 `index`，但从数值特征看（微秒级递增，恒定基数），它更可能是 `create_time` 或 `server_time`。需要对比 WS 消息的同字段值来确认。
