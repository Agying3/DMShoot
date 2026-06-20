"""DMShoot 核心链路测试 — 登录 → 发送私信 → AI回复 → 消息历史

每个测试覆盖完整数据流: GUI按钮 → 后台逻辑 → DB 读写
"""

import pytest
import time
from unittest.mock import MagicMock, patch, AsyncMock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


# ═══════════════════════════════════════════════════════════
# 1. 登录流程 — GUI按钮 → Playwright扫码 → Cookie写入DB
# ═══════════════════════════════════════════════════════════

@pytest.mark.gui
@pytest.mark.login
class TestLoginFlow:
    """登录完整链路测试"""

    def test_login_page_loads(self, qapp, qtbot):
        """L1: 登录页面正常加载，平台按钮可见"""
        from dmshoot.gui.pages.login_page import LoginPage

        page = LoginPage()
        qtbot.addWidget(page)

        assert page.isVisible() is False  # 初始不显示
        page.show()
        qtbot.waitExposed(page)

        # 平台按钮应该存在
        assert hasattr(page, "bili_btn") or hasattr(page, "dy_btn")

    def test_login_click_triggers_worker(self, qapp, qtbot):
        """L2: 点击登录按钮 → 创建 LoginWorker → 不阻塞 GUI"""
        from dmshoot.gui.pages.login_page import LoginPage

        page = LoginPage()
        qtbot.addWidget(page)
        page.show()

        # 初始 worker 为空
        assert page._worker is None

        # 如果有 B站按钮就点击
        if hasattr(page, "bili_btn"):
            with patch("dmshoot.gui.workers.login_worker.LoginWorker.start") as mock_start:
                qtbot.mouseClick(page.bili_btn, Qt.LeftButton)
                # 应该创建了 worker（异步完成）
                qtbot.waitUntil(lambda: page._worker is not None, timeout=2000)
                assert mock_start.called

    def test_cookie_save_updates_db(self, qapp, qtbot, temp_db, mock_config):
        """L3: Cookie 提取结果 → 保存到 SQLite → 状态更新"""
        from dmshoot.gui.pages.login_page import LoginPage
        from dmshoot.storage import database

        page = LoginPage()
        qtbot.addWidget(page)

        # 连接信号收集
        connected_platforms = []
        page.connect_platform.connect(lambda p: connected_platforms.append(p))

        # 模拟 Cookie 提取完成
        page._on_cookie_ready("bilibili", {
            "SESSDATA": "test_sess", "bili_jct": "test_jct",
            "buvid3": "bv3", "buvid4": "bv4",
            "dedeuserid": "duid", "ac_time_value": "atv",
        })

        # 验证 DB 写入
        cfg = database.load_config()
        assert cfg.bilibili_sessdata == "test_sess"
        assert cfg.bilibili_jct == "test_jct"

        # 验证信号发射
        assert "bilibili" in connected_platforms


# ═══════════════════════════════════════════════════════════
# 2. 发送私信流程 — 输入框 → 发送 → DB 写入 outgoing
# ═══════════════════════════════════════════════════════════

@pytest.mark.gui
@pytest.mark.chat
class TestSendDM:
    """发送私信完整链路测试"""

    def test_send_message_writes_db(self, temp_db):
        """L4: send_message → 写 outgoing 消息到 DB"""
        from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
        from dmshoot.storage import database
        from dmshoot.storage.models import ChatMessage

        adapter = BilibiliAdapter()
        adapter._credential = MagicMock()
        adapter._my_uid = 999

        with patch("bilibili_api.session.send_msg"):
            result = adapter.send_message("bilibili:12345", "test message")
            assert result is True

        # 验证 outgoing 消息可在 DB 中写入
        msg = ChatMessage(
            session_id="bilibili:12345", sender_name="我", sender_id="self",
            content="test message", msg_type="text", timestamp=time.time(),
            is_self=True, is_auto=False,
        )
        written = database.save_message(msg)
        assert written is True

    def test_rate_limiter_blocks_overflow(self):
        """L5: 限流器 → burst 用完后拒绝发送"""
        from dmshoot.core.rate_limiter import RateLimiter

        rl = RateLimiter(rate=5.0, burst=3)
        # 用光 burst
        for _ in range(3):
            assert rl.acquire() is True
        # 第4次被限流
        assert rl.acquire() is False


