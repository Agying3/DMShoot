"""适配器基类 — 每个平台adapter继承这个"""

import time
import enum
import threading
from typing import Optional

# ── 条件导入: headless 模式下不依赖 PySide6 ──
try:
    from PySide6.QtCore import QThread as _ThreadBase
    _is_qt_thread = True
except ImportError:
    _is_qt_thread = False

    class _ThreadBase(threading.Thread):
        """纯 Python Thread, 兼容 QThread 的 quit/wait/terminate 接口"""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._thread_running = True

        def isRunning(self) -> bool:
            return self.is_alive()

        def quit(self):
            self._thread_running = False

        def terminate(self):
            pass  # Python Thread 无法强制终止

        def wait(self, timeout_ms: int = 0) -> bool:
            self.join(timeout=timeout_ms / 1000.0)
            return not self.is_alive()

from dmshoot.core.bus import MessageBus, PlatformStatus
from dmshoot.core.message import Message
from dmshoot.core.poller import AdaptivePoller

# 必须用 get_logger 获取 ModuleLogger（支持 success() 等方法）
from dmshoot.utils.console_log import get_logger, raw_title, raw_sep
logger = get_logger(__name__)


class ErrorCategory(enum.Enum):
    """统一错误分类"""
    NETWORK = "network"    # 连接/HTTP/WS 错误（可重试）
    AUTH = "auth"          # Cookie 过期 / ticket 缺失（需重新登录）
    PLATFORM = "platform"   # API 限流 / 平台限制（需降级等待）
    INTERNAL = "internal"  # 代码 bug / 解析错误（需修复）


class BaseAdapter(_ThreadBase):
    """
    所有平台适配器的基类
    GUI 模式: 继承 QThread, 每个平台独立线程运行
    Headless 模式: 继承 threading.Thread, 无 PySide6 依赖
    """

    platform_name: str = "unknown"
    _im_unavailable: bool = False
    _use_adaptive_poll: bool = True  # 自适应轮询,子类可关闭

    def __init__(self, bus: Optional[MessageBus] = None, limiter=None):
        super().__init__()
        self.bus = bus or MessageBus.instance()
        self._limiter = limiter  # 可注入，send_rate_limited 中用
        self._running = False
        self._connected = False
        self._my_name: str = ""
        self._poller = AdaptivePoller()  # 自适应轮询间隔  # 子类 connect() 里填充

    def connect(self) -> bool:
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def send_message(self, session_id: str, text: str) -> bool:
        raise NotImplementedError

    def send_rate_limited(self, session_id: str, text: str) -> bool:
        """带限流保护的消息发送。子类不应覆盖此方法"""
        from dmshoot.core.rate_limiter import get_limiter
        limiter = self._limiter or get_limiter(self.platform_name)
        if not limiter.acquire():
            logger.warning(f"[{self.platform_name}] 发送限流: 超出频率限制")
            return False
        return self.send_message(session_id, text)

    def fetch_sessions(self) -> list[dict]:
        raise NotImplementedError

    def fetch_history(self, session_id: str, limit: int = 20) -> list[Message]:
        raise NotImplementedError

    def _poll_messages(self):
        raise NotImplementedError

    def run(self):
        """QThread入口"""
        self._running = True
        self._set_status(PlatformStatus.CONNECTING, "连接中...")

        if not self.connect():
            if not self._im_unavailable:
                raw_sep()
                raw_title(f"×  {self.platform_name} 连接失败")
            return

        self._connected = True
        name_part = f"{self._my_name} · " if self._my_name else ""
        # 只有抖音需要 ticket；B站/小红书无 ticket 概念，连接成功即可发消息
        if self.platform_name == "douyin":
            has_ticket = getattr(self, '_auth', None) and getattr(self._auth, 'ticket', None)
            status_text = "已连接" if has_ticket else "已连接（缺少 ticket，无法发送）"
        else:
            status_text = "已连接"
        self._set_status(PlatformStatus.ONLINE, f"{name_part}{status_text}")
        logger.success(f"✓  {name_part}{status_text}")
        self.bus.log.emit("INFO", self.platform_name, "适配器启动完成")

        try:
            self._poll_loop()
        except Exception as e:
            logger.exception(f"[{self.platform_name}] 运行异常")
            self._set_status(PlatformStatus.ERROR, str(e))
        finally:
            self.disconnect()
            self._set_status(PlatformStatus.OFFLINE, "已断开")

    def _poll_loop(self):
        """轮询主循环，单个错误不中断。每30s输出心跳日志"""
        import time as _time
        last_health = _time.time()
        while self._running:
            try:
                self._poll_messages()
            except Exception as e:
                logger.error(f"[{self.platform_name}] 轮询异常: {e}")
                _time.sleep(2)
                continue
            # 30s 心跳：确认适配器存活着
            now = _time.time()
            if now - last_health >= 60:
                last_health = now
                logger.debug_category("heartbeat", f"[{self.platform_name}] heartbeat")

    def _set_status(self, status: str, msg: str = ""):
        self.bus.set_platform_status(self.platform_name, status, msg)

    def _on_message(self, msg: Message):
        """在适配器线程只落库一次，再将新消息推送到总线。"""
        try:
            from dmshoot.storage import database
            inserted, unread_count = database.save_platform_message(msg)
        except Exception:
            logger.exception(f"[{self.platform_name}] 消息持久化失败")
            return
        if not inserted:
            return
        if isinstance(msg.raw, dict):
            msg.raw["_unread_count"] = unread_count
        self.bus.emit_message(msg)

    def stop(self):
        """安全停止适配器，不阻塞调用线程"""
        self._running = False
        self._connected = False
        if not self.isRunning():
            return
        self.quit()
        if not self.wait(3000):
            self.terminate()  # 超时强杀
            self.quit()

    def on_error(self, category: ErrorCategory, message: str, exc: Exception = None):
        """统一错误处理钩子。子类可重写以适配平台特定逻辑。
        默认行为: 记录日志 + 向总线报告认证/平台级错误。"""
        if category == ErrorCategory.AUTH:
            logger.warning(f"[{self.platform_name}] 认证错误: {message}")
            self.bus.set_platform_status(self.platform_name, "认证失败", message)
        elif category == ErrorCategory.PLATFORM:
            logger.warning(f"[{self.platform_name}] 平台限制: {message}")
        elif category == ErrorCategory.NETWORK:
            logger.error(f"[{self.platform_name}] 网络错误: {message}")
        else:
            logger.error(f"[{self.platform_name}] 内部错误: {message}", exc_info=bool(exc))


class ReconnectBackoff:
    """自适应退避重连 — 指数增长 + 成功重置"""
    def __init__(self, min_s: float = 1.0, max_s: float = 30.0):
        self._min = min_s
        self._max = max_s
        self._current = min_s

    @property
    def current(self) -> float:
        return self._current

    def fail(self) -> float:
        """记录一次失败，返回下次等待秒数"""
        wait = self._current
        self._current = min(self._current * 2, self._max)
        return wait

    def reset(self):
        """成功后重置退避"""
        self._current = self._min
