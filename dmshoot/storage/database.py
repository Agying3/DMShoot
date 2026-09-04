"""SQLite数据库操作层 — 持久连接 + platform列 + 批量写入

优化要点（参考 docs/DATABASE.md）:
  1. 持久连接: 模块级单例 _conn，避免每条消息 open/close
  2. messages 加 platform 列: 按平台删除/查询时走索引，不用 LIKE 全表扫
  3. 批量写入: save_messages_batch() 一次 commit 多条
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from dmshoot.storage.models import SessionRecord, ChatMessage, AppConfig
from dmshoot.utils.console_log import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "dmshoot.db"
AI_ECHO_WINDOW = 15 * 60  # AI 本地回复与平台自发回显的最大匹配间隔

# ── 持久连接（模块级单例，所有线程共享）──
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()  # 写操作互斥


def get_db_path() -> Path:
    return DB_PATH


def _get_conn() -> sqlite3.Connection:
    """获取持久连接（不再每次 open/close）"""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA wal_autocheckpoint=200")   # 200页≈800KB 即自动合并
        _conn.execute("PRAGMA synchronous=NORMAL")       # 平衡性能和安全
    return _conn


# 公开别名
def get_conn() -> sqlite3.Connection:
    return _get_conn()


# ── L2: 退出时强制 WAL checkpoint ──
import atexit
import signal


def _checkpoint_on_exit():
    """退出时将 WAL 写回主文件，防止数据积压"""
    if _conn is not None:
        try:
            _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint 完成（退出时）")
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败: {e}")


def _checkpoint_signal_handler(signum, frame):
    _checkpoint_on_exit()


atexit.register(_checkpoint_on_exit)
# 注意：signal 在多线程 GUI 应用中可能不生效，atexit 是主要防线
try:
    signal.signal(signal.SIGTERM, _checkpoint_signal_handler)
    signal.signal(signal.SIGINT, _checkpoint_signal_handler)
except ValueError:
    pass  # 主线程不可用时跳过


# ── 初始化 ──

def init_database():
    """初始化数据库，创建表 + 迁移"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            platform TEXT NOT NULL,
            peer_name TEXT DEFAULT '',
            peer_id TEXT DEFAULT '',
            last_message TEXT DEFAULT '',
            last_time REAL DEFAULT 0,
            unread_count INTEGER DEFAULT 0,
            is_pinned INTEGER DEFAULT 0,
            is_muted INTEGER DEFAULT 0,
            avatar_url TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            platform TEXT DEFAULT '',
            sender_name TEXT DEFAULT '',
            sender_id TEXT DEFAULT '',
            content TEXT DEFAULT '',
            msg_type TEXT DEFAULT 'text',
            is_self INTEGER DEFAULT 0,
            is_auto INTEGER DEFAULT 0,
            persona TEXT DEFAULT '',
            message_key TEXT DEFAULT '',
            timestamp REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)

    # 迁移: 给旧 messages 表加 platform 列
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN platform TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 迁移: 给旧 messages 表加 persona 列（AI 回复角色名）
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN persona TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 列已存在

    try:
        cur.execute("ALTER TABLE messages ADD COLUMN message_key TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 迁移: 回填已有数据的 platform（仅有空 platform 时才执行）
    empty = cur.execute(
        "SELECT 1 FROM messages WHERE platform = '' LIMIT 1"
    ).fetchone()
    if empty:
        cur.execute("""
            UPDATE messages SET platform = SUBSTR(session_id, 1, INSTR(session_id, ':') - 1)
            WHERE platform = '' AND session_id LIKE '%:%'
        """)

    # 迁移: 给 sessions 表加 active_messaging 列（AI主动消息开关）
    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN active_messaging INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 索引
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages(session_id, timestamp DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_platform
        ON messages(platform, timestamp DESC)
    """)
    # 服务端消息 ID 优先；无 ID 的历史数据用精确时间戳兜底。
    cur.execute("DROP INDEX IF EXISTS idx_messages_dedup")
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_message_key
        ON messages(message_key) WHERE message_key != ''
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_fallback_dedup
        ON messages(session_id, sender_id, content, is_self, timestamp)
        WHERE message_key = ''
    """)

    conn.commit()
    conn.close()
    # 初始化后建持久连接
    _get_conn()
    logger.info(f"数据库初始化完成: {DB_PATH}")


def _platform_from(session_id: str) -> str:
    """从 session_id 提取平台名: 'douyin:0:1:xxx' → 'douyin'"""
    return session_id.split(":")[0] if ":" in session_id else ""


def _is_ai_echo_candidate(message: ChatMessage) -> bool:
    """只把 AI 本地消息和平台自发回显视为可合并的一对。"""
    return bool(
        message.content
        and ((message.is_auto and not message.is_self)
             or (message.is_self and not message.is_auto))
    )


def _has_ai_echo(conn: sqlite3.Connection, message: ChatMessage) -> bool:
    """查询同一会话中是否已经存在另一方向的 AI 回显。"""
    if not _is_ai_echo_candidate(message):
        return False
    timestamp = float(message.timestamp or 0)
    row = conn.execute("""
        SELECT 1 FROM messages
        WHERE session_id = ?
          AND content = ?
          AND is_auto = ?
          AND is_self = ?
          AND timestamp BETWEEN ? AND ?
        LIMIT 1
    """, (
        message.session_id,
        message.content,
        int(message.is_self),
        int(message.is_auto),
        timestamp - AI_ECHO_WINDOW,
        timestamp + AI_ECHO_WINDOW,
    )).fetchone()
    return row is not None


def _messages_are_duplicates(left: ChatMessage, right: ChatMessage) -> bool:
    if left.session_id != right.session_id:
        return False
    if left.message_key and right.message_key:
        return left.message_key == right.message_key
    if (
        not left.message_key
        and not right.message_key
        and left.sender_id == right.sender_id
        and left.content == right.content
        and left.is_self == right.is_self
        and left.is_auto == right.is_auto
        and abs((left.timestamp or 0) - (right.timestamp or 0)) < 0.001
    ):
        return True
    if not (_is_ai_echo_candidate(left) and _is_ai_echo_candidate(right)):
        return False
    return (
        left.content == right.content
        and left.is_auto != right.is_auto
        and left.is_self != right.is_self
        and abs((left.timestamp or 0) - (right.timestamp or 0)) <= AI_ECHO_WINDOW
    )


def deduplicate_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """清理历史中已存在的重复服务端键和 AI 平台回显。"""
    result: list[ChatMessage] = []
    for message in messages:
        duplicate_index = next(
            (
                index for index in range(len(result) - 1, -1, -1)
                if _messages_are_duplicates(result[index], message)
            ),
            None,
        )
        if duplicate_index is None:
            result.append(message)
            continue
        # AI 本地消息包含 persona，优先保留它的显示身份和头像方向。
        existing = result[duplicate_index]
        if message.is_auto and not existing.is_auto:
            result[duplicate_index] = message
    return result


# ── 会话操作 ──

def upsert_session(session: SessionRecord) -> bool:
    """插入或更新会话，返回 True=有变更"""
    conn = _get_conn()
    with _lock:
        cur = conn.execute("""
            INSERT INTO sessions (session_id, platform, peer_name, peer_id,
                last_message, last_time, unread_count, is_pinned, is_muted, active_messaging, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                peer_name=excluded.peer_name,
                peer_id=excluded.peer_id,
                last_message=excluded.last_message,
                last_time=excluded.last_time,
                is_pinned=excluded.is_pinned,
                is_muted=excluded.is_muted,
                avatar_url=CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE avatar_url END
        """, (
            session.session_id, session.platform, session.peer_name, session.peer_id,
            session.last_message, session.last_time, session.unread_count,
            int(session.is_pinned), int(session.is_muted), int(session.active_messaging), session.avatar_url
        ))
        changed = cur.rowcount > 0
        conn.commit()
    return changed


def increment_unread(session_id: str) -> int:
    """原子递增会话的未读计数，返回新值"""
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE sessions SET unread_count = unread_count + 1 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT unread_count FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["unread_count"] if row else 0


def reset_unread(session_id: str):
    """会话已读，清空未读计数"""
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE sessions SET unread_count = 0 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()


def upsert_sessions_batch(sessions: list[SessionRecord]) -> int:
    """批量插入或更新会话，返回实际写入行数"""
    if not sessions:
        return 0
    conn = _get_conn()
    with _lock:
        data = [
            (s.session_id, s.platform, s.peer_name, s.peer_id,
             s.last_message, s.last_time, s.unread_count,
             int(s.is_pinned), int(s.is_muted), int(s.active_messaging), s.avatar_url)
            for s in sessions
        ]
        cur = conn.executemany("""
            INSERT INTO sessions (session_id, platform, peer_name, peer_id,
                last_message, last_time, unread_count, is_pinned, is_muted, active_messaging, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                peer_name=excluded.peer_name,
                peer_id=excluded.peer_id,
                last_message=excluded.last_message,
                last_time=excluded.last_time,
                is_pinned=excluded.is_pinned,
                is_muted=excluded.is_muted,
                avatar_url=CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE avatar_url END
        """, data)
        conn.commit()
    return cur.rowcount


def get_sessions(platform: str = "") -> list[SessionRecord]:
    """获取会话列表（按 last_time 倒序）"""
    conn = _get_conn()
    if platform:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE platform=? ORDER BY last_time DESC",
            (platform,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY last_time DESC"
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def delete_sessions(platform: str):
    """删除指定平台的所有会话和消息（走 platform 索引，不用 LIKE）"""
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM messages WHERE platform=?", (platform,))
        conn.execute("DELETE FROM sessions WHERE platform=?", (platform,))
        conn.commit()


def delete_messages(platform: str) -> int:
    """只删除指定平台消息，保留会话并与其他写操作串行。"""
    conn = _get_conn()
    with _lock:
        cur = conn.execute("DELETE FROM messages WHERE platform=?", (platform,))
        conn.commit()
    return cur.rowcount


def update_session_name_avatar(session_id: str, peer_name: str, avatar_url: str):
    """仅更新会话的昵称和头像（不覆写 last_message/last_time）"""
    conn = _get_conn()
    with _lock:
        conn.execute("""
            INSERT INTO sessions (session_id, platform, peer_name, peer_id,
                last_message, last_time, unread_count, is_pinned, is_muted, active_messaging, avatar_url)
            VALUES (?, '', ?, '', '', 0, 0, 0, 0, 0, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                peer_name=excluded.peer_name,
                avatar_url=excluded.avatar_url
        """, (session_id, peer_name, avatar_url))
        conn.commit()


def update_session_name_if_placeholder(session_id: str, peer_name: str) -> bool:
    """仅将占位昵称替换为平台返回的真实昵称。"""
    conn = _get_conn()
    with _lock:
        cur = conn.execute("""
            UPDATE sessions SET peer_name=?
            WHERE session_id=? AND (
                peer_name LIKE '用户%' OR peer_name LIKE '粉丝%' OR peer_name LIKE 'fans_%'
            )
        """, (peer_name, session_id))
        conn.commit()
    return cur.rowcount > 0


def set_active_messaging(session_id: str, enabled: bool):
    """设置会话的 AI 主动消息开关"""
    conn = _get_conn()
    with _lock:
        conn.execute(
            "UPDATE sessions SET active_messaging = ? WHERE session_id = ?",
            (int(enabled), session_id),
        )
        conn.commit()


def is_active_messaging(session_id: str) -> bool:
    """查询会话是否启用了 AI 主动消息"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT active_messaging FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    return bool(row["active_messaging"]) if row else False


def _row_to_session(row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        session_id=row["session_id"],
        platform=row["platform"],
        peer_name=row["peer_name"],
        peer_id=row["peer_id"],
        last_message=row["last_message"],
        last_time=row["last_time"],
        unread_count=row["unread_count"],
        is_pinned=bool(row["is_pinned"]),
        is_muted=bool(row["is_muted"]),
        active_messaging=bool(row["active_messaging"]),
        avatar_url=row["avatar_url"],
    )


# ── 消息操作 ──

def save_message(msg: ChatMessage) -> bool:
    """保存一条消息（自动去重），返回 True=实际写入"""
    import time as _time
    _start = _time.perf_counter()
    conn = _get_conn()
    with _lock:
        # AI 回复先在本地展示并落库，平台稍后可能再回显一份 is_self 消息。
        # 两者没有相同的服务端 ID，只能用会话、正文、方向和短时间窗口合并。
        if _has_ai_echo(conn, msg):
            return False
        cur = conn.execute("""
            INSERT OR IGNORE INTO messages (session_id, platform, sender_name, sender_id,
                content, msg_type, is_self, is_auto, persona, timestamp, message_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg.session_id, _platform_from(msg.session_id),
            msg.sender_name, msg.sender_id, msg.content,
            msg.msg_type, int(msg.is_self), int(msg.is_auto), msg.persona, msg.timestamp,
            msg.message_key,
        ))
        inserted = cur.rowcount > 0
        conn.commit()
    _elapsed = (_time.perf_counter() - _start) * 1000
    try:
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().record_db_write(_elapsed)
    except Exception:
        pass
    return inserted


def save_incoming_message(session: SessionRecord, msg: ChatMessage) -> tuple[bool, int]:
    """用一次事务保存入站消息、更新会话并递增未读。"""
    import time as _time
    _start = _time.perf_counter()
    conn = _get_conn()
    inserted = False
    unread_count = -1
    with _lock:
        try:
            cur = conn.execute("""
                INSERT OR IGNORE INTO messages (session_id, platform, sender_name, sender_id,
                    content, msg_type, is_self, is_auto, persona, timestamp, message_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.session_id, _platform_from(msg.session_id),
                msg.sender_name, msg.sender_id, msg.content,
                msg.msg_type, int(msg.is_self), int(msg.is_auto), msg.persona, msg.timestamp,
                msg.message_key,
            ))
            inserted = cur.rowcount > 0
            if inserted:
                conn.execute("""
                    INSERT INTO sessions (session_id, platform, peer_name, peer_id,
                        last_message, last_time, unread_count, is_pinned, is_muted,
                        active_messaging, avatar_url)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        peer_name=CASE
                            WHEN (
                                excluded.peer_name LIKE '用户%'
                                OR excluded.peer_name LIKE '粉丝%'
                                OR excluded.peer_name LIKE 'fans_%'
                            )
                              AND sessions.peer_name != ''
                              AND sessions.peer_name NOT LIKE '用户%'
                              AND sessions.peer_name NOT LIKE '粉丝%'
                              AND sessions.peer_name NOT LIKE 'fans_%'
                            THEN sessions.peer_name
                            ELSE excluded.peer_name
                        END,
                        peer_id=excluded.peer_id,
                        last_message=excluded.last_message,
                        last_time=excluded.last_time,
                        unread_count=sessions.unread_count + 1,
                        avatar_url=CASE WHEN excluded.avatar_url != ''
                            THEN excluded.avatar_url ELSE sessions.avatar_url END
                """, (
                    session.session_id, session.platform, session.peer_name, session.peer_id,
                    session.last_message, session.last_time,
                    int(session.is_pinned), int(session.is_muted),
                    int(session.active_messaging), session.avatar_url,
                ))
                row = conn.execute(
                    "SELECT unread_count FROM sessions WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()
                unread_count = row["unread_count"] if row else 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    _elapsed = (_time.perf_counter() - _start) * 1000
    try:
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().record_db_write(_elapsed)
    except Exception:
        pass
    return inserted, unread_count


def save_platform_message(msg) -> tuple[bool, int]:
    """统一保存适配器消息，桌面与无界面运行方式共用。"""
    content = getattr(msg, "content", "")
    if not content or not content.strip():
        return False, -1

    chat_message = ChatMessage(
        session_id=msg.session_id,
        sender_name=msg.sender_name,
        sender_id=msg.sender_id,
        content=content,
        msg_type=msg.msg_type,
        is_self=msg.is_self,
        is_auto=getattr(msg, "is_auto_reply", False),
        timestamp=msg.timestamp,
        message_key=getattr(msg, "message_key", ""),
    )
    if msg.is_self:
        return save_message(chat_message), -1

    session = SessionRecord(
        session_id=msg.session_id,
        platform=msg.platform,
        peer_name=msg.sender_name,
        peer_id=msg.sender_id,
        last_message=content[:50],
        last_time=msg.timestamp,
    )
    return save_incoming_message(session, chat_message)


def save_messages_batch(msgs: list[ChatMessage]) -> int:
    """批量保存消息，跳过重复。返回实际写入条数"""
    if not msgs:
        return 0
    import time as _time
    _start = _time.perf_counter()
    conn = _get_conn()
    with _lock:
        normal_msgs = [m for m in msgs if not _is_ai_echo_candidate(m)]
        # 同一批次内也优先写入 AI 本地记录，再过滤随后出现的平台回显。
        echo_msgs = sorted(
            (m for m in msgs if _is_ai_echo_candidate(m)),
            key=lambda m: not m.is_auto,
        )
        data = [
            (m.session_id, _platform_from(m.session_id),
             m.sender_name, m.sender_id, m.content,
             m.msg_type, int(m.is_self), int(m.is_auto), m.persona, m.timestamp, m.message_key)
            for m in normal_msgs
        ]
        cur = conn.executemany("""
            INSERT OR IGNORE INTO messages (session_id, platform, sender_name, sender_id,
                content, msg_type, is_self, is_auto, persona, timestamp, message_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data) if data else None
        written = cur.rowcount if cur is not None else 0
        # 仅对可能是 AI 回显的极少数消息做匹配查询，保留普通历史同步的批量写入性能。
        for m in echo_msgs:
            if _has_ai_echo(conn, m):
                continue
            cur = conn.execute("""
                INSERT OR IGNORE INTO messages (session_id, platform, sender_name, sender_id,
                    content, msg_type, is_self, is_auto, persona, timestamp, message_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m.session_id, _platform_from(m.session_id), m.sender_name, m.sender_id,
                m.content, m.msg_type, int(m.is_self), int(m.is_auto), m.persona,
                m.timestamp, m.message_key,
            ))
            written += cur.rowcount
        conn.commit()
    _elapsed = (_time.perf_counter() - _start) * 1000
    try:
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().record_db_write(_elapsed)
    except Exception:
        pass
    return written


def get_messages(session_id: str, limit: int = 50) -> list[ChatMessage]:
    """获取指定会话的消息（oldest first，用于上旧下新渲染）"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM messages WHERE session_id=?
        ORDER BY timestamp DESC, id DESC LIMIT ?
    """, (session_id, limit)).fetchall()
    return deduplicate_messages([_row_to_message(r) for r in reversed(rows)])


def get_messages_before(
    session_id: str,
    before_timestamp: float,
    before_id: int = 0,
    limit: int = 100,
) -> list[ChatMessage]:
    """获取指定消息之前的一页历史，返回 oldest first。"""
    conn = _get_conn()
    if before_id:
        rows = conn.execute("""
            SELECT * FROM messages
            WHERE session_id=? AND (timestamp < ? OR (timestamp = ? AND id < ?))
            ORDER BY timestamp DESC, id DESC LIMIT ?
        """, (session_id, before_timestamp, before_timestamp, before_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM messages
            WHERE session_id=? AND timestamp < ?
            ORDER BY timestamp DESC, id DESC LIMIT ?
        """, (session_id, before_timestamp, limit)).fetchall()
    return deduplicate_messages([_row_to_message(r) for r in reversed(rows)])


def get_messages_by_platform(platform: str, limit: int = 100) -> list[ChatMessage]:
    """按平台获取最新消息（走 platform 索引）"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM messages WHERE platform=?
        ORDER BY timestamp DESC LIMIT ?
    """, (platform, limit)).fetchall()
    return [_row_to_message(r) for r in rows]


def _row_to_message(row) -> ChatMessage:
    return ChatMessage(
        id=row["id"],
        session_id=row["session_id"],
        sender_name=row["sender_name"],
        sender_id=row["sender_id"],
        content=row["content"],
        msg_type=row["msg_type"],
        is_self=bool(row["is_self"]),
        is_auto=bool(row["is_auto"]),
        persona=row["persona"] if "persona" in row.keys() else "",
        timestamp=row["timestamp"],
        message_key=row["message_key"] if "message_key" in row.keys() else "",
    )


# ── 配置操作 ──

def load_config() -> AppConfig:
    """从数据库加载配置"""
    import json as _json
    config = AppConfig()
    conn = _get_conn()
    rows = conn.execute("SELECT key, value FROM config").fetchall()

    config_dict = {r["key"]: r["value"] for r in rows}
    for field_name in AppConfig.__dataclass_fields__:
        if field_name in config_dict:
            value = config_dict[field_name]
            field_type = type(getattr(config, field_name))
            if field_type == bool:
                value = value.lower() in ("true", "1", "yes")
            elif field_type == float:
                value = float(value)
            elif field_type == int:
                value = int(value)
            elif field_type == list:
                value = _json.loads(value) if value else []
            setattr(config, field_name, value)

    return config


def save_config(config: AppConfig):
    """保存全部配置到数据库"""
    update_config_fields({
        field_name: getattr(config, field_name)
        for field_name in AppConfig.__dataclass_fields__
    })


def update_config_fields(values: dict):
    """在一个事务中只更新指定配置字段，避免覆盖并发认证更新。"""
    import json as _json
    unknown = set(values) - set(AppConfig.__dataclass_fields__)
    if unknown:
        raise KeyError(f"未知配置字段: {', '.join(sorted(unknown))}")

    rows = []
    for key, value in values.items():
        if isinstance(value, list):
            value = _json.dumps(value)
        else:
            value = str(value)
        rows.append((key, value))

    conn = _get_conn()
    with _lock:
        conn.executemany("""
                INSERT INTO config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, rows)
        conn.commit()


def update_config_field(key: str, value: str):
    """原子更新单个配置字段（避免并发覆写）"""
    update_config_fields({key: value})
