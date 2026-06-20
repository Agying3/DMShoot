"""消息总线 — 所有模块通过信号槽通信"""

import threading
from typing import Callable, Optional
from PySide6.QtCore import QObject, Signal

from dmshoot.core.message import Message


class PlatformStatus:
    """平台连接状态"""
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    ERROR = "error"


class MessageBus(QObject):
    """
    全局事件中枢
    GUI 和各 Adapter 只跟 Bus 说话，互相不直接耦合
    """

    # 有新消息到达
    new_message = Signal(Message)

    # 需要向平台发送回复
    send_reply = Signal(str, str, str)  # platform, session_id, text

    # 平台连接状态变化
    platform_status = Signal(str, str, str)  # platform, status, msg

    # 日志输出
    log = Signal(str, str, str)  # level, platform, message

    # AI回复请求
    ai_request = Signal(Message)

    # AI回复结果
    ai_response = Signal(str, str, str)  # session_id, reply_text, model

    _instance: Optional["MessageBus"] = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "MessageBus":
        """线程安全单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def emit_message(self, msg: Message):
        """有新消息时调用"""
        self.log.emit("INFO", msg.platform, f"[{msg.sender_name}] {msg.content[:50]}")
        self.new_message.emit(msg)

    def request_reply(self, platform: str, session_id: str, text: str):
        """请求向平台发送回复"""
        self.send_reply.emit(platform, session_id, text)

    def set_platform_status(self, platform: str, status: str, msg: str = ""):
        """更新平台状态"""
        self.platform_status.emit(platform, status, msg)
        self.log.emit("INFO", platform, f"状态变更: {status} {msg}")
