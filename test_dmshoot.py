"""DMShoot 完整测试套件

运行: python test_dmshoot.py
覆盖: core / storage / ai / config / plugins / utils
"""

import sys
import os
import tempfile
import asyncio
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _temp_db(name_suffix="test"):
    """Generate unique temp DB path to avoid lock collisions between tests"""
    return os.path.join(tempfile.gettempdir(), f"dmshoot_test_{name_suffix}_{uuid.uuid4().hex[:8]}.db")


# ═══════════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════════

_results: list[tuple[str, bool, str]] = []


def ok(name: str, detail: str = ""):
    _results.append((name, True, detail))
    print(f"  [OK] {name}{' — ' + detail if detail else ''}")


def fail(name: str, reason: str):
    _results.append((name, False, reason))
    print(f"  [FAIL] {name}: {reason}")


def check(name: str, condition, detail: str = ""):
    if condition:
        ok(name, detail)
    else:
        fail(name, f"断言失败{f' ({detail})' if detail else ''}")


# ═══════════════════════════════════════════════════════════
# 1. core/message.py — 统一消息模型
# ═══════════════════════════════════════════════════════════

def test_message_basic():
    from dmshoot.core.message import Message

    m = Message(platform="bilibili", msg_type="text", sender_id="1",
                sender_name="A", session_id="b:1", content="你好")
    check("Message 基本创建", m.platform == "bilibili" and m.content == "你好")
    check("Message 自动时间戳", m.timestamp > 0)
    check("Message 默认 is_self=False", not m.is_self)
    check("Message 默认 is_auto_reply=False", not m.is_auto_reply)
    check("Message 默认 media_url 为空", m.media_url == "")
    check("Message raw 默认空字典", m.raw == {})


def test_message_self():
    from dmshoot.core.message import Message
    m = Message(platform="douyin", msg_type="text", sender_id="me",
                sender_name="我", session_id="d:1", content="回复", is_self=True)
    check("Message is_self=True", m.is_self)


def test_message_auto_reply():
    from dmshoot.core.message import Message
    m = Message(platform="bilibili", msg_type="text", sender_id="bot",
                sender_name="AI", session_id="b:2", content="自动回复",
                is_auto_reply=True)
    check("Message is_auto_reply=True", m.is_auto_reply)


def test_message_media():
    from dmshoot.core.message import Message
    m = Message(platform="douyin", msg_type="image", sender_id="1",
                sender_name="B", session_id="d:3", content="图片",
                media_url="https://img.example.com/1.jpg")
    check("Message 带 media_url", m.media_url == "https://img.example.com/1.jpg")


def test_message_explicit_timestamp():
    from dmshoot.core.message import Message
    ts = 1000000.0
    m = Message(platform="bilibili", msg_type="text", sender_id="1",
                sender_name="A", session_id="b:1", content="旧消息", timestamp=ts)
    check("Message 显式时间戳", m.timestamp == ts)


def test_message_from_douyin_text():
    from dmshoot.core.message import Message
    raw = {"msg_type": 1, "from_user_id": "123", "from_nickname": "抖音用户",
           "conversation_id": "conv_abc", "text": "你好啊", "msg_id": 999}
    m = Message.from_douyin(raw)
    check("from_douyin platform", m.platform == "douyin")
    check("from_douyin msg_type=text", m.msg_type == "text")
    check("from_douyin sender_id", m.sender_id == "123")
    check("from_douyin sender_name", m.sender_name == "抖音用户")
    check("from_douyin session_id", m.session_id == "douyin:conv_abc")
    check("from_douyin content", m.content == "你好啊")
    check("from_douyin seq_id", m.seq_id == 999)
    check("from_douyin raw 保留", m.raw == raw)


def test_message_from_douyin_image():
    from dmshoot.core.message import Message
    m = Message.from_douyin({"msg_type": 2, "from_user_id": "456",
                              "from_nickname": "图主", "conversation_id": "c2",
                              "text": "", "media_url": "http://img/d.jpg"})
    check("from_douyin msg_type=image", m.msg_type == "image")
    check("from_douyin media_url 传递", m.media_url == "http://img/d.jpg")


def test_message_from_douyin_voice():
    from dmshoot.core.message import Message
    m = Message.from_douyin({"msg_type": 3, "from_user_id": "789",
                              "from_nickname": "语音", "conversation_id": "c3"})
    check("from_douyin msg_type=voice", m.msg_type == "voice")


def test_message_from_douyin_video():
    from dmshoot.core.message import Message
    m = Message.from_douyin({"msg_type": 4, "from_user_id": "000",
                              "from_nickname": "视频", "conversation_id": "c4"})
    check("from_douyin msg_type=video", m.msg_type == "video")


def test_message_from_douyin_unknown_type():
    from dmshoot.core.message import Message
    m = Message.from_douyin({"msg_type": 99, "from_user_id": "x",
                              "from_nickname": "未知", "conversation_id": "cx"})
    check("from_douyin 未知类型默认 text", m.msg_type == "text")


def test_message_from_douyin_missing_fields():
    from dmshoot.core.message import Message
    m = Message.from_douyin({})
    check("from_douyin 空字典不崩溃", m.platform == "douyin")
    check("from_douyin 空字典 sender_id 为空串", m.sender_id == "")
    check("from_douyin 空字典 sender_name 为未知", m.sender_name == "未知")


