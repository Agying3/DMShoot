"""彩色终端日志 — Rich 风格，参考 QQBOT

用法:
    from dmshoot.utils.console_log import get_logger
    logger = get_logger(__name__)
    logger.info("连接成功")
    logger.success("消息已发送")          # ✅ 绿色
    logger.warning("重试中...")            # ⚠️ 黄色
    logger.error("发送失败")              # ❌ 红色
    logger.ai_thinking("用户可能想问...") # 💭 青色
    logger.ai_msg("好的，我来帮你...")     # 💬 绿色
    logger.recv("抖音", "造化众生", "你好") # 📩 品红
"""

import logging
import sys
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Windows: 强制 UTF-8 输出（Rich emoji 需要）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Rich Console ──
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Rich 主题：对齐 QQBOT loguru 风格
_RICH_THEME = Theme({
    "time": "green",
    "level.debug": "dim",
    "level.info": "white",
    "level.success": "bold green",
    "level.warning": "bold yellow",
    "level.error": "bold red",
    "level.thinking": "bold cyan",
    "module": "cyan",
    "msg.content": "green",
    "recv.platform": "magenta",
})

_console = Console(theme=_RICH_THEME, highlight=False)

# ── 自定义日志级别 ──
SUCCESS = 25
THINKING = 21
logging.addLevelName(SUCCESS, "SUCCESS")
logging.addLevelName(THINKING, "THINKING")


class ColoredFormatter(logging.Formatter):
    """Rich 风格格式化器，含 Unicode 符号和颜色"""

    LEVEL_STYLES = {
        "DEBUG":    "level.debug",
        "INFO":     "level.info",
        "SUCCESS":  "level.success",
        "WARNING":  "level.warning",
        "ERROR":    "level.error",
        "THINKING": "level.thinking",
    }

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.fromtimestamp(record.created)
        ts = now.strftime("%m-%d %H:%M:%S")
        level = record.levelname
        style = self.LEVEL_STYLES.get(level, "level.info")

        # 特殊处理：RECV 和 AI MSG 不经过标准 logging 级别
        recv_data = getattr(record, "_recv_data", None)
        thinking = getattr(record, "_thinking", False)

        if recv_data:
            platform, sender, content = recv_data
            return f"[time]{ts}[/time] [recv.platform][{platform}][/recv.platform] [dim]{sender}:[/dim] {content}"

        if thinking:
            return f"[time]{ts}[/time] [level.thinking]THINKING[/level.thinking] [module]{record.name}[/module] | [level.thinking]<thinking>[/level.thinking] {record.getMessage()} [level.thinking]</thinking>[/level.thinking]"

        mod = record.name
        msg = record.getMessage()

        # 特殊：AI MSG 用 <msg> 标签样式
        if getattr(record, "_ai_msg", False):
            return f"[time]{ts}[/time] [msg.content]MSG[/msg.content] [module]{mod}[/module] | [msg.content]<msg>[/msg.content] {msg} [msg.content]</msg>[/msg.content]"

        return f"[time]{ts}[/time] [{style}]{level}[/{style}] [module]{mod}[/module] | {msg}"


class ModuleLogger(logging.Logger):
    """自定义 Logger，支持 success / ai_thinking / ai_msg / recv / sep / title / header"""

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1):
        # 提取特殊标记，转换为 record 属性传给 Formatter
        new_extra = dict(extra) if extra else {}
        thinking = new_extra.pop("thinking", False)
        ai_msg = new_extra.pop("ai_msg", False)
        recv_data = new_extra.pop("recv_data", None)
        if thinking:
            new_extra["_thinking"] = True
        if ai_msg:
            new_extra["_ai_msg"] = True
        if recv_data:
            new_extra["_recv_data"] = recv_data
        super()._log(level, msg, args, exc_info=exc_info, extra=new_extra if new_extra else None,
                     stack_info=stack_info, stacklevel=stacklevel + 1)

    def success(self, msg, *args, **kwargs):
        if self.isEnabledFor(SUCCESS):
            self._log(SUCCESS, msg, args, **kwargs)

    def ai_thinking(self, msg: str):
        self._log(logging.INFO, msg, (), extra={"thinking": True})

    def ai_msg(self, msg: str):
        self._log(logging.INFO, msg, (), extra={"ai_msg": True})

    def recv(self, platform: str, sender: str, content: str):
        self._log(logging.INFO, content, (), extra={"recv_data": (platform, sender, content)})

    # ── Rich 可视化 ──

    def sep(self, char: str = "─", count: int = 36):
        """分隔线"""
        _console.print(f"[dim]{char * count}[/dim]")

    def title(self, text: str):
        """章节标题"""
        _console.print(f"[bold gold3]{text}[/bold gold3]")

    def header(self, text: str, width: int = 50):
        """Rich Panel 标题（替代 raw_header）"""
        _console.print()
        _console.print(Panel(text, border_style="gold3", width=width))
        _console.print()

    def json_log(self, data: dict, title: str = ""):
        """JSON 结构化日志（参考 QQBOT 的 indent=2 风格）"""
        import json
        if title:
            _console.print(f"[dim]{title}[/dim]")
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        _console.print(Text(text, style="dim"))


# ── 全局辅助函数 ──

def raw_sep(char: str = "─", count: int = 36):
    _console.print(f"[dim]{char * count}[/dim]")

def raw_title(text: str):
    _console.print(f"[bold gold3]{text}[/bold gold3]")

def raw_header(text: str, width: int = 50):
    _console.print()
    _console.print(Panel(text, border_style="gold3", width=width))
    _console.print()


# ── 日志级别过滤 ──
_log_levels: dict[str, bool] = {}

def set_log_level(category: str, enabled: bool):
    _log_levels[category] = enabled

def is_log_enabled(category: str) -> bool:
    return _log_levels.get(category, True)


# ── Rich Handler（桥接 logging → Rich Console）──

class RichHandler(logging.Handler):
    """将 logging 记录通过 Rich Console 输出"""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.setFormatter(ColoredFormatter())

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            _console.print(msg, markup=True)
        except Exception:
            self.handleError(record)


# ── 初始化 ──
_initialized = False

def setup_console_logging(level: int = logging.DEBUG):
    global _initialized
    if _initialized:
        return

    # Windows ANSI 支持（Rich 需要）
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Rich 终端 handler
    rh = RichHandler(level=level)
    root.addHandler(rh)

    # 文件 handler（5MB × 5 个备份）
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = RotatingFileHandler(
        str(log_dir / "dmshoot.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)

    # 三方库静默
    for lib in ["httpx", "httpcore", "urllib3", "asyncio", "playwright", "MARKDOWN", "markdown"]:
        logging.getLogger(lib).setLevel(logging.WARNING)
    logging.getLogger("websocket").setLevel(logging.CRITICAL)

    _initialized = True


def get_logger(name: str = "dmshoot") -> ModuleLogger:
    """获取带模块短名的 ModuleLogger"""
    saved = logging.getLoggerClass()
    try:
        logging.setLoggerClass(ModuleLogger)
        mgr = logging.Logger.manager
        if name in mgr.loggerDict and not isinstance(mgr.loggerDict[name], ModuleLogger):
            del mgr.loggerDict[name]
        return logging.getLogger(name)
    finally:
        logging.setLoggerClass(saved)
