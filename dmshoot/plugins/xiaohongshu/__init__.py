"""小红书插件 — Web私信API不可用 (2026-06-14)，保留登录入口"""
from dmshoot.plugins.xiaohongshu.adapter import XHSAdapter

PLUGIN_INFO = {
    "id": "xiaohongshu",
    "name": "小红书",
    "adapter_cls": XHSAdapter,
    "cookie_fields": ["xhs_cookie"],
    "login_handler": None,
}