def test_message_from_bilibili_text():
    from dmshoot.core.message import Message
    raw = {"msg_type": 1, "sender_uid": "111", "sender_name": "B站用户",
           "talker_id": "t_abc", "content": "在吗", "msg_seqno": 42}
    m = Message.from_bilibili(raw)
    check("from_bilibili platform", m.platform == "bilibili")
    check("from_bilibili msg_type=text", m.msg_type == "text")
    check("from_bilibili sender_id", m.sender_id == "111")
    check("from_bilibili sender_name", m.sender_name == "B站用户")
    check("from_bilibili session_id", m.session_id == "bilibili:t_abc")
    check("from_bilibili content", m.content == "在吗")
    check("from_bilibili seq_id", m.seq_id == 42)


def test_message_from_bilibili_image():
    from dmshoot.core.message import Message
    m = Message.from_bilibili({"msg_type": 2, "sender_uid": "222",
                                "sender_name": "图B", "talker_id": "t2",
                                "image_url": "http://bili/img.png"})
    check("from_bilibili msg_type=image (type 2)", m.msg_type == "image")
    check("from_bilibili media_url", m.media_url == "http://bili/img.png")


def test_message_from_bilibili_image_type6():
    from dmshoot.core.message import Message
    m = Message.from_bilibili({"msg_type": 6, "sender_uid": "333",
                                "sender_name": "图C", "talker_id": "t3"})
    check("from_bilibili msg_type=image (type 6)", m.msg_type == "image")


def test_message_from_bilibili_unknown_type():
    from dmshoot.core.message import Message
    m = Message.from_bilibili({"msg_type": 99, "sender_uid": "x",
                                "sender_name": "未知B", "talker_id": "tx"})
    check("from_bilibili 未知类型默认 text", m.msg_type == "text")


def test_message_from_bilibili_missing_fields():
    from dmshoot.core.message import Message
    m = Message.from_bilibili({})
    check("from_bilibili 空字典不崩溃", m.platform == "bilibili")
    check("from_bilibili 空字典 sender_name 为未知", m.sender_name == "未知")


def test_message_system_message():
    from dmshoot.core.message import Message
    m = Message.system_message("douyin", "连接成功")
    check("system_message platform", m.platform == "douyin")
    check("system_message type", m.msg_type == "system")
    check("system_message sender_id", m.sender_id == "SYSTEM")
    check("system_message sender_name", m.sender_name == "系统")
    check("system_message session_id", m.session_id == "douyin:SYSTEM")
    check("system_message content", m.content == "连接成功")


def test_message_unicode():
    from dmshoot.core.message import Message
    m = Message(platform="bilibili", msg_type="text", sender_id="1",
                sender_name="🎉用户", session_id="b:emoji", content="你好👋世界🌏")
    check("Message Unicode 昵称", m.sender_name == "🎉用户")
    check("Message Unicode 内容", m.content == "你好👋世界🌏")


# ═══════════════════════════════════════════════════════════
# 2. core/bus.py — 消息总线
# ═══════════════════════════════════════════════════════════

def test_bus_singleton():
    from dmshoot.core.bus import MessageBus
    b1 = MessageBus.instance()
    b2 = MessageBus.instance()
    check("MessageBus 单例", b1 is b2)


def test_bus_signals_exist():
    from dmshoot.core.bus import MessageBus
    bus = MessageBus()
    check("Bus 有 new_message 信号", hasattr(bus, "new_message"))
    check("Bus 有 send_reply 信号", hasattr(bus, "send_reply"))
    check("Bus 有 platform_status 信号", hasattr(bus, "platform_status"))
    check("Bus 有 log 信号", hasattr(bus, "log"))
    check("Bus 有 ai_request 信号", hasattr(bus, "ai_request"))
    check("Bus 有 ai_response 信号", hasattr(bus, "ai_response"))


def test_bus_emit_message():
    from dmshoot.core.bus import MessageBus
    from dmshoot.core.message import Message

    bus = MessageBus()
    received: list = []

    def on_msg(msg):
        received.append(msg)

    bus.new_message.connect(on_msg)
    m = Message(platform="douyin", msg_type="text", sender_id="1",
                sender_name="Tester", session_id="d:test", content="Hello")
    bus.emit_message(m)

    check("Bus emit_message 触发 signal", len(received) == 1)
    check("Bus emit_message 消息正确", received[0] is m)


def test_bus_request_reply():
    from dmshoot.core.bus import MessageBus
    bus = MessageBus()
    calls: list = []

    def on_reply(platform, sid, text):
        calls.append((platform, sid, text))

    bus.send_reply.connect(on_reply)
    bus.request_reply("bilibili", "b:123", "自动回复内容")

    check("Bus request_reply 触发 signal", len(calls) == 1)
    check("Bus request_reply 参数正确",
          calls[0] == ("bilibili", "b:123", "自动回复内容"))


def test_bus_platform_status():
    from dmshoot.core.bus import MessageBus, PlatformStatus
    bus = MessageBus()
    status_updates: list = []

    def on_status(platform, status, msg):
        status_updates.append((platform, status, msg))

    bus.platform_status.connect(on_status)
    bus.set_platform_status("bilibili", PlatformStatus.ONLINE, "连接成功")

    check("Bus set_platform_status 触发 signal", len(status_updates) == 1)
    check("Bus set_platform_status 状态正确",
          status_updates[0] == ("bilibili", "online", "连接成功"))


