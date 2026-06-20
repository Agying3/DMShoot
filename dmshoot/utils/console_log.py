"""彩色终端日志 — 不写文件，只打控制台

用法:
    from dmshoot.utils.console_log import get_logger
    logger = get_logger(__name__)
    logger.info("连接成功")
    logger.success("消息已发送")
    logger.warning("重试中...")
    logger.ai_thinking("用户可能想问...")
    logger.ai_msg("好的，我来帮你...")
    logger.recv("抖音", "造化众生", "你好")
"""

import logging
import sys
from datetime import datetime
from typing import Optional

# ── ANSI 颜色 ──
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

# 前景色
FG_WHITE   = "\033[37m"
FG_GREEN   = "\033[32m"
FG_YELLOW  = "\033[33m"
FG_RED     = "\033[31m"
FG_CYAN    = "\033[36m"
FG_MAGENTA = "\033[35m"
FG_BLUE_B   = "\033[94m"
FG_GRAY    = "\033[90m"

# 高亮
FG_GREEN_B  = "\033[92m"
FG_YELLOW_B = "\033[93m"
FG_CYAN_B   = "\033[96m"
FG_GOLD     = "\033[38;5;214m"   # 金色：章节标题、分隔线

# ── 自定义日志级别 ──
SUCCESS = 25  # 介于 INFO(20) 和 WARNING(30) 之间
THINKING = 21  # 介于 INFO(20) 和 SUCCESS(25) 之间
logging.addLevelName(SUCCESS, "SUCCESS")
logging.addLevelName(THINKING, "THINKING")


class ColoredFormatter(logging.Formatter):
    """HH:MM:SS LEVEL MODULE | content，带颜色"""

    LEVEL_COLORS = {
        "DEBUG":    FG_GRAY,
        "INFO":     FG_WHITE,
        "SUCCESS":  FG_GREEN_B,
        "WARNING":  FG_YELLOW_B,
        "ERROR":    FG_RED,
        "THINKING": FG_CYAN_B,
        "RECV":     FG_MAGENTA,
    }

    def format(self, record: logging.LogRecord) -> str:
        # 时间: 05-30 13:16:12
        now = datetime.fromtimestamp(record.created)
        ts = now.strftime("%m-%d %H:%M:%S")

        # 级别: [INFO]
        level = record.levelname
        color = self.LEVEL_COLORS.get(level, FG_WHITE)
        level_str = f"{color}[{level}]{RESET}"

        # 模块名
        mod = record.name
        mod_str = f"{FG_BLUE_B}{mod}{RESET}"

        # 内容
        msg = record.getMessage()

        return f"{ts} {level_str} {mod_str} | {msg}"


def _success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS):
        self._log(SUCCESS, message, args, **kwargs)


class ModuleLogger(logging.Logger):
    """自定义 Logger，支持 success / ai_thinking / ai_msg / recv 方法"""

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False,
             stacklevel=1):
        thinking = (extra or {}).pop("thinking", False)
        if thinking:
            super()._log(THINKING, f"{FG_CYAN_B}<thinking>{RESET} {msg} {FG_CYAN_B}</thinking>{RESET}", args,
                        exc_info=exc_info, extra=extra, stack_info=stack_info,
                        stacklevel=stacklevel + 1)
        else:
            super()._log(level, msg, args, exc_info=exc_info, extra=extra,
                        stack_info=stack_info, stacklevel=stacklevel + 1)

    def success(self, msg, *args, **kwargs):
        _success(self, msg, *args, **kwargs)

    def ai_thinking(self, msg: str):
        """AI 思考过程日志"""
        self._log(logging.INFO, msg, (), extra={"thinking": True})

    def ai_msg(self, msg: str):
        """AI 回复内容日志"""
        self.info(f"{FG_GREEN_B}<msg>{RESET} {msg} {FG_GREEN_B}</msg>{RESET}")

    def recv(self, platform: str, sender: str, content: str):
        """收到平台私信"""
        self.info(f"{FG_MAGENTA}[{platform}]{RESET} {DIM}{sender}:{RESET} {content}")

    def sep(self, char: str = "─", count: int = 36):
        """原始分隔线 — 不加时间戳/级别前缀"""
        sys.stdout.write(f"{FG_GOLD}{char * count}{RESET}\n")
        sys.stdout.flush()

    def title(self, text: str):
        """章节标题 — 不加时间戳/级别前缀"""
        sys.stdout.write(f"{FG_GOLD}{text}{RESET}\n")
        sys.stdout.flush()


# ── 全局辅助函数 ──

def raw_sep(char: str = "─", count: int = 36):
    """原始分隔线 — 不加时间戳/级别前缀（模块级便捷函数）"""
    sys.stdout.write(f"{FG_GOLD}{char * count}{RESET}\n")
    sys.stdout.flush()

def raw_title(text: str):
    """章节标题 — 不加时间戳/级别前缀（模块级便捷函数）"""
    sys.stdout.write(f"{FG_GOLD}{text}{RESET}\n")
    sys.stdout.flush()

def raw_header(text: str, width: int = 50):
    """平台启动头 — 双线框金色标题，与 'DMShoot 就绪' 风格一致"""
    bar = FG_GOLD + "═" * width + RESET
    sys.stdout.write(f"\n{bar}\n{FG_GOLD}{BOLD}  {text}{RESET}\n{bar}\n\n")
    sys.stdout.flush()


# ── 日志级别过滤 ──
_log_levels: dict[str, bool] = {}  # {category: enabled}

def set_log_level(category: str, enabled: bool):
    """设置日志类别开关"""
    _log_levels[category] = enabled

def is_log_enabled(category: str) -> bool:
    """检查某类日志是否启用。未注册的类别默认启用。"""
    return _log_levels.get(category, True)
# 避免污染第三方库（httpx/bilibili_api 等）的 logger


# ── 初始化 ──
_initialized = False


def setup_console_logging(level: int = logging.DEBUG):
    """初始化终端日志（全局调用一次）"""
    global _initialized
    if _initialized:
        return

    # 根 logger
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler
    root.handlers.clear()

    # 只加控制台 handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(ColoredFormatter())
    root.addHandler(handler)

    # 三方库别吵
    for lib in ["httpx", "httpcore", "urllib3", "asyncio", "playwright", "MARKDOWN", "markdown"]:
        logging.getLogger(lib).setLevel(logging.WARNING)
    # websocket 库的断连 ERROR 由我们自己 WARNING 处理
    logging.getLogger("websocket").setLevel(logging.CRITICAL)

    _initialized = True


def get_logger(name: str = "dmshoot") -> ModuleLogger:
    """获取带模块短名的 ModuleLogger。
    只对 DMShoot logger 设置 ModuleLogger 类，不污染全局。

    注意：logging 模块会缓存 logger 实例。如果之前已通过 logging.getLogger(name)
    创建了标准 Logger，需先清除缓存，否则 setLoggerClass 不生效。"""
    saved = logging.getLoggerClass()
    try:
        logging.setLoggerClass(ModuleLogger)
        # 清除缓存中已存在的标准 Logger 实例（否则返回缓存的旧实例）
        mgr = logging.Logger.manager
        if name in mgr.loggerDict and not isinstance(mgr.loggerDict[name], ModuleLogger):
            del mgr.loggerDict[name]
        return logging.getLogger(name)  # type: ignore
    finally:
        logging.setLoggerClass(saved)
