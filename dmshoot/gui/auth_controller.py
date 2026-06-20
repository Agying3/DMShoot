"""认证控制器 — 从 MainWindow 提取的自动登录 & 平台连接逻辑"""

import sys
import logging as _logging

from PySide6.QtCore import QThread, Signal as QtSignal

from dmshoot.storage import database
from dmshoot.utils.console_log import raw_header, raw_sep, FG_GOLD, FG_GREEN_B, FG_RED, RESET, BOLD

_COOKIE_PLATFORMS = frozenset({"douyin", "kuaishou"})

_PLATFORM_NAMES = {"douyin": "抖音", "bilibili": "B站", "kuaishou": "快手"}


class _SeqWorker(QThread):
    """模块级 QThread — 顺序验证一个平台的登录状态"""
    result = QtSignal(bool, str)

    def __init__(self, plugins, platform, cookie, sessdata, jct,
                 buvid3, buvid4, dedeuserid, ac_time_value, parent=None):
        super().__init__(parent)
        self._plugins = plugins
        self._platform = platform
        self._cookie = cookie
        self._sessdata = sessdata
        self._jct = jct
        self._buvid3 = buvid3
        self._buvid4 = buvid4
        self._dedeuserid = dedeuserid
        self._ac_time_value = ac_time_value

    def run(self):
        try:
            plugin = self._plugins.get(self._platform)
            if self._platform in _COOKIE_PLATFORMS:
                ok = bool(self._cookie)
                self.result.emit(ok, "有效" if ok else "未登录")
                return
            import asyncio
            if plugin and plugin.login_handler:
                async def do():
                    return await plugin.login_handler(
                        self._sessdata, self._jct,
                        buvid3=self._buvid3, buvid4=self._buvid4,
                        dedeuserid=self._dedeuserid, ac_time_value=self._ac_time_value)
                loop = asyncio.new_event_loop()
                try:
                    ok, msg = loop.run_until_complete(do())
                finally:
                    loop.close()
            else:
                ok, msg = False, "缺少验证器"
            self.result.emit(ok, msg)
        except Exception as e:
            self.result.emit(False, str(e))