def test_bus_platform_status_constants():
    from dmshoot.core.bus import PlatformStatus
    check("PlatformStatus.OFFLINE", PlatformStatus.OFFLINE == "offline")
    check("PlatformStatus.CONNECTING", PlatformStatus.CONNECTING == "connecting")
    check("PlatformStatus.ONLINE", PlatformStatus.ONLINE == "online")
    check("PlatformStatus.ERROR", PlatformStatus.ERROR == "error")


def test_bus_ai_signals():
    from dmshoot.core.bus import MessageBus
    from dmshoot.core.message import Message
    bus = MessageBus()
    requests: list = []
    responses: list = []

    bus.ai_request.connect(lambda m: requests.append(m))
    bus.ai_response.connect(lambda sid, txt, mdl: responses.append((sid, txt, mdl)))

    m = Message(platform="bilibili", msg_type="text", sender_id="1",
                sender_name="U", session_id="b:x", content="问")
    bus.ai_request.emit(m)

    check("Bus ai_request signal", len(requests) == 1 and requests[0] is m)

    bus.ai_response.emit("b:x", "AI回答", "deepseek-v4-flash")
    check("Bus ai_response signal",
          responses[0] == ("b:x", "AI回答", "deepseek-v4-flash"))


# ═══════════════════════════════════════════════════════════
# 3. storage/models.py — 数据模型
# ═══════════════════════════════════════════════════════════

def test_session_record_basic():
    from dmshoot.storage.models import SessionRecord
    s = SessionRecord(session_id="bilibili:123", platform="bilibili",
                      peer_name="测试用户", peer_id="uid_1")
    check("SessionRecord session_id", s.session_id == "bilibili:123")
    check("SessionRecord platform", s.platform == "bilibili")
    check("SessionRecord peer_name", s.peer_name == "测试用户")
    check("SessionRecord peer_id", s.peer_id == "uid_1")
    check("SessionRecord 默认 id=0", s.id == 0)
    check("SessionRecord 默认 unread=0", s.unread_count == 0)
    check("SessionRecord 默认 not pinned", not s.is_pinned)
    check("SessionRecord 默认 not muted", not s.is_muted)


def test_session_record_defaults():
    from dmshoot.storage.models import SessionRecord
    s = SessionRecord()
    check("SessionRecord 空默认值", s.session_id == "" and s.platform == "")


def test_session_record_platform_display():
    from dmshoot.storage.models import SessionRecord
    check("platform_display douyin",
          SessionRecord(platform="douyin").platform_display == "🎵 抖音")
    check("platform_display bilibili",
          SessionRecord(platform="bilibili").platform_display == "📺 B站")
    check("platform_display xiaohongshu",
          SessionRecord(platform="xiaohongshu").platform_display == "📕 小红书")
    check("platform_display unknown",
          SessionRecord(platform="unknown").platform_display == "unknown")


def test_chat_message_basic():
    from dmshoot.storage.models import ChatMessage
    m = ChatMessage(session_id="s1", sender_name="用户A", content="你好",
                    is_self=False)
    check("ChatMessage session_id", m.session_id == "s1")
    check("ChatMessage sender_name", m.sender_name == "用户A")
    check("ChatMessage content", m.content == "你好")
    check("ChatMessage not is_self", not m.is_self)
    check("ChatMessage not is_auto", not m.is_auto)
    check("ChatMessage 默认 msg_type=text", m.msg_type == "text")
    check("ChatMessage 有时间戳", m.timestamp > 0)


def test_chat_message_self_and_auto():
    from dmshoot.storage.models import ChatMessage
    m = ChatMessage(session_id="s1", sender_name="AI", content="自动",
                    is_self=True, is_auto=True)
    check("ChatMessage is_self=True", m.is_self)
    check("ChatMessage is_auto=True", m.is_auto)


def test_chat_message_explicit_timestamp():
    from dmshoot.storage.models import ChatMessage
    ts = 1234567890.0
    m = ChatMessage(session_id="s1", sender_name="A", content="x", timestamp=ts)
    check("ChatMessage 显式时间戳", m.timestamp == ts)


def test_app_config_defaults():
    from dmshoot.storage.models import AppConfig
    c = AppConfig()
    check("AppConfig 默认 model", c.model == "deepseek-v4-flash")
    check("AppConfig 默认 base_url", c.base_url == "https://api.deepseek.com")
    check("AppConfig 默认 prompt_preset", c.prompt_preset == "柁炑")
    check("AppConfig 默认 behavior_preset", c.behavior_preset == "默认")
    check("AppConfig 默认 api_key 为空", c.api_key == "")
    check("AppConfig 默认 douyin_enabled=False", not c.douyin_enabled)
    check("AppConfig 默认 bilibili_enabled=False", not c.bilibili_enabled)
    check("AppConfig 默认 auto_reply_enabled=True", c.auto_reply_enabled)
    check("AppConfig 默认 reply_delay_min=1.0", c.reply_delay_min == 1.0)
    check("AppConfig 默认 reply_delay_max=3.0", c.reply_delay_max == 3.0)
    check("AppConfig 默认 max_context_rounds=10", c.max_context_rounds == 10)


