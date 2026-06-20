# DMShoot 数据库优化方案

> **目标场景**：每平台 10,000+ 粉丝，日均 3,000~5,000 条消息，AI 回复同等数量。
> **核心结论**：SQLite WAL 模式完全够用，瓶颈不在 SQLite 本身，在于连接管理和应用层索引缺失。

---

## 1. 现状问题

### 1.1 每次写入都 open/close

```python
# database.py — 当前写法
def save_message(msg):
    conn = _get_conn()    # sqlite3.connect()
    conn.execute(...)
    conn.commit()
    conn.close()          # ← 每条消息一次
```

**代价**：高峰期一秒 10 条消息 = 10 次文件打开/关闭。WAL 写锁虽快，open/close 开销比写入本身还大。

### 1.2 messages 表缺 platform 列

```sql
-- 删除抖音数据只能这样
DELETE FROM messages WHERE session_id LIKE 'douyin:%'  -- 全表扫描
```

`LIKE 'douyin:%'` 不走索引。数据 10 万条开始变慢，50 万条明显卡顿。

### 1.3 去重索引开销大

```sql
CREATE UNIQUE INDEX idx_messages_dedup 
ON messages(session_id, content, is_self, CAST(timestamp AS INTEGER))
```

四字段 + 函数表达式，每条 INSERT 都要维护这个 B-tree。100 万条消息时索引文件可能比数据还大。

### 1.4 B站同步多线程抢写锁

`bilibili/adapter.py` 的 `_sync_history` 用 `ThreadPoolExecutor(max_workers=5)` 并发调用 `database.save_message()`，5 个线程各自 open/close + 抢 WAL 写锁。

### 1.5 抖音时间戳是编的

`douyin_msg_sync.py` 用 `base_ts + msg_idx * 60` 生成假时间戳，跟真实发送时间毫无关系。

---

## 2. 短期改造（立即执行，零风险）

### 2.1 messages 加 platform 列

```sql
-- 新建表时
CREATE TABLE messages (
    ...
    platform TEXT DEFAULT '',   -- ← 新增
    ...
);

-- 对已有数据库做迁移
ALTER TABLE messages ADD COLUMN platform TEXT DEFAULT '';

-- 新索引
CREATE INDEX IF NOT EXISTS idx_messages_platform 
ON messages(platform, timestamp DESC);
```

`save_message()` 自动从 `session_id.split(":")[0]` 提取 platform 一起写入。

### 2.2 持久连接

```python
_conn: sqlite3.Connection = None

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn
```

模块级单例连接，所有操作共用。去掉每个写函数末尾的 `conn.close()`。

⚠️ **注意**：QThread 间共享一个连接是安全的（SQLite 自身做序列化），但如果有大量读取阻塞，考虑读操作用只读连接。

### 2.3 批量写入函数

```python
def save_messages_batch(msgs: list[ChatMessage]):
    """批量保存消息，跳过重复"""
    if not msgs:
        return
    conn = _get_conn()
    data = [(m.session_id, m.session_id.split(":")[0], 
             m.sender_name, m.sender_id, m.content,
             m.msg_type, int(m.is_self), int(m.is_auto), m.timestamp)
            for m in msgs]
    conn.executemany("""
        INSERT OR IGNORE INTO messages
        (session_id, platform, sender_name, sender_id, content,
         msg_type, is_self, is_auto, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, data)
    conn.commit()
```

### 2.4 B站同步改用批量写

`bilibili/adapter.py` 的 `_sync_history`：

- `fetch_one()` 不再直接调 `database.save_message()`，改为返回 `parsed_msgs` 列表
- 主线程收集完所有结果后统一调 `save_messages_batch()`

### 2.5 抖音同步同样改批量

`douyin_msg_sync.py` 的 `sync_messages_to_db()` 同样改成收集列表 + 最后 `save_messages_batch()`。

---

## 3. 中期改造（数据到 10 万条时）

### 3.1 应用层内存索引

在 `main_window.py` 或新建 `dmshoot/core/index.py`：

