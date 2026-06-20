"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class SessionRecord:
    """会话记录"""
    id: int = 0
    session_id: str = ""       # 格式: platform:uid
    platform: str = ""         # douyin / bilibili
    peer_name: str = ""        # 对方昵称
    peer_id: str = ""          # 对方ID
    last_message: str = ""     # 最后一条消息摘要
    last_time: float = 0.0     # 最后消息时间戳
    unread_count: int = 0
    is_pinned: bool = False
    is_muted: bool = False
    avatar_url: str = ""

    @property
    def platform_display(self) -> str:
        return {"douyin": "🎵 抖音", "bilibili": "📺 B站", "xiaohongshu": "📕 小红书"}.get(
            self.platform, self.platform
        )


@dataclass(slots=True)
class ChatMessage:
    """聊天消息记录"""
    id: int = 0
    session_id: str = ""
    sender_name: str = ""
    sender_id: str = ""
    content: str = ""
    msg_type: str = "text"
    is_self: bool = False
    is_auto: bool = False      # AI自动回复
    persona: str = ""          # 发送 AI 回复时所用的提示词角色名（如「柁炑」）
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass(slots=True)
class AppConfig:
    """应用配置"""
    # AI
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    system_prompt: str = ""
    prompt_preset: str = "柁炑"
    behavior_preset: str = "默认"

    # 平台开关
    douyin_enabled: bool = False
    bilibili_enabled: bool = False
    xhs_enabled: bool = True
    ks_enabled: bool = False

    # 抖音配置
    douyin_cookie: str = ""
    douyin_web_protect: str = ""   # localStorage __web_protect__
    douyin_keys: str = ""           # localStorage __keys__

    # B站配置  
    bilibili_sessdata: str = ""
    bilibili_jct: str = ""
    bilibili_buvid3: str = ""       # bilibili-api 17.4+ 需要
    bilibili_buvid4: str = ""       # bilibili-api 17.4+ 需要
    bilibili_dedeuserid: str = ""   # bilibili-api 17.4+ 需要
    bilibili_ac_time_value: str = ""  # bilibili-api 17.4+ 需要
    bilibili_auto_monitor: bool = False  # 登录后自动启动监听

    # 小红书配置
    xhs_cookie: str = ""

    # 快手配置
    ks_cookie: str = ""

    # 自动回复
    auto_reply_enabled: bool = True
    reply_delay_min: float = 1.0   # 最小延迟(秒)
    reply_delay_max: float = 3.0   # 最大延迟(秒)
    max_context_rounds: int = 10    # AI上下文轮数

    # 界面
    wallpaper_path: str = ""  # 当前活跃壁纸路径（空=默认）
    wallpaper_gallery: list[str] = field(default_factory=list)  # 已添加的自定义壁纸集合
    debug_log_levels: str = ""  # 调试日志开关 JSON: {"heartbeat": true, "polling": false, ...}
    msg_backend: str = "python"  # 消息处理后端: python / go