def test_app_config_custom():
    from dmshoot.storage.models import AppConfig
    c = AppConfig(api_key="sk-test", model="deepseek-chat", douyin_enabled=True,
                  reply_delay_min=0.5, max_context_rounds=5)
    check("AppConfig 自定义 api_key", c.api_key == "sk-test")
    check("AppConfig 自定义 model", c.model == "deepseek-chat")
    check("AppConfig 自定义 douyin_enabled", c.douyin_enabled)
    check("AppConfig 自定义 delay_min", c.reply_delay_min == 0.5)
    check("AppConfig 自定义 max_context", c.max_context_rounds == 5)


# ═══════════════════════════════════════════════════════════
# 4. storage/database.py — SQLite 操作层
# ═══════════════════════════════════════════════════════════

def test_database_init():
    from dmshoot.storage import database, models
    import tempfile, uuid
    old = database.DB_PATH
    try:
        tmp = _temp_db("init")
        database.DB_PATH = type(old)(tmp)
        # 清理旧测试文件
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()
        check("init_database 创建 DB 文件", database.DB_PATH.exists())
        os.remove(str(database.DB_PATH))
        database.DB_PATH = old
    except Exception:
        database.DB_PATH = old
        raise


def test_database_upsert_session():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("session")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        s = models.SessionRecord(
            session_id="test:1", platform="douyin",
            peer_name="测试A", peer_id="uid_a",
            last_message="最后一条", last_time=1234567890.0,
            unread_count=3, is_pinned=True, is_muted=False,
            avatar_url="http://avatar/a.jpg"
        )
        database.upsert_session(s)

        rows = database.get_sessions("douyin")
        check("upsert_session 后能查到", len(rows) == 1)
        r = rows[0]
        check("session_id 一致", r.session_id == "test:1")
        check("peer_name 一致", r.peer_name == "测试A")
        check("peer_id 一致", r.peer_id == "uid_a")
        check("last_message 一致", r.last_message == "最后一条")
        check("last_time 一致", r.last_time == 1234567890.0)
        check("unread_count 一致", r.unread_count == 3)
        check("is_pinned 一致", r.is_pinned)
        check("is_muted 一致", not r.is_muted)
        check("avatar_url 一致", r.avatar_url == "http://avatar/a.jpg")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_upsert_update():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("update")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        s1 = models.SessionRecord(session_id="upd:1", platform="bilibili",
                                  peer_name="旧名", unread_count=0)
        database.upsert_session(s1)

        s2 = models.SessionRecord(session_id="upd:1", platform="bilibili",
                                  peer_name="新名", unread_count=5,
                                  last_message="更新了")
        database.upsert_session(s2)

        rows = database.get_sessions("bilibili")
        check("upsert 更新后仍只有一条", len(rows) == 1)
        check("upsert 更新 peer_name", rows[0].peer_name == "新名")
        check("upsert 更新 unread_count", rows[0].unread_count == 5)
        check("upsert 更新 last_message", rows[0].last_message == "更新了")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_get_sessions_all():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("all")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        database.upsert_session(models.SessionRecord(
            session_id="all:1", platform="douyin", peer_name="D1",
            last_time=100.0))
        database.upsert_session(models.SessionRecord(
            session_id="all:2", platform="bilibili", peer_name="B1",
            last_time=200.0))

        rows = database.get_sessions()
        check("get_sessions() 返回所有会话", len(rows) == 2)
        check("按 last_time DESC 排序", rows[0].peer_name == "B1")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_save_and_get_messages():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("msg")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        m1 = models.ChatMessage(session_id="msg:1", sender_name="U",
                                content="消息1", timestamp=100.0)
        m2 = models.ChatMessage(session_id="msg:1", sender_name="AI",
                                content="消息2", is_self=True,
                                is_auto=True, timestamp=200.0)
        database.save_message(m1)
        database.save_message(m2)

        msgs = database.get_messages("msg:1")
        check("保存2条能查到2条", len(msgs) == 2)
        # get_messages 返回 oldest first
        check("第一条是消息1", msgs[0].content == "消息1")
        check("第二条是消息2", msgs[1].content == "消息2")
        check("消息2 is_self=True", msgs[1].is_self)
        check("消息2 is_auto=True", msgs[1].is_auto)

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_message_dedup():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("dedup")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        ts = 9999999999.0
        m = models.ChatMessage(session_id="dedup:1", sender_name="U",
                               content="重复消息", timestamp=ts)
        database.save_message(m)
        database.save_message(m)  # 重复保存

        msgs = database.get_messages("dedup:1")
        check("重复消息去重", len(msgs) == 1)

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_get_messages_limit():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("limit")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        for i in range(10):
            database.save_message(models.ChatMessage(
                session_id="limit:1", sender_name="U",
                content=f"消息{i}", timestamp=float(i)))

        msgs = database.get_messages("limit:1", limit=5)
        check("limit=5 返回最多5条", len(msgs) == 5)

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_delete_sessions():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("delete")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        database.upsert_session(models.SessionRecord(
            session_id="douyin:del_d1", platform="douyin", peer_name="D"))
        database.upsert_session(models.SessionRecord(
            session_id="bilibili:del_b1", platform="bilibili", peer_name="B"))
        database.save_message(models.ChatMessage(
            session_id="douyin:del_d1", sender_name="U", content="msg"))

        database.delete_sessions("douyin")
        check("delete douyin 后 douyin 会话为空",
              len(database.get_sessions("douyin")) == 0)
        check("delete douyin 后 bilibili 会话还在",
              len(database.get_sessions("bilibili")) == 1)
        check("delete douyin 后对应消息也被删",
              len(database.get_messages("douyin:del_d1")) == 0)

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_config_roundtrip():
    from dmshoot.storage import database, models
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("config")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        c = models.AppConfig(
            api_key="sk-roundtrip", model="deepseek-chat",
            douyin_enabled=True, reply_delay_min=2.5,
            max_context_rounds=8
        )
        database.save_config(c)
        loaded = database.load_config()

        check("config roundtrip api_key", loaded.api_key == "sk-roundtrip")
        check("config roundtrip model", loaded.model == "deepseek-chat")
        check("config roundtrip douyin_enabled", loaded.douyin_enabled)
        check("config roundtrip delay_min", loaded.reply_delay_min == 2.5)
        check("config roundtrip max_context", loaded.max_context_rounds == 8)

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_database_load_empty_config():
    from dmshoot.storage import database
    import tempfile
    old = database.DB_PATH
    try:
        tmp = _temp_db("empty_cfg")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        cfg = database.load_config()
        check("空DB load_config 返回默认值",
              cfg.model == "deepseek-v4-flash" and cfg.api_key == "")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


