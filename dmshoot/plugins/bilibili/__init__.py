"""B站插件"""

from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
from dmshoot.utils.platform_connector import verify_bilibili

PLUGIN_INFO = {
    "id": "bilibili",
    "name": "B站",
    "adapter_cls": BilibiliAdapter,
    "cookie_fields": ["bilibili_sessdata", "bilibili_jct",
                       "bilibili_buvid3", "bilibili_buvid4",
                       "bilibili_dedeuserid", "bilibili_ac_time_value"],
    "login_handler": verify_bilibili,
}
