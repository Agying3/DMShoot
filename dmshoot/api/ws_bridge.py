"""WebSocket 桥接 —— 将 MessageBus Signal 映射到 WebSocket 事件推送"""

import asyncio
import json
import logging
import time
from typing import Optional
from fastapi import WebSocket

from dmshoot.core.bus import MessageBus, PlatformStatus
from dmshoot.api.models import (
    AdapterStatusItem, AdapterSnapshot, PerfSnapshotResponse,
)

logger = logging.getLogger("dmshoot.api.ws_bridge")

HEARTBEAT_INTERVAL = 5   # 心跳间隔（秒）
PERF_INTERVAL = 1        # 性能数据推送间隔（秒）


class WSBridge:
    """管理 WebSocket 连接，桥接 MessageBus → WS 推送"""

    def __init__(self):
        self._ws: Optional[WebSocket] = None
        self._bus: Optional[MessageBus] = None
        self._closing = False

    # ── 生命周期 ──

    async def serve(self, ws: WebSocket, bus: MessageBus):
        """启动 WebSocket 服务，阻塞直到断开"""
        await ws.accept()
        self._ws = ws
        self._bus = bus
        self._closing = False
        logger.info("WebSocket 客户端已连接")

        # 连接 bus 信号
        self._wire_signals()

        # 启动心跳
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        perf_task = asyncio.create_task(self._perf_loop())

        try:
            while not self._closing:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=1)
                    await self._handle_client(raw)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        finally:
            self._closing = True
            heartbeat_task.cancel()
            perf_task.cancel()
            self._unwire_signals()
            self._ws = None
            self._bus = None
            logger.info("WebSocket 客户端已断开")

    # ── 信号绑定 ──

    def _wire_signals(self):
        if not self._bus:
            return
        self._bus.new_message.connect(self._on_message)
        self._bus.platform_status.connect(self._on_platform_status)
        self._bus.log.connect(self._on_log)

    def _unwire_signals(self):
        if not self._bus:
            return
        try:
            self._bus.new_message.disconnect(self._on_message)
        except Exception:
            pass
        try:
            self._bus.platform_status.disconnect(self._on_platform_status)
        except Exception:
            pass
        try:
            self._bus.log.disconnect(self._on_log)
        except Exception:
            pass

    # ── 推送事件 ──

    async def _send(self, event: str, data: dict):
        if not self._ws:
            return
        try:
            await self._ws.send_text(json.dumps({
                "event": event,
                "ts": time.time(),
                **data,
            }, ensure_ascii=False))
        except Exception:
            pass

    async def push_qr_code(self, platform: str, b64: str):
        await self._send("qr_code", {"platform": platform, "b64": b64})

    async def push_login_ok(self, platform: str):
        await self._send("login_ok", {"platform": platform})

    async def push_login_fail(self, platform: str, reason: str):
        await self._send("login_fail", {"platform": platform, "reason": reason})

    async def push_ai_stream(self, session_id: str, chunk: str, done: bool):
        await self._send("ai_stream", {
            "session_id": session_id, "chunk": chunk, "done": done,
        })

    async def push_system_error(self, error_type: str, detail: str):
        await self._send("system_error", {"type": error_type, "detail": detail})

    # ── Signal 回调 ──

    def _on_message(self, msg):
        """msg: ChatMessage 对象"""
        asyncio.ensure_future(self._send("new_message", {
            "platform": msg.platform if hasattr(msg, 'platform') else "",
            "session_id": msg.session_id,
            "sender_id": str(getattr(msg, 'sender_id', '')),
            "sender_name": msg.sender_name or "",
            "content": msg.content or "",
            "msg_type": getattr(msg, 'msg_type', 'text'),
            "timestamp": getattr(msg, 'timestamp', time.time()),
            "is_self": bool(getattr(msg, 'is_self', False)),
        }))

    def _on_platform_status(self, platform: str, status: str, detail: str = ""):
        asyncio.ensure_future(self._send("platform_status", {
            "platform": platform,
            "status": status,
            "detail": detail,
        }))

    def _on_log(self, level: str, module: str, message: str):
        asyncio.ensure_future(self._send("log", {
            "level": level, "module": module, "message": message,
        }))

    # ── 心跳 & 性能 ──

    async def _heartbeat_loop(self):
        while not self._closing:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await self._send("heartbeat", {"ts": time.time()})

    async def _perf_loop(self):
        while not self._closing:
            await asyncio.sleep(PERF_INTERVAL)
            try:
                from dmshoot.core.perf_monitor import get_monitor
                mon = get_monitor()
                snapshot = mon.snapshot()
                await self._send("perf", {
                    "cpu": snapshot.get("cpu_percent", 0),
                    "memory": snapshot.get("memory_mb", 0),
                    "msg_rate": snapshot.get("msg_rate", 0),
                    "breakdown": snapshot.get("event_breakdown", {}),
                })
            except Exception:
                pass

    # ── 客户端消息处理 ──

    async def _handle_client(self, raw: str):
        try:
            data = json.loads(raw)
            action = data.get("action")
            if action == "ping":
                await self._send("pong", {})
            # 可扩展其他 action
        except json.JSONDecodeError:
            pass


# 全局单例
_bridge: Optional[WSBridge] = None


def get_bridge() -> WSBridge:
    global _bridge
    if _bridge is None:
        _bridge = WSBridge()
    return _bridge
