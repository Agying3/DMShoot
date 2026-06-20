"""抖音 SDK 客户端 — 适配器模式隔离 DouYin_Spider

所有对外部 SDK 的直接依赖仅在此文件中，DouyinAdapter 只通过 DouyinClient 接口交互。
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # plugins/douyin → 项目根


class DouyinClient:
    """抖音平台 SDK 封装。内部使用 douyin_sdk / douyin_ws / douyin_im_sync，
    对外暴露简洁接口供 DouyinAdapter 使用。
    """

    def __init__(self, cookie: str, web_protect: str = "", keys: str = ""):
        from dmshoot.utils.douyin_sdk import create_auth
        self._cookie = cookie
        self._auth = create_auth(cookie, web_protect, keys)
        self._ws_receiver = None
        # 会话缓存（send_message_cached 用）
        self._conv_cache: dict[str, tuple] = {}

    # ── 认证 ──

    @property
    def auth(self):
        """原始 DouyinAuth 对象（WS receiver 需要）"""
        return self._auth

    @property
    def uid(self) -> str:
        """当前登录用户 UID"""
        return str(self._auth.get_uid()) if self._auth else ""

    @property
    def ticket(self):
        """ticket 令牌（发消息需要）"""
        return getattr(self._auth, 'ticket', None)

    @property
    def has_ticket(self) -> bool:
        return bool(self.ticket)

    # ── 连接 ──

    def connect(self) -> tuple[bool, str]:
        """验证连接：获取 UID + 昵称。返回 (ok, error_msg)"""
        uid = self._auth.get_uid()
        if not uid:
            return False, "Cookie 已过期"
        return True, ""

    def start_ws_receiver(self):
        """启动 WebSocket 实时消息接收"""
        from dmshoot.utils.douyin_ws import DouyinWSReceiver
        self._ws_receiver = DouyinWSReceiver(self._auth)
        self._ws_receiver.start()

    @property
    def ws_receiver(self):
        """WebSocket 接收器（用于 poll 读取消息）"""
        return self._ws_receiver

    def stop_ws_receiver(self):
        if self._ws_receiver:
            self._ws_receiver.stop()
            self._ws_receiver = None

    # ── 发送 ──

    def send_message(self, peer_uid: int, text: str) -> bool:
        """发送私信。返回是否成功"""
        from dmshoot.utils.douyin_sdk import send_message_cached
        return send_message_cached(self._auth, peer_uid, text, self._conv_cache)

    # ── 同步 ──

    def fetch_history(self) -> list[dict]:
        """同步历史会话列表（返回 dict 列表，非 Message）"""
        from dmshoot.utils.douyin_im_sync import fetch_conversations_sync
        return fetch_conversations_sync(self._cookie)

    def get_cached_messages(self, *args, **kwargs) -> list[dict]:
        """获取缓存中的历史消息（返回 dict 列表，适配器层转换为 ChatMessage）"""
        from dmshoot.utils.douyin_im_sync import get_cached_messages
        return get_cached_messages(*args, **kwargs)