# ═══════════════════════════════════════════════════════════
# 5. ai/backend.py — AI 后端
# ═══════════════════════════════════════════════════════════

def test_ai_creation():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="sk-test", model="deepseek-v4-flash")
    check("AIBackend 有 key 时 configured=True", ai.configured)
    check("AIBackend 默认 base_url",
          ai.base_url == "https://api.deepseek.com")
    check("AIBackend model 存储", ai.model == "deepseek-v4-flash")


def test_ai_not_configured():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend()
    check("AIBackend 无 key 时 configured=False", not ai.configured)


def test_ai_custom_base_url():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k", base_url="https://custom.api.com/v1/")
    check("AIBackend 自定义 base_url 去掉尾部斜杠",
          ai.base_url == "https://custom.api.com/v1")


def test_ai_system_prompt():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k", system_prompt="你是客服")
    msgs = ai._build_messages([{"role": "user", "content": "你好"}])
    check("system prompt 出现在 system message",
          "你是客服" in msgs[0]["content"])
    check("system message role", msgs[0]["role"] == "system")


def test_ai_behavior_prompt():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k", behavior_prompt="回复要简短")
    msgs = ai._build_messages([{"role": "user", "content": "你好"}])
    check("behavior prompt 出现在 system message",
          "回复要简短" in msgs[0]["content"])


def test_ai_dual_prompt():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k", system_prompt="角色A", behavior_prompt="行为B")
    msgs = ai._build_messages([{"role": "user", "content": "x"}])
    check("system+behavior 拼接",
          "角色A" in msgs[0]["content"] and "行为B" in msgs[0]["content"])


def test_ai_only_behavior():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k", behavior_prompt="仅行为")
    msgs = ai._build_messages([{"role": "user", "content": "x"}])
    check("仅 behavior 正确", msgs[0]["content"] == "仅行为")


def test_ai_only_system():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k", system_prompt="仅角色")
    msgs = ai._build_messages([{"role": "user", "content": "x"}])
    check("仅 system 正确", msgs[0]["content"] == "仅角色")


def test_ai_empty_prompts():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k")
    msgs = ai._build_messages([{"role": "user", "content": "你好"}])
    check("无 prompt 时只有 user message", len(msgs) == 1)
    check("无 prompt 时第一条是 user", msgs[0]["role"] == "user")


def test_ai_context_management():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k")
    check("初始无上下文", len(ai._contexts) == 0)

    # 手动注入上下文
    ai._contexts["sess:1"] = [
        {"role": "user", "content": "问题1"},
        {"role": "assistant", "content": "回答1"},
    ]
    check("手动注入后存在", "sess:1" in ai._contexts)


def test_ai_clear_context():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k")
    ai._contexts["sess:1"] = [{"role": "user", "content": "x"}]
    ai._contexts["sess:2"] = [{"role": "user", "content": "y"}]

    ai.clear_context("sess:1")
    check("clear_context 清除指定会话", "sess:1" not in ai._contexts)
    check("clear_context 不影响其他会话", "sess:2" in ai._contexts)

    ai.clear_all_contexts()
    check("clear_all_contexts 清除全部", len(ai._contexts) == 0)


def test_ai_build_messages_preserves_user():
    from dmshoot.ai.backend import AIBackend
    ai = AIBackend(api_key="k")
    msgs = ai._build_messages([
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
    ])
    check("user message 保留", msgs[-2]["content"] == "Q1")
    check("assistant message 保留", msgs[-1]["content"] == "A1")


def test_ai_handle_message_empty():
    from dmshoot.ai.backend import AIBackend
    from dmshoot.core.message import Message
    ai = AIBackend(api_key="k")
    m = Message(platform="bilibili", msg_type="text", sender_id="1",
                sender_name="A", session_id="b:1", content="   ")
    # 空内容不调用 API
    result = asyncio.run(ai.handle_message(m))
    check("空消息返回 None", result is None)


