"""适配器管理器 — 从 MainWindow 提取的适配器生命周期控制"""

import os
import threading

from PySide6.QtCore import QTimer

from dmshoot.storage import database
from dmshoot.utils.console_log import get_logger, raw_header

logger = get_logger("dmshoot.adapter_mgr")

# ── 平台分类常量 ──
_IM_UNAVAILABLE_PLATFORMS = frozenset({"kuaishou", "xiaohongshu"})

_PLATFORM_NAMES = {"douyin": "抖音", "bilibili": "B站", "kuaishou": "快手"}


class AdapterManager:
    """MainWindow 中适配器生命周期管理的提取。
    依赖通过构造函数注入（非 QObject）。"""

    def __init__(self, config, plugins, bus, adapters: dict,
                 page_login, page_home, sidebar, monitor):
        self._config = config
        self._plugins = plugins
        self._bus = bus
        self._adapters = adapters      # MainWindow._adapters 的引用
        self._page_login = page_login
        self._page_home = page_home
        self._sidebar = sidebar
        self._monitor = monitor

    def _refresh_config(self):
        """从 DB 原地刷新共享 AppConfig，避免旧对象后续全量保存覆盖新 cookie。"""
        latest = database.load_config()
        for field_name in type(self._config).__dataclass_fields__:
            setattr(self._config, field_name, getattr(latest, field_name))
        return self._config

    # ── 公共入口 ──

    def start_from_ui(self, platform: str):
        """用户点击启动 — 未登录则拒绝"""
        self._refresh_config()
        has_cookie = {
            "douyin": self._config.douyin_cookie,
            "bilibili": self._config.bilibili_sessdata,
            "xiaohongshu": self._config.xhs_cookie,
            "kuaishou": self._config.ks_cookie,
        }.get(platform, "")
        if not has_cookie:
            name = _PLATFORM_NAMES.get(platform, platform)
            logger.warning(f"{name} 未登录，无法启动监听")
            return
        self._start(platform)

    def stop_from_ui(self, platform: str):
        """用户点击停止按钮 — 后台线程停止，不阻塞 UI"""
        adapter = self._adapters.pop(platform, None)
        if adapter and hasattr(adapter, "stop"):
            threading.Thread(target=adapter.stop, daemon=True).start()
        name = _PLATFORM_NAMES.get(platform, platform)
        if self._page_login:
            self._page_login.set_monitor_running(platform, False)
        self._bus.log.emit("INFO", name, "监听已停止")
        logger.warning(f"{name} 监听已停止")

    def clear_platform(self, platform: str):
        """清理 cookie：停适配器，清 DB 会话，清首页，删状态文件"""
        self.stop_from_ui(platform)
        database.delete_sessions(platform)
        if self._sidebar:
            self._sidebar.update_status(platform, "✕")
        self._bus.set_platform_status(platform, "离线", "")
        if self._page_home:
            self._page_home._msg_cache.clear()
            self._page_home._load_contacts()
        if self._page_login:
            self._page_login.on_disconnected(platform)
        # 删除状态文件（_replied 去重集、cookie 兜底文件等）
        state_files = {
            "douyin": ["data/douyin_state.json"],
            "bilibili": ["data/bilibili_state.json"],
            "kuaishou": ["data/kuaishou_state.json", "data/kuaishou_cookie.json", "data/ks_cookie_tmp.json"],
        }
        for fname in state_files.get(platform, []):
            try:
                path = os.path.join(os.path.dirname(__file__), "..", fname)
                os.remove(path)
            except FileNotFoundError:
                pass
            except Exception:
                pass
        name = _PLATFORM_NAMES.get(platform, platform)
        logger.warning(f"{name} Cookie 已清理，会话/消息/缓存已删除")

    def on_auto_monitor_toggle(self, checked: bool):
        cfg = self._refresh_config()
        cfg.bilibili_auto_monitor = checked
        database.update_config_field("bilibili_auto_monitor", checked)

    def stop_all(self):
        """关闭时停止所有适配器"""
        for name, adapter in list(self._adapters.items()):
            if hasattr(adapter, "stop"):
                adapter.stop()
            del self._adapters[name]

    # ── 内部 ──

    def _start(self, platform: str):
        """启动适配器。已启动则跳过。"""
        if platform in self._adapters:
            return
        try:
            plugin = self._plugins.get(platform)
            if not plugin:
                return
            name = plugin.name
            # 在主线程打印启动头，保证日志顺序
            raw_header(f"{name} 监听启动")
            adapter = plugin.create_adapter(self._bus, self._config)
            # 先登记再启动，避免重复点击或回调创建两个适配器。
            self._adapters[platform] = adapter
            try:
                adapter.start()
            except Exception:
                self._adapters.pop(platform, None)
                raise
            logger.success(f"{name} 监听已启动")
            self._bus.log.emit("INFO", name, "私信监听已启动")
            if platform in _IM_UNAVAILABLE_PLATFORMS:
                self._bus.log.emit("WARN", name,
                    "⚠️ Web 端不支持私信收发 — 详见右侧聊天区域显示的逆向日志")
            if self._monitor:
                self._monitor.show()
            if self._page_login:
                self._page_login.set_monitor_running(platform, True)
            if self._page_home:
                self._page_home._load_contacts()
                QTimer.singleShot(5000, lambda: self._page_home._load_contacts())
        except Exception as e:
            import traceback
            logger.error(f"[{platform}] 适配器启动失败: {e}\n{traceback.format_exc()}")
