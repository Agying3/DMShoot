"""主窗口 — 侧边栏导航 + 多页面"""

import sys
import time
import random
import asyncio
from pathlib import Path
import ctypes
import ctypes.wintypes

import markdown

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget,
    QDialog, QTextBrowser, QScrollArea,
)
from PySide6.QtCore import QTimer, Qt, QPoint, QPointF, QRect, QThread, Signal as QtSignal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QAction, QBrush, QMouseEvent, QPainter, QPainterPath, QPen, QRegion, QTransform, QColor, QFont, QTextOption

from dmshoot.core.bus import MessageBus
from dmshoot.core.message import Message
from dmshoot.gui.monitor_panel import MonitorPanel
from dmshoot.gui.sidebar import Sidebar
from dmshoot.gui.pages.home_page import HomePage
from dmshoot.gui.pages.login_page import LoginPage
from dmshoot.gui.pages.deepseek_page import DeepSeekPage
from dmshoot.gui.pages.prompt_page import PromptPage
from dmshoot.storage import database
from dmshoot.storage.models import ChatMessage, AppConfig
from dmshoot.ai.backend import get_ai, init_ai
from dmshoot.ai.prompts import load_prompts, load_behavior_prompts
from dmshoot.plugins.manager import PluginManager
from dmshoot.utils.console_log import get_logger
from dmshoot.core.adapter_manager import AdapterManager
from dmshoot.gui.auth_controller import AuthController
from dmshoot.gui.signal_wiring import SignalWiring
from dmshoot.gui.workers.ai_worker import AIWorker, ActiveAIWorker
from dmshoot.gui.widgets.toast import show_toast
from dmshoot.gui.font_manager import FontManager

logger = get_logger(__name__)

# ── 标题栏 ──