def test_ai_handle_message_no_key():
    from dmshoot.ai.backend import AIBackend
    from dmshoot.core.message import Message
    ai = AIBackend()  # 无 api_key
    m = Message(platform="bilibili", msg_type="text", sender_id="1",
                sender_name="A", session_id="b:1", content="你好")
    result = asyncio.run(ai.handle_message(m))
    check("无 API key 时返回 None", result is None)


def test_ai_global_singleton():
    from dmshoot.ai.backend import get_ai, init_ai
    a1 = get_ai()
    check("get_ai 创建实例", a1 is not None)
    a2 = get_ai()
    check("get_ai 单例", a1 is a2)

    init_ai(api_key="sk-new", system_prompt="新角色", model="m1",
            behavior_prompt="新行为")
    a3 = get_ai()
    check("init_ai 更新实例", a3.api_key == "sk-new")
    check("init_ai 更新 model", a3.model == "m1")


def test_ai_max_context_messages():
    from dmshoot.ai.backend import AIBackend
    check("MAX_CONTEXT_MESSAGES 常量", AIBackend.MAX_CONTEXT_MESSAGES == 20)


# ═══════════════════════════════════════════════════════════
# 6. ai/prompts.py — 提示词管理
# ═══════════════════════════════════════════════════════════

def test_prompts_load():
    from dmshoot.ai.prompts import load_prompts
    chars = load_prompts()
    check("load_prompts 返回 dict", isinstance(chars, dict))
    check("load_prompts 非空", len(chars) > 0)
    check("load_prompts 包含柁炑", "柁炑" in chars)
    check("load_prompts 柁炑内容非空", len(chars["柁炑"]) > 0)


def test_prompts_strip_number_prefix():
    from dmshoot.ai.prompts import load_prompts
    chars = load_prompts()
    check("02_热情朋友 → 热情朋友", "热情朋友" in chars)
    check("03_专业客服 → 专业客服", "专业客服" in chars)
    check("04_高冷话痨 → 高冷话痨", "高冷话痨" in chars)


def test_behavior_prompts_load():
    from dmshoot.ai.prompts import load_behavior_prompts
    behaviors = load_behavior_prompts()
    check("load_behavior_prompts 返回 dict", isinstance(behaviors, dict))
    check("load_behavior_prompts 非空", len(behaviors) > 0)
    check("load_behavior_prompts 包含默认", "默认" in behaviors)


def test_prompts_save_and_delete():
    from dmshoot.ai.prompts import save_prompt, delete_prompt, load_prompts
    name = "_test_prompt_temp"
    save_prompt(name, "测试提示词内容")

    chars = load_prompts()
    check("save_prompt 保存成功", name in chars)
    check("save_prompt 内容正确", chars[name] == "测试提示词内容")

    delete_prompt(name)
    chars2 = load_prompts()
    check("delete_prompt 删除成功", name not in chars2)


def test_prompts_delete_nonexistent():
    from dmshoot.ai.prompts import delete_prompt
    # 不应该崩溃
    try:
        delete_prompt("_nonexistent_xyz_123")
        ok("delete_prompt 不存在时不崩溃")
    except Exception as e:
        fail("delete_prompt 不存在时崩溃", str(e))


# ═══════════════════════════════════════════════════════════
# 8. plugins/manager.py — 插件管理
# ═══════════════════════════════════════════════════════════

def test_plugin_manager_discover():
    from dmshoot.plugins.manager import PluginManager
    pm = PluginManager()
    plugins = pm.list()
    check("PluginManager 发现插件", len(plugins) > 0)
    check("PluginManager 列表非空", len(plugins) >= 1)


def test_plugin_manager_get_bilibili():
    from dmshoot.plugins.manager import PluginManager
    pm = PluginManager()
    bili = pm.get("bilibili")
    check("get bilibili 非空", bili is not None)
    check("bilibili.id", bili.id == "bilibili")
    check("bilibili.name", bili.name == "B站")
    check("bilibili 有 adapter_cls", bili.adapter_cls is not None)


def test_plugin_manager_get_nonexistent():
    from dmshoot.plugins.manager import PluginManager
    pm = PluginManager()
    check("get 不存在的插件返回 None",
          pm.get("nonexistent_platform") is None)


def test_plugin_manager_platform_ids():
    from dmshoot.plugins.manager import PluginManager
    pm = PluginManager()
    ids = pm.platform_ids
    check("platform_ids 是列表", isinstance(ids, list))
    check("platform_ids 包含 bilibili", "bilibili" in ids)


def test_plugin_info_cookie_fields():
    from dmshoot.plugins.manager import PluginManager
    pm = PluginManager()
    bili = pm.get("bilibili")
    check("bilibili cookie_fields 非空", len(bili.cookie_fields) > 0)
    check("bilibili cookie_fields 有 bilibili_sessdata",
          "bilibili_sessdata" in bili.cookie_fields)


def test_plugin_info_create_adapter():
    from dmshoot.plugins.manager import PluginManager
    from dmshoot.core.bus import MessageBus
    from dmshoot.storage.models import AppConfig

    pm = PluginManager()
    bili = pm.get("bilibili")
    bus = MessageBus()
    cfg = AppConfig(bilibili_sessdata="test_sessdata", bilibili_jct="test_jct")

    adapter = bili.create_adapter(bus, cfg)
    check("create_adapter 返回实例", adapter is not None)
    check("create_adapter 平台名", adapter.platform_name == "bilibili")


