"""DMShoot 无头后端入口 —— FastAPI + WebSocket 服务器

供 Godot / Electron / 其他前端通过 HTTP + WebSocket 调用。
独立于 PySide6，不导入任何 GUI 模块。
"""

import sys
import asyncio
import logging
import threading
from pathlib import Path

# ── 路径初始化 ──
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%m-%d %H:%M:%S",
)
logger = logging.getLogger("dmshoot.headless")

# ── 数据库 ──
from dmshoot.storage.database import init_database, load_config
from dmshoot.storage import database as db

# ── 核心 ──
from dmshoot.core.bus import MessageBus
from dmshoot.plugins.manager import PluginManager


class HeadlessAdapterManager:
    """无 GUI 的适配器管理器。不依赖 PySide6，直接管理适配器生命周期。"""

    PLATFORM_NAMES = {
        "douyin": "抖音", "bilibili": "B站",
        "kuaishou": "快手", "xiaohongshu": "小红书",
    }

    def __init__(self, config, plugins, bus):
        self._config = config
        self._plugins = plugins
        self._bus = bus
        self._adapters: dict = {}

    @property
    def adapters(self):
        return self._adapters

    def start(self, platform: str):
        """启动适配器"""
        if platform in self._adapters:
            return
        has_cookie = {
            "douyin": self._config.douyin_cookie,
            "bilibili": self._config.bilibili_sessdata,
            "kuaishou": self._config.ks_cookie,
        }.get(platform, "")
        if not has_cookie:
            logger.warning(f"{platform} 未登录，跳过启动")
            return

        plugin = self._plugins.get(platform)
        if not plugin:
            logger.warning(f"插件不存在: {platform}")
            return

        name = plugin.name
        logger.info(f"{name} 监听启动")
        adapter = plugin.create_adapter(self._bus, self._config)
        adapter.start()
        self._adapters[platform] = adapter
        logger.info(f"{name} 监听已启动")

    def stop(self, platform: str):
        """停止适配器"""
        adapter = self._adapters.pop(platform, None)
        if adapter and hasattr(adapter, "stop"):
            threading.Thread(target=adapter.stop, daemon=True).start()
        name = self.PLATFORM_NAMES.get(platform, platform)
        logger.warning(f"{name} 监听已停止")

    def clear(self, platform: str):
        """清理平台数据"""
        self.stop(platform)
        db.delete_sessions(platform)
        logger.warning(f"{platform} Cookie 已清理")


async def main():
    """启动 HTTP/WebSocket 服务器"""
    import uvicorn
    from fastapi import FastAPI, WebSocket
    from fastapi.middleware.cors import CORSMiddleware
    from dmshoot.api.routes import router, init as routes_init
    from dmshoot.api.ws_bridge import get_bridge

    # ── 初始化核心组件 ──
    logger.info("初始化数据库...")
    init_database()
    config = load_config()

    # AI 初始化
    try:
        from dmshoot.ai.backend import init_ai
        init_ai(config)
        logger.info("AI 已初始化")
    except Exception as e:
        logger.warning(f"AI 初始化跳过: {e}")

    # 插件
    logger.info("加载插件...")
    plugins = PluginManager()
    logger.info(f"已加载 {len(plugins.list())} 个插件")

    # MessageBus
    bus = MessageBus.instance()

    # Headless Adapter Manager
    adapter_mgr = HeadlessAdapterManager(config, plugins, bus)

    # 注入到 routes
    routes_init(adapter_mgr, config)

    # ── 创建 FastAPI App ──
    app = FastAPI(title="DMShoot Backend", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    # ── WebSocket 端点 ──
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        bridge = get_bridge()
        await bridge.serve(ws, bus)

    logger.info("=" * 50)
    logger.info("DMShoot 后端已启动 → http://127.0.0.1:9876")
    logger.info("WebSocket → ws://127.0.0.1:9876/ws")
    logger.info("=" * 50)

    config_uv = uvicorn.Config(app, host="127.0.0.1", port=9876, log_level="info")
    server = uvicorn.Server(config_uv)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
