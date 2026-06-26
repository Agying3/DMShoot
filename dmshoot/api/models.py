"""Pydantic 数据模型 —— API 请求/响应的类型定义"""

from pydantic import BaseModel, Field
from typing import Optional, Any


# ── 通用 ──

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ── 适配器 ──

class AdapterStartRequest(BaseModel):
    platform: str = Field(..., pattern="^(douyin|bilibili|kuaishou|xiaohongshu)$")
    auto_reply: bool = True


class AdapterStopRequest(BaseModel):
    platform: str = Field(..., pattern="^(douyin|bilibili|kuaishou|xiaohongshu)$")


class AdapterStatusItem(BaseModel):
    connected: bool
    status: str     # "online"|"offline"|"connecting"|"error"
    name: Optional[str] = None
    error: Optional[str] = None
    session_count: int = 0


class StatusResponse(BaseModel):
    platforms: dict[str, AdapterStatusItem]


# ── 登录 ──

class LoginScanRequest(BaseModel):
    platform: str = Field(..., pattern="^(douyin|bilibili|kuaishou|xiaohongshu)$")


# ── 消息 ──

class MessageSendRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=500)


class SessionItem(BaseModel):
    session_id: str
    platform: str
    peer_name: str
    peer_id: str
    avatar_url: str = ""
    last_message: str = ""
    last_time: float = 0
    unread: int = 0
    is_online: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionItem]


class MessageItem(BaseModel):
    msg_id: int
    sender_id: str
    sender_name: str
    content: str
    msg_type: str = "text"
    timestamp: float
    is_self: bool = False


class MessageListResponse(BaseModel):
    session_id: str
    peer_name: str
    messages: list[MessageItem]
    has_more: bool = False


# ── AI ──

class AIGenerateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    persona: Optional[str] = None


# ── 配置 ──

class ConfigUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    auto_reply_enabled: Optional[bool] = None
    reply_delay_min: Optional[float] = Field(None, ge=0.1, le=60)
    reply_delay_max: Optional[float] = Field(None, ge=0.1, le=120)
    max_context_rounds: Optional[int] = Field(None, ge=1, le=50)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=8192)
    theme: Optional[str] = Field(None, pattern="^(dark|light)$")
    rate_douyin: Optional[int] = Field(None, ge=1, le=60)
    rate_bilibili: Optional[int] = Field(None, ge=1, le=60)


class ConfigResponse(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    auto_reply_enabled: bool = True
    reply_delay_min: float = 1.0
    reply_delay_max: float = 3.0
    max_context_rounds: int = 10
    temperature: float = 0.7
    max_tokens: int = 1024
    theme: str = "dark"
    rate_douyin: int = 3
    rate_bilibili: int = 3


# ── 提示词 ──

class PromptUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    type: str = Field(..., pattern="^(role|behavior)$")


class PromptListResponse(BaseModel):
    presets: dict[str, str]
    active: str = ""
    behavior_presets: dict[str, str]
    active_behavior: str = ""


# ── 性能 ──

class AdapterSnapshot(BaseModel):
    running: bool
    queue_size: int = 0


class PerfSnapshotResponse(BaseModel):
    cpu_percent: float
    memory_mb: float
    msg_rate: float
    adapter_status: dict[str, AdapterSnapshot]
    event_breakdown: dict[str, int]