# ═══════════════════════════════════════════════════════════
# 9. utils/platform_connector.py — Cookie 验证
# ═══════════════════════════════════════════════════════════

def test_verify_douyin_invalid_cookie():
    from dmshoot.utils.platform_connector import verify_douyin
    ok_flag, msg = asyncio.run(verify_douyin("invalid_cookie_string"))
    check("verify_douyin 不崩溃", isinstance(ok_flag, bool) and isinstance(msg, str))


def test_verify_bilibili_invalid_cookie():
    from dmshoot.utils.platform_connector import verify_bilibili
    ok_flag, msg = asyncio.run(verify_bilibili("bad_sessdata", "bad_jct"))
    check("verify_bilibili 无效 cookie 返回 False", not ok_flag)
    check("verify_bilibili 有错误信息", len(msg) > 0)


# ═══════════════════════════════════════════════════════════
# 10. utils/cookie_reader.py — Cookie 解析
# ═══════════════════════════════════════════════════════════

def test_extract_bilibili_cookies_parse():
    from dmshoot.utils.cookie_reader import extract_bilibili_cookies_sync
    # Monkey-patch asyncio.run 避免真的启动浏览器
    original_run = asyncio.run

    async def fake_login(path):
        return "SESSDATA=fake_sess; bili_jct=fake_jct; other=ignored"

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_bilibili_cookies_sync()
        check("extract_bilibili SESSDATA 解析",
              result.get("SESSDATA") == "fake_sess")
        check("extract_bilibili bili_jct 解析",
              result.get("bili_jct") == "fake_jct")
    finally:
        asyncio.run = original_run


def test_extract_bilibili_cookies_empty():
    from dmshoot.utils.cookie_reader import extract_bilibili_cookies_sync
    original_run = asyncio.run

    async def fake_login(path):
        return ""

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_bilibili_cookies_sync()
        check("空 cookie 返回空 dict", result == {"SESSDATA": "", "bili_jct": ""})
    finally:
        asyncio.run = original_run


def test_extract_bilibili_cookies_only_sessdata():
    from dmshoot.utils.cookie_reader import extract_bilibili_cookies_sync
    original_run = asyncio.run

    async def fake_login(path):
        return "SESSDATA=only_sess"

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_bilibili_cookies_sync()
        check("仅 SESSDATA 正确", result["SESSDATA"] == "only_sess")
        check("无 bili_jct 为空", result["bili_jct"] == "")
    finally:
        asyncio.run = original_run


def test_extract_douyin_cookies_empty():
    from dmshoot.utils.cookie_reader import extract_douyin_cookies_sync
    original_run = asyncio.run

    async def fake_login(path):
        return None

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_douyin_cookies_sync()
        check("douyin None 登录返回空字典", result == {})
    finally:
        asyncio.run = original_run


# ═══════════════════════════════════════════════════════════
# 11. 集成测试: Message → DB → AI 全链路
# ═══════════════════════════════════════════════════════════

def test_integration_message_roundtrip():
    """消息从创建到存储再到读取的完整链路"""
    from dmshoot.core.message import Message
    from dmshoot.storage import database, models
    import tempfile

    old = database.DB_PATH
    try:
        tmp = _temp_db("int")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        # 模拟收到一条 B站消息
        raw = {"msg_type": 1, "sender_uid": "999", "sender_name": "测试者",
               "talker_id": "int_test", "content": "帮我查一下", "msg_seqno": 1}
        msg = Message.from_bilibili(raw)

        # 存为 ChatMessage
        cm = models.ChatMessage(
            session_id=msg.session_id, sender_name=msg.sender_name,
            sender_id=msg.sender_id, content=msg.content,
            msg_type=msg.msg_type
        )
        database.save_message(cm)

        # 读出来
        msgs = database.get_messages("bilibili:int_test")
        check("集成: 消息 roundtrip 成功", len(msgs) == 1)
        check("集成: 内容一致", msgs[0].content == "帮我查一下")
        check("集成: 发送者一致", msgs[0].sender_name == "测试者")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


# ═══════════════════════════════════════════════════════════
# 测试运行器
# ═══════════════════════════════════════════════════════════