```python
class SessionIndex:
    """内存中的会话索引，避免每次操作都查 DB"""
    
    def __init__(self):
        self.by_id: dict[str, SessionRecord] = {}           # session_id → 记录
        self.by_platform: dict[str, list[str]] = {}         # platform → [session_id]
        self.msg_cache: dict[str, list[ChatMessage]] = {}   # session_id → 最近消息

    def upsert(self, session: SessionRecord):
        sid = session.session_id
        self.by_id[sid] = session
        plat = session.platform
        if sid not in self.by_platform.setdefault(plat, []):
            self.by_platform[plat].append(sid)

    def get_by_platform(self, platform: str) -> list[SessionRecord]:
        return [self.by_id[sid] for sid in self.by_platform.get(platform, [])]
```

**收益**：通讯录刷新、会话查找、AI 上下文全部走内存，DB 只做持久化。

### 3.2 消息去重移到应用层

去掉 `idx_messages_dedup` 四字段唯一索引，改用内存 Bloom Filter：

```python
# 2,000 条容量，误判率 0.1%
_dedup = set()  # 或 pybloom_live.ScalableBloomFilter

def is_duplicate(session_id: str, content: str, timestamp: float) -> bool:
    key = f"{session_id}|{content}|{int(timestamp)}"
    if key in _dedup:
        return True
    _dedup.add(key)
    if len(_dedup) > 10000:  # 定期清理
        _dedup.clear()
    return False
```

**收益**：写入性能提升 5~10 倍，索引文件不会膨胀。

### 3.3 定期清理旧消息

```sql
-- 保留最近 30 天
DELETE FROM messages WHERE timestamp < unixepoch('now', '-30 days');
VACUUM;
```

或按月归档到 `messages_archive` 表：

```sql
CREATE TABLE messages_archive AS SELECT * FROM messages WHERE 1=0;
-- 每月 1 号自动执行
INSERT INTO messages_archive SELECT * FROM messages 
WHERE timestamp < unixepoch('now', '-30 days');
DELETE FROM messages WHERE timestamp < unixepoch('now', '-30 days');
```

---

## 4. 索引总览

| 索引 | 类型 | 用途 | 优先级 |
|------|------|------|--------|
| `idx_messages_platform` | DB | 按平台过滤消息 | 🔴 短期 |
| `idx_messages_session` | DB | 按会话查消息（已有） | ✅ 已有 |
| `idx_sessions_last_time` | DB | 通讯录排序 | 🟡 中期 |
| `idx_messages_dedup` | DB | 去重（建议删掉，改用内存） | ❌ 删 |
| `SessionIndex.by_id` | 内存 dict | 会话秒查 | 🟡 中期 |
| `SessionIndex.msg_cache` | 内存 dict | AI 上下文 | 🟡 中期 |
| `_dedup` set/bloom | 内存 set | 消息去重 | 🟡 中期 |
| FTS5 全文搜索 | DB 虚拟表 | 关键词搜索 | 🟢 按需 |

---

## 5. 不改的方案

**以下情况不需要换库**：

- ❌ 不需要 PostgreSQL / MySQL — 单机桌面应用 + SQLite WAL 足够
- ❌ 不需要 Redis — 内存 dict 做缓存更简单
- ❌ 不需要 DuckDB — 除非需要复杂分析查询（日报/周报统计）

SQLite WAL 模式在 500 万条消息以内都是最优解。

---

## 6. 相关文件

| 文件 | 涉及内容 |
|------|---------|
| `dmshoot/storage/database.py` | 表结构、连接管理、CRUD |
| `dmshoot/storage/models.py` | ChatMessage、SessionRecord 定义 |
| `dmshoot/plugins/bilibili/adapter.py` | B站历史同步（多线程写） |
| `dmshoot/utils/douyin_msg_sync.py` | 抖音消息同步（假时间戳） |
| `dmshoot/gui/main_window.py` | AI 上下文、通讯录刷新触发 |
| `dmshoot/gui/widgets/contact.py` | 通讯录增量更新 |

---

*最后更新：2026-05-30*
