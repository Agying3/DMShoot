"""Go 消息服务 Python 客户端 — 热加载切换

用法:
    from dmshoot.core.go_bridge import GoServiceBridge
    bridge = GoServiceBridge()
    bridge.start()                              # 启动 Go 进程
    await bridge.register("douyin", cookie)     # 注册平台
    await bridge.send("douyin", sess_id, "hi")  # 发送消息
    bridge.stop()                               # 关闭
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
import websockets

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_GO_DIR = _PROJECT_ROOT / "dmshoot-go"
_GO_EXE = _GO_DIR / "msg-service.exe"
_GO_PORT = 9800
_GO_URL = f"http://127.0.0.1:{_GO_PORT}"


class GoServiceBridge:
    """Python 端 Go 服务桥梁 — 管理子进程 + HTTP/WS 通信"""

    def __init__(self, db_path: str = None):
        self._proc: Optional[subprocess.Popen] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._on_message = None
        self._on_send_command = None
        self._db_path = db_path or str(_PROJECT_ROOT / "dmshoot" / "data" / "dmshoot.db")

    # ── 生命周期 ──

    def start(self) -> bool:
        """编译（如需）并启动 Go 子进程"""
        if self._proc and self._proc.poll() is None:
            return True
        exe_path = str(_GO_EXE)
        if not os.path.exists(exe_path):
            logger.info("Go 二进制不存在，尝试编译...")
            if not self._compile():
                return False
        env = os.environ.copy()
        env["DMSHOOT_DB"] = self._db_path
        try:
            self._proc = subprocess.Popen(
                [exe_path, str(_GO_PORT)],
                cwd=str(_GO_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception as e:
            logger.error(f"Go 服务启动失败: {e}")
            return False
        # 等待就绪
        return self._wait_ready()

    def stop(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def _compile(self) -> bool:
        """编译 Go 源码"""
        go = "go"
        try:
            result = subprocess.run(
                [go, "build", "-o", str(_GO_EXE), "."],
                cwd=str(_GO_DIR),
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.error(f"Go 编译失败:\n{result.stderr}")
                return False
            return True
        except FileNotFoundError:
            logger.error("未找到 Go 编译器，请安装: https://go.dev/dl/")
            return False
        except Exception as e:
            logger.error(f"Go 编译异常: {e}")
            return False

    def _wait_ready(self, timeout: float = 15.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = httpx.get(f"{_GO_URL}/api/health", timeout=2)
                if resp.status_code == 200:
                    logger.info("Go 消息服务已就绪")
                    return True
            except Exception:
                time.sleep(0.5)
        logger.error("Go 服务启动超时")
        return False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── HTTP API ──

    async def _ensure_client(self):
        if not self._client:
            self._client = httpx.AsyncClient(base_url=_GO_URL, timeout=30)

    async def register(self, platform: str, cookie: str, interval_ms: int = 3000) -> bool:
        await self._ensure_client()
        try:
            resp = await self._client.post("/api/register", json={
                "platform": platform, "cookie": cookie, "interval_ms": interval_ms,
            })
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Go 注册 {platform} 失败: {e}")
            return False

    async def unregister(self, platform: str) -> bool:
        await self._ensure_client()
        try:
            resp = await self._client.post("/api/unregister", json={"platform": platform})
            return resp.status_code == 200
        except Exception:
            return False

    async def send(self, platform: str, session_id: str, content: str) -> bool:
        await self._ensure_client()
        try:
            resp = await self._client.post("/api/send", json={
                "platform": platform, "session_id": session_id, "content": content,
            })
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Go 发送失败: {e}")
            return False

    async def status(self) -> dict:
        await self._ensure_client()
        try:
            resp = await self._client.get("/api/status")
            return resp.json()
        except Exception:
            return {"workers": 0, "platforms": []}

    # ── WebSocket 实时推送 ──

    def start_ws_sync(self, on_send_command=None):
        """同步启动 WebSocket 连接（适用于 Qt/非 async 上下文）
        
        在后台线程中运行 asyncio 事件循环，连接 Go WS 并接收消息。
        """
        self._on_send_command = on_send_command
        self._ws_thread = threading.Thread(target=self._ws_thread_loop, daemon=True)
        self._ws_thread.start()
        logger.info("Go WS 后台线程已启动")

    async def connect_ws(self, on_message, on_send_command=None):
        self._on_message = on_message
        self._on_send_command = on_send_command
        self._ws_task = asyncio.create_task(self._ws_loop())

    def _ws_thread_loop(self):
        """后台线程的事件循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_loop())
        except Exception as e:
            logger.error(f"Go WS 后台线程异常: {e}")
        finally:
            loop.close()

    async def _ws_loop(self):
        while self.running:
            try:
                async with websockets.connect(f"ws://127.0.0.1:{_GO_PORT}/ws") as ws:
                    self._ws = ws
                    logger.info("Go WebSocket 已连接")
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            msg_type = msg.get("type", "")
                            # 路由：按 type 分发到不同回调
                            if msg_type == "send_command" and self._on_send_command:
                                self._on_send_command(msg.get("data", {}))
                            elif self._on_message:
                                self._on_message(msg)
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                logger.warning(f"Go WS 断开: {e}, 3s 后重连")
                self._ws = None
                await asyncio.sleep(3)

    async def disconnect_ws(self):
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        await self.disconnect_ws()
        self.stop()


# ── 全局单例 ──
_bridge: Optional[GoServiceBridge] = None


def get_go_bridge() -> GoServiceBridge:
    global _bridge
    if _bridge is None:
        _bridge = GoServiceBridge()
    return _bridge
