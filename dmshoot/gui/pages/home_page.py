"""首页 — 刻度尺平台切换 + 通讯录 + 对话气泡"""

from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter
from PySide6.QtCore import Qt, QTimer

from dmshoot.gui.widgets.ruler import PlatformRuler
from dmshoot.gui.widgets.contact import ContactList
from dmshoot.gui.quick_chat_view import ChatView
from dmshoot.gui.monitor_panel import MonitorPanel
from dmshoot.storage import database
from dmshoot.storage.models import SessionRecord

_IM_UNAVAILABLE = frozenset({"xiaohongshu", "kuaishou"})  # Web 端不支持 IM


class HomePage(QWidget):
    MESSAGE_PAGE_SIZE = 100

    def __init__(self, monitor: MonitorPanel, platforms: list[tuple[str, str]], font_manager=None):
        super().__init__()
        self.monitor = monitor
        self._adapters: dict = {}
        self._current_platform = platforms[0][0] if platforms else "bilibili"
        self._current_session: str = ""
        self._msg_cache: dict[str, list] = {}  # 消息缓存，避免重复读DB
        self._history_cursor: dict[str, tuple[float, int]] = {}
        self._history_has_more: dict[str, bool] = {}
        self._history_loading = False
        # 通讯录节流：高频消息时 500ms 内只刷新一次
        self._contacts_throttle = QTimer(self)
        self._contacts_throttle.setSingleShot(True)
        self._contacts_throttle.setInterval(500)
        self._contacts_throttle.timeout.connect(self._do_load_contacts)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # 刻度尺
        self.ruler = PlatformRuler(platforms)
        self.ruler.switched.connect(self._on_platform_switch)
        main.addWidget(self.ruler)

        # 左右分栏（无手柄，通讯录固定宽度）
        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)

        # 左：通讯录
        self.contacts = ContactList()
        self.contacts.session_selected.connect(self._on_session_select)
        hbox.addWidget(self.contacts)

        # 右：对话气泡
        self.chat = ChatView(font_manager=font_manager)
        self.chat.history_requested.connect(self._load_older_messages)
        hbox.addWidget(self.chat, stretch=1)

        horizontal_container = QWidget()
        horizontal_container.setLayout(hbox)

        # 底部监控（可拖拽调整高度）
        self.monitor.setObjectName("MonitorPanel")
        v_split = QSplitter(Qt.Vertical)
        v_split.setStyleSheet(
            "QSplitter::handle { background: transparent; height: 6px; }"
            "QSplitter::handle:hover { background: rgba(0,229,255,0.12); }"
        )
        v_split.addWidget(horizontal_container)
        v_split.addWidget(self.monitor)
        v_split.setStretchFactor(0, 4)
        v_split.setStretchFactor(1, 1)
        v_split.setSizes([400, 120])

        main.addWidget(v_split, stretch=1)
        self.setLayout(main)
        self._load_contacts()

    def set_adapters(self, adapters: dict):
        """接收 MainWindow 的适配器字典，用于显示当前账号头像。"""
        self._adapters = adapters
        self.refresh_account_avatar()

    def refresh_account_avatar(self, platform: str | None = None, *_):
        platform = platform or self._current_platform
        adapter = self._adapters.get(platform)
        avatar = ""
        if adapter is not None:
            avatar = (
                getattr(adapter, "_my_avatar", "")
                or getattr(adapter, "_my_avatar_url", "")
                or ""
            )
        if platform == self._current_platform:
            self.chat.set_account_avatar(avatar)

    def _on_platform_switch(self, platform: str):
        self._current_platform = platform
        self.refresh_account_avatar(platform)
        # 切换到非 IM 平台时，清除 Markdown 视图回到正常模式
        if platform not in _IM_UNAVAILABLE:
            self.chat.clear_markdown()
        self._do_load_contacts()

    def _load_contacts(self):
        """节流加载通讯录（高频消息场景合并刷新）"""
        if not self._contacts_throttle.isActive():
            self._contacts_throttle.start()

    def _do_load_contacts(self):
        sessions = database.get_sessions(self._current_platform)
        # 过滤系统机器人
        BOT_NAMES = {"UP主小助手", "哔哩哔哩智能机"}
        sessions = [s for s in sessions if s.peer_name not in BOT_NAMES]
        self.contacts.list.setUpdatesEnabled(False)
        self.contacts.set_sessions(sessions)
        self.contacts.list.setUpdatesEnabled(True)
        # 空状态引导
        if not sessions:
            platform_names = {"douyin": "抖音", "bilibili": "B站", "xiaohongshu": "小红书", "kuaishou": "快手"}
            pn = platform_names.get(self._current_platform, self._current_platform)
            # 不可用平台：显示逆向日志全文
            if self._current_platform in _IM_UNAVAILABLE:
                log_path = Path(__file__).parent.parent.parent.parent / "docs" / "XHS_IM_逆向日志.md"
                self.chat.show_markdown(str(log_path), f"{pn} IM 逆向日志")
            else:
                self.chat.show_placeholder(f"暂未连接 {pn}\n\n请前往左侧「登录」扫码连接平台")

    def _on_session_select(self, session_id: str, peer_name: str = "会话"):
        self._current_session = session_id
        database.reset_unread(session_id)  # 进入会话时清零未读
        self._msg_cache.pop(session_id, None)
        # 兼容旧版本已经写入的“AI本地回复 + 平台自发回显”双记录。
        msgs = database.deduplicate_messages(
            database.get_messages(session_id, limit=self.MESSAGE_PAGE_SIZE)
        )
        self._msg_cache[session_id] = msgs
        self._history_has_more[session_id] = len(msgs) >= self.MESSAGE_PAGE_SIZE
        if msgs:
            self._history_cursor[session_id] = (msgs[0].timestamp, msgs[0].id)
        else:
            self._history_cursor.pop(session_id, None)
        session = next(
            (item for item in database.get_sessions(self._current_platform)
             if item.session_id == session_id),
            None,
        )
        peer_avatar_url = session.avatar_url if session else ""
        self.refresh_account_avatar(self._current_platform)
        self.chat.set_conversation(session_id, peer_avatar_url)
        self.chat.set_history_available(self._history_has_more.get(session_id, False))
        self.chat.load_messages(peer_name, msgs, peer_avatar_url)

    def _load_older_messages(self, session_id: str):
        """滚动到顶部时向 SQLite 读取更早的一页，并保持可视消息锚点。"""
        if session_id != self._current_session or self._history_loading:
            return
        if not self._history_has_more.get(session_id, False):
            self.chat.set_history_available(False)
            return
        cursor = self._history_cursor.get(session_id)
        if cursor is None:
            self._history_has_more[session_id] = False
            self.chat.set_history_available(False)
            return

        self._history_loading = True
        try:
            before_timestamp, before_id = cursor
            older = database.get_messages_before(
                session_id,
                before_timestamp,
                before_id=before_id,
                limit=self.MESSAGE_PAGE_SIZE,
            )
            if older:
                cache = self._msg_cache.get(session_id, [])
                self._msg_cache[session_id] = older + cache
                self._history_cursor[session_id] = (older[0].timestamp, older[0].id)
                self.chat.prepend_messages(older)
            has_more = len(older) >= self.MESSAGE_PAGE_SIZE
            self._history_has_more[session_id] = has_more
            self.chat.set_history_available(has_more)
        finally:
            self._history_loading = False
            self.chat.history_load_finished()

    def refresh_session(self, session_id: str):
        """新联系人或资料补全后，按现有节流策略刷新当前平台。"""
        if session_id.startswith(f"{self._current_platform}:"):
            self._load_contacts()

    def add_message(self, session_id: str, sender_name: str, content: str,
                     is_auto: bool = False, timestamp: float = None, persona: str = "",
                     unread_count: int = -1, send_ok: bool = True,
                     sender_id: str = "", message_key: str = "", is_self: bool = False):
        """添加新消息到缓存和界面。缓存按时间排序，保证上旧下新顺序。"""
        from dmshoot.storage.models import ChatMessage
        import time as _time
        now = _time.time()
        ts = timestamp or now
        msg = ChatMessage(
            session_id=session_id,
            sender_name=sender_name,
            sender_id=sender_id,
            content=content,
            is_self=is_self,
            is_auto=is_auto,
            persona=persona,
            timestamp=ts,
            message_key=message_key,
        )
        # 维护缓存（按时间排序，保证 oldest first）
        cache = self._msg_cache.get(session_id, [])
        merged = database.deduplicate_messages(cache + [msg])
        merged.sort(key=lambda item: (item.timestamp or 0, item.id or 0))
        # 新消息被已有服务端键或 AI 平台回显命中时，不再重复推送气泡。
        if len(merged) == len(cache):
            self._msg_cache[session_id] = merged
            return
        self._msg_cache[session_id] = merged
        # 推气泡（如果在看这个会话）
        if self._current_session == session_id:
            self.chat.append_message(msg)
        # 增量更新通讯录（不查 DB，只更新文字）
        if not self.contacts.update_one_session(session_id, content, ts, unread_count):
            self.refresh_session(session_id)
