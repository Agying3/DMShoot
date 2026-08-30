"""认证控制器 — 从 MainWindow 提取的自动登录 & 平台连接逻辑"""

import logging as _logging

from PySide6.QtCore import QThread, QTimer, Signal as QtSignal

from dmshoot.storage import database
from dmshoot.utils.console_log import raw_header, raw_sep, _console

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
        self._auto_login_running = False

    def _refresh_config(self):
        """从 DB 原地刷新共享 AppConfig，避免扫码后旧配置对象覆盖新 cookie。"""
        latest = database.load_config()
        for field_name in type(self._config).__dataclass_fields__:
            setattr(self._config, field_name, getattr(latest, field_name))
        return self._config

    # ── 自动登录 ──

    def auto_login(self):
        """启动时顺序验证已启用的平台，完成后再启动对应监听。"""
        if self._auto_login_running:
            return
        self._refresh_config()
        # 保存过登录信息的平台都做状态恢复；是否自动启动仍由 enabled 控制。
        queue = [
            platform for platform, cookie in (
                ("bilibili", self._config.bilibili_sessdata),
                ("douyin", self._config.douyin_cookie),
                ("kuaishou", self._config.ks_cookie),
            ) if cookie
        ]

        if not queue:
            return

        self._auto_login_running = True
        raw_header("自动登录验证")
        self._auto_login_results = {}

        def process_next():
            if not queue:
                self._print_summary()
                self._auto_login_running = False
                return
            platform = queue.pop(0)
            self._verify_sequential(platform, process_next)

        process_next()

    def _verify_sequential(self, platform: str, on_done):
        """顺序自动登录 — 完成后调 on_done 继续下一个平台"""
        self._refresh_config()
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
                self._bus.set_platform_status(platform, "已保存", msg)
                self._sidebar.update_status(platform, "—")
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
            # 给 Qt 一次空闲机会刷新首屏和状态，再处理下一个平台。
            QTimer.singleShot(250, on_done)

        worker.result.connect(handle_result)
        worker.start()

    def _print_summary(self):
        """打印自动登录汇总"""
        raw_sep("┈", 50)
        _console.print("[bold gold3]  DMShoot 已就绪，监听在后台运行[/bold gold3]")
        for platform, name in [("bilibili", "B站"), ("douyin", "抖音"), ("kuaishou", "快手")]:
            result = self._auto_login_results.get(platform)
            if result is None:
                _console.print(f"  [gold3]{name}[/gold3]  — 未配置")
            elif result[0]:
                _console.print(f"  [bold green]{name} ✓ 已连接[/bold green]  {result[1]}")
            else:
                _console.print(f"  [bold red]{name} ✕ 未登录[/bold red]  {result[1]}")
        raw_sep("┈", 50)
        _console.print("")

    # ── 扫码后连接 ──

    def connect_platform(self, platform: str):
        """扫码后连接平台。cookie 刚扫的，直接启动适配器，跳过网络验证。"""
        name = _PLATFORM_NAMES.get(platform, platform)
        self._refresh_config()  # 确保读到最新 cookie
        self._page_login.set_status(platform, f"{name} · 已保存")
        self._sidebar.update_status(platform, "已保存")
        self._page_login.on_connected(platform)
        self._sidebar.set_active("home")
        self._stack.setCurrentIndex(0)
        enabled = {"douyin": self._config.douyin_enabled,
                    "bilibili": self._config.bilibili_enabled,
                    "kuaishou": self._config.ks_enabled}.get(platform, False)
        if self._config.bilibili_auto_monitor and enabled:
            self._bus.log.emit("INFO", name, f"{name}已保存，正在启动监听...")
            self._sidebar.update_status(platform, "连接中")
            self._adapter_mgr.start_from_ui(platform)
        else:
            self._bus.log.emit("INFO", name, f"{name}登录信息已保存")

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
