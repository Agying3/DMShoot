"""消息总线 — 所有模块通过信号槽通信

GUI 模式: 使用 Qt Signal (线程安全, 跨线程自动队列化)
Headless 模式: 使用纯 Python Signal (无 PySide6 依赖)
"""

import threading
import logging
from typing import Callable, Optional, Any

from dmshoot.core.message import Message

logger = logging.getLogger("dmshoot.core.bus")

# ── 检测是否可用 Qt Signal ──
try:
    from PySide6.QtCore import QObject, Signal as QtSignal
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


# ── 纯 Python Signal（无 Qt 依赖）─────────────────────────────

class _PySignal:
    def __init__(self, *arg_types):
        self._slots: list[Callable] = []
        self._arg_types = arg_types

    def connect(self, slot: Callable) -> None:
        if slot not in self._slots:
            self._slots.append(slot)

    def disconnect(self, slot: Callable) -> None:
        if slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args) -> None:
        for slot in self._slots:
            try:
                slot(*args)
            except Exception:
                logger.exception("Signal slot error")

    def disconnect_all(self) -> None:
        self._slots.clear()


# ── 平台状态枚举 ──────────────────────────────────────────────

class PlatformStatus:
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    ERROR = "error"


# ── 实现类（按是否有 Qt 分两套）───────────────────────────────

if _HAS_QT:

    class _QtMessageBus(QObject):
        """GUI 模式：Qt Signal (类级定义，线程安全)"""
        new_message = QtSignal(Message)
        send_reply = QtSignal(str, str, str)
        platform_status = QtSignal(str, str, str)
        log = QtSignal(str, str, str)
        ai_request = QtSignal(Message)
        ai_response = QtSignal(str, str, str)
        session_updated = QtSignal(str)

        _instance: Optional["_QtMessageBus"] = None
        _lock = threading.Lock()

        @classmethod
        def instance(cls) -> "_QtMessageBus":
            if cls._instance is None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = cls()
            return cls._instance

        def emit_message(self, msg: Message):
            self.log.emit("INFO", msg.platform, f"[{msg.sender_name}] {msg.content[:50]}")
            self.new_message.emit(msg)

        def request_reply(self, platform: str, session_id: str, text: str):
            self.send_reply.emit(platform, session_id, text)

        def set_platform_status(self, platform: str, status: str, msg: str = ""):
            self.platform_status.emit(platform, status, msg)
            self.log.emit("INFO", platform, f"状态变更: {status} {msg}")

        def notify_session_updated(self, session_id: str):
            self.session_updated.emit(session_id)

    MessageBus = _QtMessageBus

else:

    class _PyMessageBus:
        new_message: _PySignal
        send_reply: _PySignal
        platform_status: _PySignal
        log: _PySignal
        ai_request: _PySignal
        ai_response: _PySignal
        session_updated: _PySignal

        _instance: Optional["_PyMessageBus"] = None
        _lock = threading.Lock()

        def __init__(self):
            self.new_message = _PySignal(Message)
            self.send_reply = _PySignal(str, str, str)
            self.platform_status = _PySignal(str, str, str)
            self.log = _PySignal(str, str, str)
            self.ai_request = _PySignal(Message)
            self.ai_response = _PySignal(str, str, str)
            self.session_updated = _PySignal(str)

        @classmethod
        def instance(cls) -> "_PyMessageBus":
            if cls._instance is None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = cls()
            return cls._instance

        def emit_message(self, msg: Message):
            self.log.emit("INFO", msg.platform, f"[{msg.sender_name}] {msg.content[:50]}")
            self.new_message.emit(msg)

        def request_reply(self, platform: str, session_id: str, text: str):
            self.send_reply.emit(platform, session_id, text)

        def set_platform_status(self, platform: str, status: str, msg: str = ""):
            self.platform_status.emit(platform, status, msg)
            self.log.emit("INFO", platform, f"状态变更: {status} {msg}")

        def notify_session_updated(self, session_id: str):
            self.session_updated.emit(session_id)

    MessageBus = _PyMessageBus