class PinButton(QPushButton):
    """置顶按钮 — 图钉转动画钉入 + 破洞效果"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pinned = False
        self._rotation = 0.0
        self._hover = False
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("窗口置顶")
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._spin = QPropertyAnimation(self, b"rotation")
        self._spin.setDuration(600)
        self._spin.setStartValue(0.0)
        self._spin.setKeyValueAt(0.35, 290.0)
        self._spin.setKeyValueAt(0.7, 380.0)
        self._spin.setEndValue(360.0)
        self._spin.setEasingCurve(QEasingCurve.InOutCubic)

    def toggle(self, window):
        self._pinned = not self._pinned
        try:
            hwnd = int(window.winId())
            HWND_TOPMOST = ctypes.c_void_p(-1)
            HWND_NOTOPMOST = ctypes.c_void_p(-2)
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            flags = SWP_NOMOVE | SWP_NOSIZE
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST if self._pinned else HWND_NOTOPMOST,
                0, 0, 0, 0,
                flags,
            )
        except Exception as e:
            logger.warning(f"图钉切换失败: {e}")
        self.setToolTip("已置顶 · 点击取消" if self._pinned else "窗口置顶")
        self._apply_mask()
        self._spin.stop()
        self._spin.setStartValue(self._rotation)
        self._spin.setEndValue(self._rotation + 360.0)
        self._spin.start()

    def _apply_mask(self):
        self.clearMask()
        if self._pinned:
            r = self.rect()
            full = QRegion(r)
            # 针尖正下方的小孔，透出后面内容
            hole = QRegion(QRect(r.center().x() - 3, r.center().y() + 2, 6, 6), QRegion.Ellipse)
            self.setMask(full.subtracted(hole))

    def _get_rotation(self):
        return self._rotation
    def _set_rotation(self, value):
        self._rotation = value % 360.0
        self.update()
    rotation = Property(float, _get_rotation, _set_rotation)

    def enterEvent(self, e):
        self._hover = True; self.update()
    def leaveEvent(self, e):
        self._hover = False; self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        cx, cy = r.center().x(), r.center().y()

        # 钉入后：针尖下的破洞边缘
        if self._pinned:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(40, 40, 55, 180), 1.0))
            p.drawEllipse(QPointF(cx, cy + 6), 5, 4)

        # 图钉旋转
        angle = self._rotation if not self._pinned else -8
        p.translate(cx, cy)
        p.rotate(angle)
        p.translate(-cx, -cy)

        font = QFont()
        font.setPixelSize(18)
        p.setFont(font)
        if self._pinned:
            color = QColor(137, 180, 250, 250)
        elif self._hover:
            color = QColor(255, 255, 255, 220)
        else:
            color = QColor(255, 255, 255, 150)
        p.setPen(color)
        p.drawText(r, Qt.AlignCenter, "📌")
        p.end()


class RotatingGear(QPushButton):
    """带旋转动画的齿轮按钮"""
    def __init__(self, parent=None):
        super().__init__("⚙", parent)
        self._angle = 0
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("设置")
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "border-radius: 15px; color: rgba(255,255,255,0.55); font-size: 16px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.12); color: rgba(255,255,255,0.85); }"
        )
        self._anim = QPropertyAnimation(self, b"angle")
        self._anim.setDuration(600)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def spin(self):
        if self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()
        self._anim.setStartValue(self._angle)
        self._anim.setEndValue(self._angle + 360)
        self._anim.start()

    def _get_angle(self):
        return self._angle
    def _set_angle(self, value):
        self._angle = value % 360
        self.update()
    angle = Property(float, _get_angle, _set_angle)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = self.rect().center()
        p.translate(center)
        p.rotate(self._angle)
        p.translate(-center)
        font = QFont()
        font.setPixelSize(18)
        p.setFont(font)
        color = QColor(255, 255, 255, 200) if self.underMouse() else QColor(255, 255, 255, 140)
        p.setPen(color)
        p.drawText(self.rect(), Qt.AlignCenter, "⚙")
        p.end()


class TitleBar(QWidget):
    minimize_clicked = QtSignal()
    close_clicked = QtSignal()
    settings_clicked = QtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("TitleBar")
        self.setFixedHeight(36)
        self._drag_pos = None
        self._spin_anim = None

        layout = QHBoxLayout()
        layout.setContentsMargins(14, 0, 4, 0)

        title = QLabel("DMShoot")
        title.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.70);"
            " background:transparent;"
        )
        layout.addWidget(title)
        layout.addStretch()

        # 置顶按钮
        self.btn_pin = PinButton()
        self.btn_pin.clicked.connect(lambda: self.btn_pin.toggle(self.window()))
        layout.addWidget(self.btn_pin)

        # 齿轮设置按钮
        self.btn_gear = RotatingGear()
        self.btn_gear.clicked.connect(self._on_gear_click)
        layout.addWidget(self.btn_gear)

        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("winBtn"); self.btn_min.setFixedSize(30, 30)
        self.btn_min.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.12); border: none; "
            "border-radius: 10px; color: rgba(255,255,255,0.65); font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(255,255,255,0.22); color: rgba(255,255,255,0.95); }"
        )
        self.btn_min.clicked.connect(self.minimize_clicked.emit)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("winBtn"); self.btn_close.setFixedSize(30, 30)
        self.btn_close.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.12); border: none; "
            "border-radius: 10px; color: rgba(255,255,255,0.65); font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background: rgba(232,17,35,0.55); color: #ffffff; }"
        )
        self.btn_close.clicked.connect(self.close_clicked.emit)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_close)
        self.setLayout(layout)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()
    def mouseMoveEvent(self, e):
        if self._drag_pos is not None:
            self.window().move(
                self.window().pos() + e.globalPosition().toPoint() - self._drag_pos
            )
            self._drag_pos = e.globalPosition().toPoint()
    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def _on_gear_click(self):
        self.btn_gear.spin()
        self.settings_clicked.emit()


# ── 壁纸容器 ──

class ShadowContainer(QFrame):
    def __init__(self, inner: QWidget):
        super().__init__()
        self.setObjectName("ShadowContainer")
        bg = Path(__file__).parent.parent.parent / "resources" / "b2.jpg"
        if bg.exists():
            css = (
                f"QFrame#ShadowContainer {{"
                f" border-image: url({bg.as_posix()}) 0 0 0 0 stretch stretch;"
                f" border: 0.5px solid rgba(255,255,255,0.08);"
                f" border-radius: 16px; }}"
            )
        else:
            css = (
                "QFrame#ShadowContainer {"
                " background: rgba(8,10,16,0.96);"
                " border: 0.5px solid rgba(255,255,255,0.08);"
                " border-radius: 16px; }"
            )
        self.setStyleSheet(css)
        layout = QVBoxLayout(); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        layout.addWidget(inner); self.setLayout(layout)


# ── Markdown 查看器 ──

class MarkdownViewer(QDialog):
    """显示 Markdown 格式的逆向日志文档（非模态，不阻塞主窗口）"""

    _CSS = """
        body {
            font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
            line-height: 1.75; background: #1e1e2e; color: #cdd6f4;
            padding: 4px; margin: 0;
        }
        h1 { color: #cba6f7; border-bottom: 2px solid #45475a; padding-bottom: 8px; font-size: 20px; }
        h2 { color: #89b4fa; border-bottom: 1px solid #45475a; padding-bottom: 5px; font-size: 16px; }
        h3 { color: #a6e3a1; font-size: 14px; }
        table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 12px; }
        th { background: #45475a; color: #f5c2e7; padding: 8px 10px; text-align: left; }
        td { border: 1px solid #45475a; padding: 6px 10px; }
        tr:nth-child(even) td { background: rgba(255,255,255,0.03); }
        code { background: #313244; padding: 1px 5px; border-radius: 3px; font-family: 'Consolas', monospace; font-size: 12px; }
        pre { background: #11111b; padding: 12px 14px; border-radius: 6px; overflow-x: auto; }
        pre code { background: none; padding: 0; }
        hr { border: none; border-top: 1px solid #45475a; margin: 18px 0; }
        blockquote { border-left: 3px solid #cba6f7; padding-left: 14px; margin-left: 0; color: #a6adc8; }
        a { color: #89b4fa; text-decoration: none; }
        strong { color: #f9e2af; }
        em { color: #f38ba8; }
    """

    def __init__(self, md_path: str, title: str = "逆向日志", parent=None):
        super().__init__(parent)
        self._md_path = md_path
        self.setWindowTitle(title)
        self.setMinimumSize(780, 600)
        self.resize(820, 720)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题栏
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background: #313244; border-bottom: 1px solid #45475a;")
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(16, 0, 8, 0)
        lbl = QLabel(f"📄 {title}")
        lbl.setStyleSheet("color: #cdd6f4; font-size: 13px; font-weight: bold;")
        tl.addWidget(lbl)
        tl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #cdd6f4; font-size: 14px; }"
            "QPushButton:hover { background: #45475a; border-radius: 14px; color: #f38ba8; }"
        )
        close_btn.clicked.connect(self.close)
        tl.addWidget(close_btn)
        layout.addWidget(title_bar)

        # 内容区域
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            "QTextBrowser { background: #1e1e2e; border: none; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical { background: #45475a; border-radius: 4px; min-height: 30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)

        try:
            md_content = Path(md_path).read_text(encoding="utf-8")
            html_body = markdown.markdown(
                md_content,
                extensions=["tables", "fenced_code", "codehilite", "nl2br"],
            )
            full_html = f"<html><head><style>{self._CSS}</style></head><body>{html_body}</body></html>"
            browser.setHtml(full_html)
        except Exception as e:
            browser.setPlainText(f"无法加载日志文件：{e}")

        layout.addWidget(browser)

        # 底部提示栏
        footer = QWidget()
        footer.setFixedHeight(32)
        footer.setStyleSheet("background: #313244; border-top: 1px solid #45475a;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        hint = QLabel("此窗口可随时关闭，不影响程序运行")
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        fl.addWidget(hint)
        fl.addStretch()
        layout.addWidget(footer)

    def closeEvent(self, event):
        """关闭时只隐藏，不销毁，方便重新打开"""
        self.hide()
        event.ignore()


# ── 主窗口 ──

class MainWindow(QMainWindow):
    # AI 连接测试结果信号（跨线程安全）
    _ai_test_result = QtSignal(bool, str)  # (成功, 消息)
    _send_result = QtSignal(str, str, str, bool)  # session_id, platform, text, ok
    _settings_ready = QtSignal()

    def __init__(self):
        super().__init__()
        self.bus = MessageBus.instance()
        self.config = AppConfig()
        self._adapters: dict = {}
        self._closing = False  # 关闭标志，防止 QTimer 回调访问已销毁 widget
        self._prompt_signals_bound = False
        self._settings_class = None
        self._settings_loading = False
        self._settings_open_requested = False
        self._settings_dialog = None
        self.font_manager = None
        self.plugins = PluginManager()

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("DMShoot")
        self.setMinimumSize(900, 520)
        self.resize(1100, 620)

        self._load_style()
        database.init_database()
        self.config = database.load_config()
        self.font_manager = FontManager.instance(FontManager.resolve_font_dir())
        self.config.font_mode = self.font_manager.apply(self.config.font_mode)
        logger.info("DMShoot 启动中...")
        self._init_ai()
        logger.info("_init_ai 完成")
        self._build_ui()
        logger.info("_build_ui 完成")

        # ── P0 重构：适配器管理器 & 认证控制器 ──
        self._adapter_mgr = AdapterManager(
            self.config, self.plugins, self.bus, self._adapters,
            self.page_login, self.page_home, self.sidebar, self.monitor)
        self._auth_ctrl = AuthController(
            self.config, self.plugins, self.bus, self.sidebar,
            self.page_login, self.stack, self._adapter_mgr)

        SignalWiring.connect_all(self, self._adapter_mgr, self._auth_ctrl)
        # AI 连接测试结果信号（跨线程安全）
        self._ai_test_result.connect(self._on_ai_test_result)
        self._send_result.connect(self._on_send_result)
        self._settings_ready.connect(self._on_settings_ready)
        logger.info("_connect_signals 完成")
        self._sync_config_to_ui()
        logger.info("_sync_config_to_ui 完成")
        self._apply_wallpaper()
        from dmshoot.utils.console_log import raw_title
        raw_title("  DMShoot 就绪 — 等待连接")
        QTimer.singleShot(100, lambda: self.sidebar.set_active("home"))
        QTimer.singleShot(150, self._preload_settings)
        # 认证控制器统一负责启动时的验证和监听，避免重复调度适配器
        QTimer.singleShot(900, self._auth_ctrl.auto_login)
        # 通讯录右键菜单：AI主动发一句
        self.page_home.contacts.active_message_requested.connect(
            self._on_active_message_request
        )
        # 性能监控 — 每秒 tick
        self._perf_timer = QTimer(self)
        self._perf_timer.timeout.connect(self._tick_perf)
        self._perf_timer.start(1000)

    def _tick_perf(self):
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().tick()
        if hasattr(self, '_settings_dialog') and self._settings_dialog:
            try:
                self._settings_dialog.tick_perf()
            except Exception:
                pass

    def _load_style(self):
        qss = Path(__file__).parent / "styles.qss"
        if qss.exists():
            QApplication.instance().setStyleSheet(qss.read_text(encoding="utf-8"))

    # ── UI ──

    def _build_ui(self):
        root = QWidget()
        root.setAttribute(Qt.WA_TranslucentBackground)
        root.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(); rl.setContentsMargins(0,0,0,0)
        content = self._build_content()
        shadow = ShadowContainer(content)
        rl.addWidget(shadow)
        root.setLayout(rl)
        self.setCentralWidget(root)

    def _build_content(self) -> QWidget:
        c = QWidget(); c.setObjectName("ContentPanel")
        l = QVBoxLayout(); l.setContentsMargins(0,0,0,0); l.setSpacing(0)

        tb = TitleBar()
        tb.minimize_clicked.connect(self.showMinimized)
        tb.close_clicked.connect(self.close)
        tb.settings_clicked.connect(lambda: self._on_nav("settings"))
        l.addWidget(tb)

        logger.info("_build_content: body...")
        body = QWidget()
        bl = QHBoxLayout(); bl.setContentsMargins(0,0,0,0); bl.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(self._on_nav)

        logger.info("_build_content: monitor...")
        self.monitor = MonitorPanel()
        self.monitor.hide()  # 连接成功后才显示
        self.stack = QStackedWidget()
        plt = [(p.id, p.name) for p in self.plugins.list()]
        logger.info(f"_build_content: HomePage with {plt}")
        self.page_home = HomePage(self.monitor, plt, font_manager=self.font_manager)
        self.page_login = LoginPage()
        self.page_deepseek = DeepSeekPage()
        self.page_prompt = PromptPage()

        self.stack.addWidget(self.page_home)     # 0
        self.stack.addWidget(self.page_login)    # 1
        self.stack.addWidget(self.page_deepseek) # 2
        self.stack.addWidget(self.page_prompt)   # 3

        bl.addWidget(self.sidebar)
        bl.addWidget(self.stack, stretch=1)
        body.setLayout(bl)
        l.addWidget(body)
        c.setLayout(l)
        self._body = body  # 壁纸用
        return c

    def _apply_wallpaper(self):
        """根据配置设置聊天背景"""
        path = self.config.wallpaper_path
        if path and Path(path).exists():
            self._body.setStyleSheet(
                f"QWidget#ContentPanel body {{"
                f"  background-image: url({path.replace(chr(92), '/')});"
                f"  background-position: center;"
                f"  border: none;"
                f"}}"
            )
        else:
            self._body.setStyleSheet("")

    # ── 导航 ──

    def _on_nav(self, key: str):
        if key == "settings":
            if self._settings_dialog and self._settings_dialog.isVisible():
                self._settings_dialog.raise_()
                self._settings_dialog.activateWindow()
                return
            if self._settings_class is None:
                self._settings_open_requested = True
                self._preload_settings()
                return
            self._show_settings()
            return
        pages = {"home": 0, "login": 1, "deepseek": 2, "prompt": 3}
        self.stack.setCurrentIndex(pages.get(key, 0))

    def _on_cache_cleared(self, platform: str):
        """缓存清除后自动重连平台"""
        self._adapter_mgr.stop_from_ui(platform)
        QTimer.singleShot(500, lambda: self._adapter_mgr.start_from_ui(platform))

    def _preload_settings(self):
        """后台预载设置模块；Qt 控件仍只在主线程创建。"""
        if self._settings_class is not None or self._settings_loading:
            return
        self._settings_loading = True
        import threading
        threading.Thread(
            target=self._load_settings_module,
            name="settings-preload",
            daemon=True,
        ).start()

    def _load_settings_module(self):
        try:
            from dmshoot.gui.settings_dialog import SettingsDialog
            self._settings_class = SettingsDialog
        except Exception:
            logger.exception("设置模块预载失败")
        finally:
            self._settings_loading = False
            try:
                self._settings_ready.emit()
            except RuntimeError:
                pass

    def _on_settings_ready(self):
        if self._settings_open_requested and self._settings_class is not None:
            self._settings_open_requested = False
            self._show_settings()

    def _show_settings(self):
        dialog = self._settings_class(self.config, self, font_manager=self.font_manager)
        self._settings_dialog = dialog
        dialog.cache_cleared.connect(self._on_cache_cleared)
        dialog.font_mode_changed.connect(self._on_font_mode_changed)
        dialog.finished.connect(
            lambda result, d=dialog: self._on_settings_closed(result, d)
        )
        dialog.show()

    def _on_settings_closed(self, result: int, dialog=None):
        if result == QDialog.Accepted:
            latest = database.load_config()
            for field_name in type(self.config).__dataclass_fields__:
                setattr(self.config, field_name, getattr(latest, field_name))
            self._sync_config_to_ui()
            self._apply_wallpaper()
            self.page_home.chat.set_font_mode(self.config.font_mode)
            show_toast(self, "设置已保存", "success")
        if dialog is not None:
            dialog.deleteLater()
            if self._settings_dialog is dialog:
                self._settings_dialog = None

    def _on_font_mode_changed(self, mode: str):
        """字体模式切换后同步已经创建的聊天控件。"""
        if self.font_manager is not None:
            mode = self.font_manager.apply(mode)
        self.config.font_mode = mode
        self.page_home.chat.set_font_mode(mode)

    # ── 配置同步 ──

    def _sync_config_to_ui(self):
        c = self.config
        self.page_deepseek.set_values(c.api_key, c.base_url, c.model)
        if c.api_key:
            ai = get_ai()
            if ai.configured:
                self.page_deepseek.set_status(f"已连接 {c.model}")
                self.page_deepseek.set_status_color("green")
                self.sidebar.update_ai_status("●")
            else:
                self.page_deepseek.set_status(f"就绪 {c.model}")
                self.page_deepseek.set_status_color("")
                self.sidebar.update_ai_status("—")
        else:
            self.page_deepseek.set_status("未连接")
            self.sidebar.update_ai_status("✕")

        auth_state = [
            ("douyin", bool(c.douyin_cookie), "抖音"),
            ("bilibili", bool(c.bilibili_sessdata), "B站"),
            ("xiaohongshu", bool(c.xhs_cookie), "小红书"),
            ("kuaishou", bool(c.ks_cookie), "快手"),
        ]
        for platform, has_cookie, name in auth_state:
            self.page_login.set_status(
                platform, f"{name} · {'就绪' if has_cookie else '未登录'}"
            )
            self.sidebar.update_status(platform, "—" if has_cookie else "未登录")

        self.page_login.auto_monitor.setChecked(c.bilibili_auto_monitor)
        self.page_home._load_contacts()

        from dmshoot.core.rate_limiter import get_limiter
        get_limiter("douyin").set_rate(c.rate_douyin)
        get_limiter("bilibili").set_rate(c.rate_bilibili)
        get_limiter("kuaishou").set_rate(c.rate_kuaishou)
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().set_enabled(c.perf_monitor_enabled)

        # 恢复调试日志开关
        import json as _json
        from dmshoot.utils.console_log import set_log_level
        if c.debug_log_levels:
            try:
                state = _json.loads(c.debug_log_levels)
                for k, v in state.items():
                    set_log_level(k, v)
            except Exception:
                pass

        # 提示词页面 — 角色 + 行为
        char_prompts = load_prompts()
        behavior_prompts = load_behavior_prompts()
        self.page_prompt.load_chars(char_prompts, c.prompt_preset)
        self.page_prompt.load_behaviors(behavior_prompts, c.behavior_preset)
        if char_prompts:
            self.page_prompt.set_content(char_prompts.get(c.prompt_preset, ""))
        # 设置窗口保存后会再次同步配置，信号只需要绑定一次。
        if not self._prompt_signals_bound:
            self.page_prompt.prompt_changed.connect(self._on_prompt_change)
            self.page_prompt.behavior_changed.connect(self._on_behavior_change)
            self._prompt_signals_bound = True

    # ── 信号 ── (已迁移到 SignalWiring)

    # ── 平台 ── (已迁移到 AdapterManager + AuthController)

    # ── DeepSeek ──

    def _save_deepseek(self, api_key, base_url, model):
        if not api_key.strip():
            self.page_deepseek.set_status("请先输入 API Key")
            self.page_deepseek.set_status_color("red")
            return

        self.config.api_key = api_key
        self.config.base_url = base_url or "https://api.deepseek.com"
        self.config.model = model or "deepseek-v4-flash"
        database.update_config_fields({
            "api_key": self.config.api_key,
            "base_url": self.config.base_url,
            "model": self.config.model,
        })
        self.page_deepseek.set_status("连接中...")
        self.page_deepseek.set_status_color("")

        # 异步测试连接 — 后台线程 + Signal 跨线程刷新 UI
        import threading
        threading.Thread(target=self._run_test_ai, daemon=True).start()

    def _run_test_ai(self):
        """在后台线程运行 asyncio 测试连接"""
        try:
            asyncio.run(self._test_ai_connection())
        except Exception as e:
            self._ai_test_result.emit(False, f"连接失败: {e}")

    async def _test_ai_connection(self):
        """实际测试 API 连接，通过 Signal 通知主线程更新 UI"""
        try:
            init_ai(self.config.api_key, self._get_prompt(), self.config.model, self._get_behavior_prompt())
            get_ai().set_persona(self.config.prompt_preset)
            ok, err = await get_ai().test_connection()
            self._ai_test_result.emit(ok, err if err else "")
        except Exception as e:
            self._ai_test_result.emit(False, f"连接失败: {e}")

    def _on_ai_test_result(self, ok: bool, msg: str):
        """Signal 槽：在 Qt 主线程安全地更新 AI 状态 UI"""
        if ok:
            self.page_deepseek.set_status(f"已连接 {self.config.model}")
            self.page_deepseek.set_status_color("green")
            self.sidebar.update_ai_status("●")
        else:
            self.page_deepseek.set_status(msg or "连接失败")
            self.page_deepseek.set_status_color("red")
            self.sidebar.update_ai_status("○")

    def _on_prompt_change(self, name: str):
        """角色提示词切换 — 保存配置 + 更新 AI 角色名"""
        if name == self.config.prompt_preset:
            return
        self.config.prompt_preset = name
        database.update_config_field("prompt_preset", name)
        self.page_prompt.set_content(load_prompts().get(name, ""))
        ai = get_ai()
        if ai.configured:
            # 先切角色清上下文，再重建 AI（新角色提示词生效）
            ai.set_persona(name)
            init_ai(self.config.api_key, self._get_prompt(), self.config.model, self._get_behavior_prompt())
            get_ai().set_persona(name)  # 新实例也要设置角色名
        logger.info(f"角色提示词切换: {name}")

    def _on_behavior_change(self, name: str):
        if name == self.config.behavior_preset:
            return
        self.config.behavior_preset = name
        database.update_config_field("behavior_preset", name)
        bp = load_behavior_prompts().get(name, "")
        ai = get_ai()
        if ai.configured:
            ai.set_behavior_prompt(bp)
            logger.info(f"行为提示词热更新: {name}")
        else:
            init_ai(self.config.api_key, self._get_prompt(), self.config.model, bp)

    def _get_behavior_prompt(self) -> str:
        prompts = load_behavior_prompts()
        return prompts.get(self.config.behavior_preset, "")

    # ── 总线日志 ──

    def _on_bus_log(self, level: str, platform: str, message: str):
        """来自适配器的日志 → 终端 + 监控面板"""
        import logging
        lg = logging.getLogger(f"DMShoot.{platform}")
        getattr(lg, level.lower(), lg.info)(message)

    # ── 消息 ──

    def _on_new_message(self, msg: Message):
        if not msg.content.strip():
            return
        new_unread = msg.raw.get("_unread_count", -1) if isinstance(msg.raw, dict) else -1

        # 性能监控 — 记录消息
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().record_msg()

        # 首页气泡（add_message 内部有缓存去重）
        self.page_home.add_message(msg.session_id, msg.sender_name, msg.content,
                                   timestamp=msg.timestamp,
                                   sender_id=msg.sender_id,
                                   message_key=msg.message_key,
                                   is_self=msg.is_self,
                                   unread_count=new_unread if not msg.is_self else -1)

        # 自己的消息不触发AI
        if msg.is_self:
            return
        # 历史消息不触发AI（启动同步时拉取的旧消息，距现在超过 5 分钟）
        import time as _time
        if _time.time() - msg.timestamp > 300:
            return
        ai = get_ai()
        if self.config.auto_reply_enabled and ai.configured and msg.msg_type == "text":
            import random as rand
            delay_ms = int(rand.uniform(self.config.reply_delay_min, self.config.reply_delay_max) * 1000)
            logger.info(f"AI回复延迟 {delay_ms}ms")
            timer = QTimer(self)
            timer.setSingleShot(True)
            def fire_reply(a=ai, m=msg, t=timer):
                try:
                    self._call_ai(m, a)
                finally:
                    t.deleteLater()
            timer.timeout.connect(fire_reply)
            timer.start(max(delay_ms, 500))

    def _call_ai(self, msg: Message, ai=None):
        ai = ai or get_ai()
        t = AIWorker(msg, ai, self)
        t.done.connect(lambda sid, txt, m=ai.model: self._on_ai_response(sid, txt, m))
        t.finished.connect(t.deleteLater)
        t.start()

    def _on_ai_response(self, session_id, reply_text, model):
        import re
        persona = self.config.prompt_preset or "AI"

        # 提取所有 <msg> 标签内容，每个 <msg> 作为一条独立消息
        msgs = re.findall(r'<msg>(.*?)</msg>', reply_text, re.DOTALL)
        if msgs:
            parts = [m.strip() for m in msgs if m.strip()]
            logger.info(f"MSG分拆: {len(parts)}段 → {[p[:20]+'...' for p in parts]}")
        else:
            parts = [reply_text.strip()] if reply_text.strip() else []

        if not parts:
            return

        platform = session_id.split(":")[0]
        adapter = self._adapters.get(platform)
        if not adapter:
            logger.warning(f"[无适配器] {platform} 未连接，消息无法发送")
            self.bus.log.emit("WARN", persona, f"{platform} 未连接，消息仅保存未发送")
        else:
            logger.info(f"[发送准备] {platform} adapter={adapter.platform_name}")

        for part in parts:
            # 保存到 DB
            ts = time.time()
            rm = ChatMessage(session_id=session_id, sender_name="AI",
                             sender_id="ai", content=part, is_auto=True,
                             persona=persona, timestamp=ts)
            database.save_message(rm)
            # 网络发送在后台完成，Qt 主线程只更新本地界面。
            self.page_home.add_message(session_id, persona, part, is_auto=True,
                                       persona=persona, send_ok=bool(adapter))

        if adapter:
            from dmshoot.core.concurrency import ConcurrencyManager
            mgr = ConcurrencyManager.instance()
            mgr.submit(
                ConcurrencyManager.PRIO_HIGH,
                platform,
                self._send_ai_parts,
                adapter,
                session_id,
                platform,
                list(parts),
            )

        # 更新会话最后消息
        conn = database.get_conn()
        conn.execute("""
            UPDATE sessions SET last_message=?, last_time=?
            WHERE session_id=?
        """, (parts[-1][:50], time.time(), session_id))
        conn.commit()

        # 监控面板日志（用户触发消息 + AI 完整回复）
        history = database.get_messages(session_id, limit=3)
        trigger_msg = (history[-2].content[:200] if len(history) >= 2
                       else (parts[0] if parts else reply_text))
        self.monitor.add_reply_log(trigger_msg, reply_text)

    def _send_ai_parts(self, adapter, session_id: str, platform: str, parts: list[str]):
        """在线程池中顺序发送 AI 回复，避免网络请求和间隔等待冻结窗口。"""
        import time as _sleep_time
        for index, part in enumerate(parts):
            if index > 0:
                _sleep_time.sleep(0.8)
            try:
                ok = adapter.send_rate_limited(session_id, part)
            except Exception:
                logger.exception(f"[{platform}] 后台发送异常")
                ok = False
            try:
                self._send_result.emit(session_id, platform, part, ok)
            except RuntimeError:
                return

    def _on_send_result(self, session_id: str, platform: str, text: str, ok: bool):
        if ok:
            return
        persona = self.config.prompt_preset or "AI"
        logger.error(f"[发送失败] {platform} → session={session_id}: '{text[:30]}'")
        self.bus.log.emit("ERROR", persona, f"发送失败: {text[:20]}...")
        show_toast(self, "消息发送失败，请检查平台连接", "warning", 2800)

    # ── AI 主动消息 ──

    def _on_active_message_request(self, session_id: str):
        """通讯录右键菜单：立即基于上下文生成一条主动消息并发送"""
        ai = get_ai()
        if not ai.configured:
            self.bus.log.emit("WARN", "AI主动消息", "AI 未配置，无法生成消息")
            return
        logger.info(f"[AI主动消息] 为 {session_id} 生成消息...")
        self.bus.log.emit("INFO", "AI主动消息", f"正在为 {session_id} 生成消息...")
        QTimer.singleShot(100, lambda: self._call_active_ai(session_id))

    def _call_active_ai(self, session_id: str, ai=None):
        """在后台线程调用 AI 生成主动消息"""
        ai = ai or get_ai()
        t = ActiveAIWorker(session_id, ai, self)
        t.done.connect(lambda sid, txt, m=ai.model: self._on_ai_response(sid, txt, m))
        t.finished.connect(t.deleteLater)
        t.start()

    def _get_prompt(self) -> str:
        prompts = load_prompts()
        return prompts.get(self.config.prompt_preset, "")

    def _init_ai(self):
        if self.config.api_key:
            init_ai(self.config.api_key, self._get_prompt(), self.config.model, self._get_behavior_prompt())
            get_ai().set_persona(self.config.prompt_preset)

    def closeEvent(self, event):
        self._closing = True
        self.page_login._stop_worker()
        self._adapter_mgr.stop_all()
        from dmshoot.core.concurrency import ConcurrencyManager
        ConcurrencyManager.instance().shutdown(wait=False)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
