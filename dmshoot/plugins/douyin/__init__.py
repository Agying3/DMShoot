"""抖音插件"""

from dmshoot.plugins.douyin.adapter import DouyinAdapter
from dmshoot.utils.platform_connector import verify_douyin

PLUGIN_INFO = {
    "id": "douyin",
    "name": "抖音",
    "adapter_cls": DouyinAdapter,
    "cookie_fields": ["douyin_cookie", "douyin_web_protect", "douyin_keys"],
    "login_handler": verify_douyin,
}