ALL_TESTS: list[tuple[str, callable]] = [
    # 1. core/message.py (19)
    ("Message 基本创建", test_message_basic),
    ("Message is_self", test_message_self),
    ("Message is_auto_reply", test_message_auto_reply),
    ("Message media_url", test_message_media),
    ("Message 显式时间戳", test_message_explicit_timestamp),
    ("from_douyin 文本", test_message_from_douyin_text),
    ("from_douyin 图片", test_message_from_douyin_image),
    ("from_douyin 语音", test_message_from_douyin_voice),
    ("from_douyin 视频", test_message_from_douyin_video),
    ("from_douyin 未知类型", test_message_from_douyin_unknown_type),
    ("from_douyin 缺字段", test_message_from_douyin_missing_fields),
    ("from_bilibili 文本", test_message_from_bilibili_text),
    ("from_bilibili 图片(type2)", test_message_from_bilibili_image),
    ("from_bilibili 图片(type6)", test_message_from_bilibili_image_type6),
    ("from_bilibili 未知类型", test_message_from_bilibili_unknown_type),
    ("from_bilibili 缺字段", test_message_from_bilibili_missing_fields),
    ("Message system_message", test_message_system_message),
    ("Message Unicode", test_message_unicode),

    # 2. core/bus.py (8)
    ("Bus 单例", test_bus_singleton),
    ("Bus 信号存在", test_bus_signals_exist),
    ("Bus emit_message", test_bus_emit_message),
    ("Bus request_reply", test_bus_request_reply),
    ("Bus platform_status", test_bus_platform_status),
    ("Bus PlatformStatus 常量", test_bus_platform_status_constants),
    ("Bus AI signals", test_bus_ai_signals),

    # 3. storage/models.py (7)
    ("SessionRecord 基本", test_session_record_basic),
    ("SessionRecord 默认值", test_session_record_defaults),
    ("SessionRecord platform_display", test_session_record_platform_display),
    ("ChatMessage 基本", test_chat_message_basic),
    ("ChatMessage is_self/is_auto", test_chat_message_self_and_auto),
    ("ChatMessage 显式时间戳", test_chat_message_explicit_timestamp),
    ("AppConfig 默认值", test_app_config_defaults),
    ("AppConfig 自定义", test_app_config_custom),

    # 4. storage/database.py (10)
    ("DB 初始化", test_database_init),
    ("DB upsert_session", test_database_upsert_session),
    ("DB upsert 更新", test_database_upsert_update),
    ("DB get_sessions 全部", test_database_get_sessions_all),
    ("DB save/get messages", test_database_save_and_get_messages),
    ("DB 消息去重", test_database_message_dedup),
    ("DB messages limit", test_database_get_messages_limit),
    ("DB delete_sessions", test_database_delete_sessions),
    ("DB config roundtrip", test_database_config_roundtrip),
    ("DB load empty config", test_database_load_empty_config),

    # 5. ai/backend.py (15)
    ("AI 创建", test_ai_creation),
    ("AI 未配置", test_ai_not_configured),
    ("AI 自定义 base_url", test_ai_custom_base_url),
    ("AI system_prompt", test_ai_system_prompt),
    ("AI behavior_prompt", test_ai_behavior_prompt),
    ("AI 双提示词", test_ai_dual_prompt),
    ("AI 仅 behavior", test_ai_only_behavior),
    ("AI 仅 system", test_ai_only_system),
    ("AI 空 prompts", test_ai_empty_prompts),
    ("AI 上下文管理", test_ai_context_management),
    ("AI clear_context", test_ai_clear_context),
    ("AI build_messages 保留用户", test_ai_build_messages_preserves_user),
    ("AI 空消息返回 None", test_ai_handle_message_empty),
    ("AI 无 key 返回 None", test_ai_handle_message_no_key),
    ("AI 全局单例", test_ai_global_singleton),
    ("AI MAX_CONTEXT", test_ai_max_context_messages),

    # 6. ai/prompts.py (5)
    ("Prompts 加载", test_prompts_load),
    ("Prompts 数字前缀剥离", test_prompts_strip_number_prefix),
    ("Behavior 加载", test_behavior_prompts_load),
    ("Prompts 保存/删除", test_prompts_save_and_delete),
    ("Prompts 删除不存在", test_prompts_delete_nonexistent),

    # 7. plugins/ (6)
    ("Plugin 发现", test_plugin_manager_discover),
    ("Plugin get bilibili", test_plugin_manager_get_bilibili),
    ("Plugin get 不存在", test_plugin_manager_get_nonexistent),
    ("Plugin platform_ids", test_plugin_manager_platform_ids),
    ("Plugin cookie_fields", test_plugin_info_cookie_fields),
    ("Plugin create_adapter", test_plugin_info_create_adapter),

    # 9. utils/platform_connector.py (2)
    ("verify_douyin 无效", test_verify_douyin_invalid_cookie),
    ("verify_bilibili 无效", test_verify_bilibili_invalid_cookie),

    # 10. utils/cookie_reader.py (4)
    ("extract_bilibili 解析", test_extract_bilibili_cookies_parse),
    ("extract_bilibili 空", test_extract_bilibili_cookies_empty),
    ("extract_bilibili 仅 SESSDATA", test_extract_bilibili_cookies_only_sessdata),
    ("extract_douyin 空", test_extract_douyin_cookies_empty),

    # 11. 集成测试 (1)
    ("集成: Message→DB roundtrip", test_integration_message_roundtrip),
]


if __name__ == "__main__":
    print("DMShoot 完整测试套件")
    print("=" * 50)
    print(f"共 {len(ALL_TESTS)} 个测试")
    print()

    passed = 0
    failed_tests: list[str] = []

    for name, fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except Exception as e:
            import traceback
            fail(name, str(e))
            traceback.print_exc()
            failed_tests.append(name)

    print()
    print("=" * 50)
    rate = passed / len(ALL_TESTS) * 100
    print(f"结果: {passed}/{len(ALL_TESTS)} 通过 ({rate:.1f}%)")

    if failed_tests:
        print(f"\n失败 ({len(failed_tests)}):")
        for name in failed_tests:
            print(f"  ✗ {name}")

    sys.exit(0 if passed == len(ALL_TESTS) else 1)
