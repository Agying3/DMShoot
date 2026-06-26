"""DMShoot 无头后端入口 —— FastAPI + WebSocket 服务器

供 Godot / Electron / 其他前端通过 HTTP + WebSocket 调用。
与现有 PySide6 GUI 完全解耦，可并行运行。
"""

import sys
import os
import asyncio
import logging
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

# ── 核心组件 ──
from dmshoot.core.bus import get_bus
from dmshoot.plugins.manager import PluginManager
from dmshoot.core.adapter_manager import AdapterManager
from dmshoot.gui.auth_controller import AuthController
from dmshoot.ai.backend import init_ai


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

    logger.info("初始化 AI...")
    init_ai(config)

    logger.info("加载插件...")
    plugins = PluginManager()

    logger.info("初始化 MessageBus...")
    bus = get_bus()

    # AdapterManager & AuthController 需要一些 GUI 类的 mock
    # 当前方案：复用 PySide6 模块的副作用是最小的
    adapters: dict = {}
    adapter_mgr = AdapterManager(config, plugins, bus, adapters, None, None, None, None)
    auth_ctrl = AuthController(config, plugins, bus, None, None, None, adapter_mgr)

    # 注入到 routes
    routes_init(adapter_mgr, auth_ctrl, config)

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

    # ── 启动服务器 ──
    config_uv = uvicorn.Config(app, host="127.0.0.1", port=9876, log_level="info")
    server = uvicorn.Server(config_uv)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
