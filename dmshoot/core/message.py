"""统一消息模型 — 所有平台的消息都套这个壳"""

from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class Message:
    """跨平台统一消息"""
    platform: str           # "douyin" | "bilibili" | "xiaohongshu"
    msg_type: str           # "text" | "image" | "voice" | "video" | "system"
    sender_id: str          # 发送者唯一ID
    sender_name: str        # 发送者昵称
    session_id: str         # 会话ID (platform:uid)
    content: str            # 文本内容 / 媒体URL描述
    media_url: str = ""     # 图片/视频等附件URL
    raw: dict = field(default_factory=dict)
    timestamp: float = 0.0
    is_auto_reply: bool = False   # 是否由AI自动回复
    is_self: bool = False         # 是否是自己发出的
    seq_id: int = 0               # 消息序号

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = datetime.now().timestamp()

    @classmethod
    def from_douyin(cls, raw_msg: dict) -> "Message":
        """从抖音原始消息转换"""
        content_type = raw_msg.get("msg_type", 1)
        type_map = {1: "text", 2: "image", 3: "voice", 4: "video"}
        return cls(
            platform="douyin",
            msg_type=type_map.get(content_type, "text"),
            sender_id=str(raw_msg.get("from_user_id", "")),
            sender_name=raw_msg.get("from_nickname", "未知"),
            session_id=f"douyin:{raw_msg.get('conversation_id', '')}",
            content=raw_msg.get("text", ""),
            media_url=raw_msg.get("media_url", ""),
            raw=raw_msg,
            seq_id=raw_msg.get("msg_id", 0),
        )

    @classmethod
    def from_bilibili(cls, raw_msg: dict) -> "Message":
        """从B站原始消息转换"""
        msg_type = raw_msg.get("msg_type", 1)
        type_map = {1: "text", 2: "image", 6: "image"}
        return cls(
            platform="bilibili",
            msg_type=type_map.get(msg_type, "text"),
            sender_id=str(raw_msg.get("sender_uid", "")),
            sender_name=raw_msg.get("sender_name", "未知"),
            session_id=f"bilibili:{raw_msg.get('talker_id', '')}",
            content=raw_msg.get("content", ""),
            media_url=raw_msg.get("image_url", ""),
            raw=raw_msg,
            seq_id=raw_msg.get("msg_seqno", 0),
        )

    @classmethod
    def system_message(cls, platform: str, content: str) -> "Message":
        """创建系统消息"""
        return cls(
            platform=platform,
            msg_type="system",
            sender_id="SYSTEM",
            sender_name="系统",
            session_id=f"{platform}:SYSTEM",
            content=content,
        )

    def to_dict(self) -> dict:
        """序列化为 dict，供跨进程/日志/Go桥接使用"""
        return {
            "platform": self.platform,
            "msg_type": self.msg_type,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "session_id": self.session_id,
            "content": self.content,
            "media_url": self.media_url,
            "timestamp": self.timestamp,
            "is_auto_reply": self.is_auto_reply,
            "is_self": self.is_self,
            "seq_id": self.seq_id,
        }
