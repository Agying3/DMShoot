"""插件管理器——动态发现和加载平台插件"""

import importlib
from pathlib import Path
from typing import Optional, List


class PluginInfo:
    def __init__(self, id: str, name: str, adapter_cls, cookie_fields: List[str],
                 login_handler=None):
        self.id = id
        self.name = name
        self.adapter_cls = adapter_cls      # BaseAdapter 子类
        self.cookie_fields = cookie_fields   # config 里对应的字段名
        self.login_handler = login_handler    # 登录验证函数

    def create_adapter(self, bus, config: object):
        """用配置创建适配器实例"""
        kwargs = {}
        for f in self.cookie_fields:
            kwargs[f] = getattr(config, f, "")
        return self.adapter_cls(bus=bus, **kwargs)


class PluginManager:
    def __init__(self):
        self._plugins: dict[str, PluginInfo] = {}
        self._discover()

    def _discover(self):
        plugins_dir = Path(__file__).parent
        for d in sorted(plugins_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
                continue
            try:
                mod = importlib.import_module(f"dmshoot.plugins.{d.name}")
                if hasattr(mod, "PLUGIN_INFO"):
                    info_dict = mod.PLUGIN_INFO
                    info = PluginInfo(
                        id=info_dict["id"],
                        name=info_dict["name"],
                        adapter_cls=info_dict["adapter_cls"],
                        cookie_fields=info_dict.get("cookie_fields", []),
                        login_handler=info_dict.get("login_handler"),
                    )
                    self._plugins[info.id] = info
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"插件 {d.name} 加载失败: {e}")

    def list(self) -> List[PluginInfo]:
        return list(self._plugins.values())

    def get(self, platform: str) -> Optional[PluginInfo]:
        return self._plugins.get(platform)

    @property
    def platform_ids(self) -> List[str]:
        return list(self._plugins.keys())