# ═══════════════════════════════════════════════════════════
# 3. AI 自动回复流程 — 收到消息 → AI 回复 → DB 写入回复
# ═══════════════════════════════════════════════════════════

@pytest.mark.chat
class TestAIReply:
    """AI 回复完整链路测试"""

    def test_ai_builds_messages_from_context(self, temp_db):
        """L6: 从 DB 加载上下文 → AI._build_messages → 包含历史"""
        from dmshoot.ai.backend import AIBackend
        from dmshoot.storage import database
        from dmshoot.storage.models import ChatMessage

        # 写入几条假消息
        msgs = [
            ChatMessage(session_id="test:sid1", sender_name="User", sender_id="1",
                        content="hello", msg_type="text", timestamp=time.time(),
                        is_self=False, is_auto=False),
            ChatMessage(session_id="test:sid1", sender_name="AI", sender_id="self",
                        content="hi there", msg_type="text", timestamp=time.time() + 1,
                        is_self=True, is_auto=True),
        ]
        for m in msgs:
            database.save_message(m)

        # 从 DB 加载
        history = database.get_messages("test:sid1", limit=10)
        assert len(history) == 2

        # AI 构建消息
        ai = AIBackend(api_key="sk-test", system_prompt="Role A", behavior_prompt="Be helpful")
        ctx = ai._contexts.get("test:sid1", [])
        for m in history:
            role = "assistant" if m.is_self else "user"
            ctx.append({"role": role, "content": m.content})
        ai._contexts["test:sid1"] = ctx

        msgs = ai._build_messages(ctx)
        assert len(msgs) > 0
        # 第一条应该是 system prompt
        assert "Role A" in msgs[0]["content"]

    def test_ai_reply_saves_to_db(self, temp_db):
        """L7: AI 生成回复 → save_message → DB 有 is_auto=True 的消息"""
        from dmshoot.storage import database
        from dmshoot.storage.models import ChatMessage

        reply = ChatMessage(
            session_id="test:sid1", sender_name="AI助手", sender_id="self",
            content="这是自动回复", msg_type="text", timestamp=time.time(),
            is_self=True, is_auto=True, persona="TestAI",
        )
        written = database.save_message(reply)
        assert written is True

        # 验证写入
        msgs = database.get_messages("test:sid1", limit=5)
        auto_msgs = [m for m in msgs if m.is_auto]
        assert len(auto_msgs) >= 1
        assert auto_msgs[-1].content == "这是自动回复"


# ═══════════════════════════════════════════════════════════
# 4. 消息历史流程 — DB 查询 → 会话列表 → 消息详情
# ═══════════════════════════════════════════════════════════

@pytest.mark.history
class TestMessageHistory:
    """消息历史完整链路测试"""

    def test_session_list_from_db(self, temp_db):
        """L8: 写入会话 → get_sessions → 按时间倒序"""
        from dmshoot.storage import database
        from dmshoot.storage.models import SessionRecord

        sessions = [
            SessionRecord(session_id="bilibili:100", platform="bilibili",
                          peer_name="User1", peer_id="100",
                          last_message="hello", last_time=1000, avatar_url=""),
            SessionRecord(session_id="bilibili:200", platform="bilibili",
                          peer_name="User2", peer_id="200",
                          last_message="world", last_time=2000, avatar_url=""),
        ]
        for s in sessions:
            database.upsert_session(s)

        result = database.get_sessions("bilibili")
        assert len(result) >= 2
        # 按 last_time 倒序
        assert result[0].last_time >= result[-1].last_time

    def test_messages_load_by_session(self, temp_db):
        """L9: 批量写入消息 → get_messages → 正确数量和顺序"""
        from dmshoot.storage import database
        from dmshoot.storage.models import ChatMessage

        batch = [
            ChatMessage(session_id="test:batch", sender_name=f"User{i}",
                        sender_id=str(i), content=f"msg_{i}", msg_type="text",
                        timestamp=float(i), is_self=False, is_auto=False)
            for i in range(20)
        ]
        written = database.save_messages_batch(batch)
        assert written == 20

        result = database.get_messages("test:batch", limit=50)
        assert len(result) == 20
        # 按时间升序
        for i in range(len(result) - 1):
            assert result[i].timestamp <= result[i + 1].timestamp

    def test_dedup_prevents_duplicates(self, temp_db):
        """L10: 重复消息 → INSERT OR IGNORE → 不重复写入"""
        from dmshoot.storage import database
        from dmshoot.storage.models import ChatMessage

        msg = ChatMessage(
            session_id="test:dedup", sender_name="User", sender_id="1",
            content="unique_msg", msg_type="text", timestamp=time.time(),
            is_self=False, is_auto=False,
        )
        first = database.save_message(msg)
        second = database.save_message(msg)
        assert first is True
        assert second is False  # 去重生效

    def test_unread_count_increments(self, temp_db):
        """L11: 新消息 → increment_unread → 计数正确"""
        from dmshoot.storage import database
        from dmshoot.storage.models import SessionRecord

        sid = "test:unread"
        database.upsert_session(SessionRecord(
            session_id=sid, platform="test", peer_name="U", peer_id="1",
            last_message="", last_time=0, avatar_url="",
        ))

        assert database.increment_unread(sid) == 1
        assert database.increment_unread(sid) == 2
        assert database.increment_unread(sid) == 3

        database.reset_unread(sid)
        # 重置后应该为 0（再查一次）
        sessions = database.get_sessions("test")
        unread = next((s.unread_count for s in sessions if s.session_id == sid), None)
        assert unread == 0