class AuthController:
    """MainWindow 自动登录 & 扫码后连接逻辑的提取。
    依赖通过构造函数注入。"""

    def __init__(self, config, plugins, bus, sidebar, page_login, stack,
                 adapter_manager):
        self._config = config
        self._plugins = plugins
        self._bus = bus
        self._sidebar = sidebar
        self._page_login = page_login
        self._stack = stack
        self._adapter_mgr = adapter_manager
        self._auto_login_results = {}

    # ── 自动登录 ──

    def auto_login(self):
        """启动时自动验证已保存的 Cookie — 顺序执行: B站 → 抖音 → 快手"""
        queue = []
        if self._config.bilibili_sessdata:
            queue.append("bilibili")
        if self._config.douyin_cookie:
            queue.append("douyin")
        if self._config.ks_cookie:
            queue.append("kuaishou")

        if not queue:
            return

        raw_header("自动登录验证")
        self._auto_login_results = {}

        def process_next():
            if not queue:
                self._print_summary()
                return
            platform = queue.pop(0)
            self._verify_sequential(platform, process_next)

        process_next()

    def _verify_sequential(self, platform: str, on_done):
        """顺序自动登录 — 完成后调 on_done 继续下一个平台"""
        name = _PLATFORM_NAMES.get(platform, platform)
        cookie = {
            "douyin": self._config.douyin_cookie,
            "bilibili": self._config.bilibili_sessdata,
            "kuaishou": self._config.ks_cookie,
        }.get(platform, "")
        sessdata = self._config.bilibili_sessdata if platform == "bilibili" else ""
        jct = self._config.bilibili_jct if platform == "bilibili" else ""
        buvid3 = self._config.bilibili_buvid3 if platform == "bilibili" else ""
        buvid4 = self._config.bilibili_buvid4 if platform == "bilibili" else ""
        dedeuserid = self._config.bilibili_dedeuserid if platform == "bilibili" else ""
        ac_time_value = self._config.bilibili_ac_time_value if platform == "bilibili" else ""

        worker = _SeqWorker(
            self._plugins, platform, cookie, sessdata, jct,
            buvid3, buvid4, dedeuserid, ac_time_value, None)
        lg = _logging.getLogger("DMShoot")

        def handle_result(ok, msg):
            if ok:
                lg.info(f"  {name} ✓ {msg}")
                self._auto_login_results[platform] = (True, msg)
                self._bus.set_platform_status(platform, "已连接", msg)
                self._sidebar.update_status(platform, "●")
                self._page_login.on_connected(platform)
                enabled = {"douyin": self._config.douyin_enabled,
                            "bilibili": self._config.bilibili_enabled,
                            "kuaishou": self._config.ks_enabled}.get(platform, False)
                if enabled:
                    self._adapter_mgr.start_from_ui(platform)
            else:
                lg.warning(f"  {name} ✕ {msg}")
                self._auto_login_results[platform] = (False, msg)
                hint = "Cookie 已过期，请重新扫码" if platform in _COOKIE_PLATFORMS else (msg or "验证失败")
                self._page_login.set_status(platform, f"{name} · {hint}")
                self._sidebar.update_status(platform, "✕")
            worker.deleteLater()
            on_done()

        worker.result.connect(handle_result)
        worker.start()

    def _print_summary(self):
        """打印自动登录汇总"""
        raw_sep("┈", 50)
        sys.stdout.write(f"{FG_GOLD}{BOLD}  DMShoot 启动完成{RESET}\n")
        for platform, name in [("bilibili", "B站"), ("douyin", "抖音"), ("kuaishou", "快手")]:
            result = self._auto_login_results.get(platform)
            if result is None:
                sys.stdout.write(f"  {FG_GOLD}{name}{RESET}  — 未配置\n")
            elif result[0]:
                sys.stdout.write(f"  {FG_GREEN_B}{name} ✓ 已连接{RESET}  {result[1]}\n")
            else:
                sys.stdout.write(f"  {FG_RED}{name} ✕ 未登录{RESET}  {result[1]}\n")
        raw_sep("┈", 50)
        sys.stdout.write("\n")
        sys.stdout.flush()

    # ── 扫码后连接 ──

    def connect_platform(self, platform: str):
        """扫码后连接平台。cookie 刚扫的，直接启动适配器，跳过网络验证。"""
        name = _PLATFORM_NAMES.get(platform, platform)
        self._config = database.load_config()  # 确保读到最新 cookie
        self._page_login.set_status(platform, f"{name} · 已保存")
        self._sidebar.update_status(platform, "●")
        self._page_login.on_connected(platform)
        self._bus.log.emit("INFO", name, f"{name}已连接，正在同步数据...")
        self._sidebar.set_active("home")
        self._stack.setCurrentIndex(0)
        enabled = {"douyin": self._config.douyin_enabled,
                    "bilibili": self._config.bilibili_enabled,
                    "kuaishou": self._config.ks_enabled}.get(platform, False)
        if self._config.bilibili_auto_monitor and enabled:
            self._adapter_mgr.start_from_ui(platform)

    # ── 状态同步 ──

    def on_platform_status(self, platform, status, msg):
        # 结合 status 字段和 msg 字段判断真实状态
        combined = f"{status or ''} {msg or ''}"
        self._sidebar.update_status(platform, combined if combined.strip() else (msg or status or "✕"))
        name = _PLATFORM_NAMES.get(platform, platform)
        self._page_login.set_status(platform, f"{name} · {msg or status}")

    @property
    def results(self):
        """返回自动登录结果 {platform: (ok, msg)}，供外部查询"""
        return self._auto_login_results
