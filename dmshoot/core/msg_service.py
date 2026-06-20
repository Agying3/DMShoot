"""消息服务抽象层 — Python / Go 可切换

用法:
    from dmshoot.core.msg_service import MessageService
    svc = MessageService(backend="python")  # 默认
    # 或
    svc = MessageService(backend="go")      # 需要先 build + start Go

    await svc.start()
    await svc.register_platform("douyin", cookie)
    await svc.switch_backend("go")          # 热切换
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class MessageService:
    """统一消息服务门面 — 底层 Python/Go 可热切换"""

    def __init__(self, backend: str = "python", go_bridge=None):
        self._backend = backend
        self._on_message: Optional[Callable] = None
        self._on_send_command: Optional[Callable] = None
        self._go_bridge = go_bridge  # 可注入，避免重复 import

    def _get_go_bridge(self):
        """惰性获取 Go 桥接实例（缓存以避免重复 import）"""
        if self._go_bridge is None:
            from dmshoot.core.go_bridge import get_go_bridge
            self._go_bridge = get_go_bridge()
        return self._go_bridge

    @property
    def backend(self) -> str:
        return self._backend

    async def start(self):
        if self._backend == "go":
            bridge = self._get_go_bridge()
            if not bridge.running:
                bridge.start()
            await bridge.connect_ws(self._on_ws_message, self._on_ws_send_command)

    async def stop(self):
        if self._backend == "go":
            await self._get_go_bridge().disconnect_ws()

    async def switch_backend(self, target: str):
        if target == self._backend:
            return
        logger.info(f"消息后端切换: {self._backend} → {target}")
        await self.stop()
        self._backend = target
        await self.start()

    async def register_platform(self, platform: str, cookie: str, interval_ms: int = 3000):
        if self._backend == "go":
            await self._get_go_bridge().register(platform, cookie, interval_ms)

    async def unregister_platform(self, platform: str):
        if self._backend == "go":
            await self._get_go_bridge().unregister(platform)

    async def send(self, platform: str, session_id: str, content: str) -> bool:
        if self._backend == "go":
            return await self._get_go_bridge().send(platform, session_id, content)
        return False

    def on_message(self, callback: Callable):
        self._on_message = callback

    def on_send_command(self, callback: Callable):
        """注册 send_command 回调 — Go 收到发消息指令后通过 WS 回传"""
        self._on_send_command = callback

    async def _on_ws_message(self, msg: dict):
        """Go 桥接原始消息回调（dict）。TODO: 接入总线前需转为 Message"""
        if self._on_message:
            self._on_message(msg)

    async def _on_ws_send_command(self, data: dict):
        if self._on_send_command:
            self._on_send_command(data)