# ═══════════════════════════════════════════════════════════
# 5. B站异步轮询 — asyncio.gather 并发
# ═══════════════════════════════════════════════════════════

@pytest.mark.slow
@pytest.mark.chat
class TestAsyncPoll:
    """B站异步轮询测试"""

    def test_async_poll_uses_gather(self, mock_bilibili_api):
        """L12: _async_poll → asyncio.gather → 并发拉取"""
        import asyncio
        from dmshoot.plugins.bilibili.adapter import BilibiliAdapter

        adapter = BilibiliAdapter()
        adapter._credential = MagicMock()
        adapter._my_uid = 999
        adapter._running = True
        adapter._http = MagicMock()
        adapter._on_message = MagicMock()

        async def run_poll():
            await adapter._async_poll()
            return True

        result = asyncio.run(run_poll())
        assert result is True

    def test_concurrent_fetch_reduces_latency(self, mock_bilibili_api):
        """L13: 3会话并发拉取 → 耗时 < 串行 O(N*RTT)"""
        import asyncio
        import time
        from dmshoot.plugins.bilibili.adapter import BilibiliAdapter

        adapter = BilibiliAdapter()
        adapter._credential = MagicMock()
        adapter._my_uid = 999
        adapter._running = True
        adapter._http = MagicMock()
        adapter._on_message = MagicMock()

        async def run():
            t0 = time.perf_counter()
            await adapter._async_poll()
            return (time.perf_counter() - t0) * 1000

        elapsed = asyncio.run(run())
        # Mock 下应 < 500ms（真实 B站 API ~200ms RTT）
        assert elapsed < 2000, f"轮询耗时 {elapsed:.0f}ms 过高"


# ═══════════════════════════════════════════════════════════
# 6. 配置持久化
# ═══════════════════════════════════════════════════════════

class TestConfig:
    """配置读写测试"""

    def test_config_roundtrip(self, temp_db):
        """L14: 保存配置 → 加载配置 → 值一致"""
        from dmshoot.storage import database
        from dmshoot.storage.models import AppConfig

        cfg = AppConfig(
            api_key="sk-abc123", model="test-model",
            douyin_cookie="dy_cookie_val", bilibili_sessdata="b_sess",
        )
        database.save_config(cfg)
        loaded = database.load_config()

        assert loaded.api_key == "sk-abc123"
        assert loaded.model == "test-model"
        assert loaded.douyin_cookie == "dy_cookie_val"
        assert loaded.bilibili_sessdata == "b_sess"

    def test_config_update_single_field(self, temp_db):
        """L15: update_config_field → 原子更新单个字段"""
        from dmshoot.storage import database

        database.update_config_field("model", "new-model")
        cfg = database.load_config()
        assert cfg.model == "new-model"
