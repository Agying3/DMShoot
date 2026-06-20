"""快手 (Kuaishou) 私信插件"""

from dmshoot.plugins.kuaishou.adapter import KuaishouAdapter, kuaishou_login

PLUGIN_INFO = {
    "id": "kuaishou",
    "name": "快手",
    "adapter_cls": KuaishouAdapter,
    "cookie_fields": ["ks_cookie"],
    "login_handler": None,  # 使用适配器自身的 connect() 验证
}

__all__ = ["KuaishouAdapter", "kuaishou_login", "PLUGIN_INFO"]
