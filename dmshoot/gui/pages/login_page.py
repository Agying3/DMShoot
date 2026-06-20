"""登录账号页面 — 扫码提取 + 手动输入 Cookie"""

import json
import base64
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QPushButton, QApplication,
    QLabel, QHBoxLayout, QCheckBox, QDialog, QScrollArea, QStackedWidget, QLineEdit
)
from PySide6.QtCore import Signal, QEvent, Qt, QPropertyAnimation, QEasingCurve, Property, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor

from dmshoot.storage import database
from dmshoot.gui.workers.login_worker import LoginWorker


class _SpinningIcon(QWidget):
    """旋转图标 — 用 QTransform 旋转绘制文字"""

    def __init__(self, text: str, size: int = 48, color: str = "#ff6b6b", parent=None):
        super().__init__(parent)
        self._text = text
        self._size = size
        self._color = QColor(color)
        self._angle = 0
        self.setFixedSize(size + 8, size + 8)

    def _get_angle(self): return self._angle
    def _set_angle(self, v): self._angle = v; self.update()

    angle = Property(float, _get_angle, _set_angle)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._angle)
        p.setPen(self._color)
        font = p.font()
        font.setPixelSize(self._size)
        p.setFont(font)
        p.drawText(-self._size // 2, -self._size // 2,
                   self._size, self._size,
                   Qt.AlignCenter, self._text)
        p.end()


class _QRDialog(QDialog):
    """扫码弹窗 — 加载动画 → 二维码"""

    def __init__(self, platform_name: str = "平台", parent=None):
        super().__init__(parent)
        self.setWindowTitle("")
        self.setFixedSize(320, 420)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Dialog
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignCenter)

        card = QWidget()
        card.setObjectName("qrCard")
        card.setStyleSheet("""
            #qrCard {
                background: rgba(25, 28, 38, 0.96);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 16px;
            }
            QLabel { background: transparent; }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.addStretch()
        title = QLabel(f"{platform_name} 登录")
        title.setStyleSheet(
            "color: rgba(255,255,255,0.9); font-size: 15px; font-weight: bold;"
        )
        header.addWidget(title)
        header.addStretch()
        close_btn = QLabel("×")
        close_btn.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 18px; margin-right: 4px;"
        )
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self.close()
        header.addWidget(close_btn)
        layout.addLayout(header)

        self._stack = QWidget()
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)

        # ── 加载页 ──
        self._loading_page = QWidget()
        loading_layout = QVBoxLayout(self._loading_page)
        loading_layout.setAlignment(Qt.AlignCenter)
        loading_layout.setSpacing(12)

        self._spinner = _SpinningIcon("⏳", size=48, color="#ff6b6b")
        loading_layout.addWidget(self._spinner, alignment=Qt.AlignCenter)

        self._loading_text = QLabel("正在启动浏览器...")
        self._loading_text.setAlignment(Qt.AlignCenter)
        self._loading_text.setStyleSheet(
            "color: rgba(255,255,255,0.6); font-size: 13px;"
        )
        loading_layout.addWidget(self._loading_text)

        self._rotate_anim = QPropertyAnimation(self._spinner, b"angle")
        self._rotate_anim.setDuration(2000)
        self._rotate_anim.setStartValue(0)
        self._rotate_anim.setEndValue(360)
        self._rotate_anim.setLoopCount(-1)
        self._rotate_anim.start()

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(90, 32)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 6px;
                color: rgba(255,255,255,0.7);
                font-size: 13px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.08);
                border-color: rgba(255,255,255,0.3);
            }
        """)
        cancel_btn.clicked.connect(self.close)
        loading_layout.addWidget(cancel_btn, alignment=Qt.AlignCenter)

        # ── 二维码页 ──
        self._qr_page = QWidget()
        qr_layout = QVBoxLayout(self._qr_page)
        qr_layout.setAlignment(Qt.AlignCenter)
        qr_layout.setSpacing(12)

        qr_container = QWidget()
        qr_container.setFixedSize(220, 220)
        qr_container.setStyleSheet(
            "background: white; border-radius: 14px;"
        )
        qr_container_layout = QVBoxLayout(qr_container)
        qr_container_layout.setContentsMargins(12, 12, 12, 12)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignCenter)
        qr_container_layout.addWidget(self._qr_label)
        qr_layout.addWidget(qr_container, alignment=Qt.AlignCenter)

        self._qr_hint = QLabel(f"请使用{platform_name}APP扫描上方二维码")
        self._qr_hint.setAlignment(Qt.AlignCenter)
        self._qr_hint.setStyleSheet(
            "color: rgba(255,255,255,0.6); font-size: 12px; line-height: 1.6;"
        )
        qr_layout.addWidget(self._qr_hint)

        cancel_btn2 = QPushButton("取消")
        cancel_btn2.setFixedSize(90, 32)
        cancel_btn2.setStyleSheet(cancel_btn.styleSheet())
        cancel_btn2.clicked.connect(self.close)
        qr_layout.addWidget(cancel_btn2, alignment=Qt.AlignCenter)

        self._stack_layout.addWidget(self._loading_page)
        self._stack_layout.addWidget(self._qr_page)
        self._qr_page.hide()

        layout.addWidget(self._stack, stretch=1)
        outer.addWidget(card)
        self.setLayout(outer)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(500)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_done)

    def set_qr_image(self, data):
        """切换到二维码显示 — 支持 PNG bytes 或 base64 data URL"""
        if isinstance(data, str) and data.startswith("data:image/"):
            import base64
            header, encoded = data.split(",", 1)
            data = base64.b64decode(encoded) if ";base64" in header else data
        if data:
            pixmap = QPixmap()
            pixmap.loadFromData(data, 'PNG' if isinstance(data, bytes) else None)
            self._qr_label.setPixmap(
                pixmap.scaled(184, 184, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self._loading_page.hide()
        self._qr_page.show()

    def fade_out(self):
        """扫码成功后淡出"""
        self._fade_anim.start()

    def _on_fade_done(self):
        self.accept()
        self.close()

    def closeEvent(self, event):
        if hasattr(self, '_rotate_anim'):
            self._rotate_anim.stop()
        super().closeEvent(event)


class LoginPage(QWidget):
    connect_platform = Signal(str)
    start_monitor = Signal(str)
    stop_monitor = Signal(str)
    clear_platform = Signal(str)

    def __init__(self):
        super().__init__()
        self._worker = None
        self._qr_dialog = None      # 小红书二维码弹窗
        self._bili_running = False
        self._dy_running = False
        self._xhs_running = False
        self._ks_running = False
        self._has_dy = False
        self._has_bili = False
        self._has_xhs = False
        self._has_ks = False

        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(16)

        # === 左列 ===
        left_scroll = QScrollArea()
        left_scroll.setFixedWidth(230)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QScrollBar:vertical { width: 6px; background: rgba(255,255,255,0.05); } QScrollBar::handle:vertical { background: rgba(255,255,255,0.15); border-radius: 3px; } QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        left = QWidget()
        left.setFixedWidth(210)
        ll = QVBoxLayout()
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        # -- 抖音 --
        dy = QGroupBox("抖音")
        dyl = QVBoxLayout(); dyl.setSpacing(6)
        self.dy_status = QLabel("未登录")
        self.dy_status.setObjectName("infoLabel")
        self.dy_status.setCursor(Qt.PointingHandCursor)
        self.dy_status.installEventFilter(self)
        dyl.addWidget(self.dy_status)
        btn_dy = QPushButton("扫码提取")
        btn_dy.setObjectName("primaryBtn")
        btn_dy.clicked.connect(lambda: self._auto_fetch("douyin"))
        dyl.addWidget(btn_dy)
        self.btn_dy_clear = QPushButton("清理")
        self.btn_dy_clear.clicked.connect(lambda: self._clear_cookie("douyin"))
        dyl.addWidget(self.btn_dy_clear)
        self.dy_monitor = QPushButton("启动")
        self.dy_monitor.setObjectName("primaryBtn")
        self.dy_monitor.setFixedSize(50, 26)
        self.dy_monitor.setVisible(False)
        self.dy_monitor.clicked.connect(lambda: self._toggle_monitor("douyin"))
        dyl.addWidget(self.dy_monitor)
        dy.setLayout(dyl)
        ll.addWidget(dy)

        # -- B站 --
        bili = QGroupBox("B站")
        bl = QVBoxLayout(); bl.setSpacing(6)
        self.bili_status = QLabel("未登录")
        self.bili_status.setObjectName("infoLabel")
        self.bili_status.setCursor(Qt.PointingHandCursor)
        self.bili_status.installEventFilter(self)
        bl.addWidget(self.bili_status)
        btn_bili = QPushButton("扫码提取")
        btn_bili.setObjectName("primaryBtn")
        btn_bili.clicked.connect(lambda: self._auto_fetch("bilibili"))
        bl.addWidget(btn_bili)
        self.btn_bili_clear = QPushButton("清理")
        self.btn_bili_clear.clicked.connect(lambda: self._clear_cookie("bilibili"))
        bl.addWidget(self.btn_bili_clear)
        self.bili_monitor = QPushButton("启动")
        self.bili_monitor.setObjectName("primaryBtn")
        self.bili_monitor.setFixedSize(50, 26)
        self.bili_monitor.setVisible(False)
        self.bili_monitor.clicked.connect(lambda: self._toggle_monitor("bilibili"))
        bl.addWidget(self.bili_monitor)
        bili.setLayout(bl)
        ll.addWidget(bili)

        # -- 小红书 -- (Web私信API不可用，保留登录入口)
        xhs = QGroupBox("小红书")
        xhsl = QVBoxLayout(); xhsl.setSpacing(6)
        self.xhs_status = QLabel("未登录")
        self.xhs_status.setObjectName("infoLabel")
        self.xhs_status.setCursor(Qt.PointingHandCursor)
        self.xhs_status.installEventFilter(self)
        xhsl.addWidget(self.xhs_status)
        xhs_note = QLabel("Web私信API不可用\n详见 docs/XHS_IM_逆向日志.md")
        xhs_note.setStyleSheet("color: rgba(255,255,255,0.25); font-size: 10px; background: transparent;")
        xhsl.addWidget(xhs_note)
        self.btn_xhs_clear = QPushButton("清理")
        self.btn_xhs_clear.clicked.connect(lambda: self._clear_cookie("xiaohongshu"))
        xhsl.addWidget(self.btn_xhs_clear)
        xhs.setLayout(xhsl)
        ll.addWidget(xhs)

        # -- 快手 -- (Web端不支持私信，保留登录入口)
        ks = QGroupBox("快手")
        ksl = QVBoxLayout(); ksl.setSpacing(6)
        self.ks_status = QLabel("未登录")
        self.ks_status.setObjectName("infoLabel")
        self.ks_status.setCursor(Qt.PointingHandCursor)
        self.ks_status.installEventFilter(self)
        ksl.addWidget(self.ks_status)
        btn_ks = QPushButton("扫码提取")
        btn_ks.setObjectName("primaryBtn")
        btn_ks.clicked.connect(lambda: self._auto_fetch("kuaishou"))
        ksl.addWidget(btn_ks)
        self.btn_ks_clear = QPushButton("清理")
        self.btn_ks_clear.clicked.connect(lambda: self._clear_cookie("kuaishou"))
        ksl.addWidget(self.btn_ks_clear)
        self.ks_monitor = QPushButton("启动")
        self.ks_monitor.setObjectName("primaryBtn")
        self.ks_monitor.setFixedSize(50, 26)
        self.ks_monitor.setVisible(False)
        self.ks_monitor.clicked.connect(lambda: self._toggle_monitor("kuaishou"))
        ksl.addWidget(self.ks_monitor)
        ks.setLayout(ksl)
        ll.addWidget(ks)

        # 自动监听
        self.auto_monitor = QCheckBox("登录后自动监听")
        self.auto_monitor.setObjectName("monitorCheck")
        ll.addWidget(self.auto_monitor)
        self.auto_hint = QLabel("勾选后登录即自动开始监听，每 3 秒轮询一次新私信")
        self.auto_hint.setWordWrap(True)
        self.auto_hint.setStyleSheet("color: rgba(255,255,255,0.30); font-size: 10px; padding-left: 22px; background: transparent;")
        ll.addWidget(self.auto_hint)
        ll.addStretch()
        left.setLayout(ll)
        left_scroll.setWidget(left)

        # === 右列：二维码嵌入区 / 说明页 ===
        self._right_stack = QStackedWidget()
        self._right_stack.setStyleSheet("background: transparent;")

        # 第 0 页：说明
        right = QGroupBox("说明")
        rl = QVBoxLayout()
        rl.setSpacing(6)
        info = QLabel(
            "抖音/B站：点击「扫码提取」→ 右侧显示二维码 → 手机扫码\n"
            "扫码成功后自动保存 Cookie\n"
            "\n"
            "登录后点击「启动」开始监听\n"
            "Cookie 保存在本地，不会上传"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 12px; background: transparent; line-height: 1.6;")
        rl.addWidget(info)
        rl.addStretch()
        right.setLayout(rl)
        self._right_stack.addWidget(right)  # index 0

        # 第 1 页：二维码内嵌显示
        qr_card = QWidget()
        self._qr_card_layout = QVBoxLayout(qr_card)
        self._qr_card_layout.setAlignment(Qt.AlignCenter)
        self._qr_card_layout.setSpacing(16)

        self._qr_spinner = _SpinningIcon("⏳", size=48, color="#ff6b6b")
        self._qr_card_layout.addWidget(self._qr_spinner, alignment=Qt.AlignCenter)

        self._qr_status = QLabel("准备扫码...")
        self._qr_status.setAlignment(Qt.AlignCenter)
        self._qr_status.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 13px;")
        self._qr_card_layout.addWidget(self._qr_status)

        self._qr_container = QWidget()
        self._qr_container.setFixedSize(200, 200)
        self._qr_container.setStyleSheet("background: white; border-radius: 14px;")
        self._qr_container.hide()
        qr_container_layout = QVBoxLayout(self._qr_container)
        qr_container_layout.setContentsMargins(10, 10, 10, 10)
        self._qr_inline_label = QLabel()
        self._qr_inline_label.setAlignment(Qt.AlignCenter)
        qr_container_layout.addWidget(self._qr_inline_label)
        self._qr_card_layout.addWidget(self._qr_container, alignment=Qt.AlignCenter)

        self._qr_hint_inline = QLabel()
        self._qr_hint_inline.setAlignment(Qt.AlignCenter)
        self._qr_hint_inline.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px;")
        self._qr_card_layout.addWidget(self._qr_hint_inline)

        self._qr_rotate_anim = QPropertyAnimation(self._qr_spinner, b"angle")
        self._qr_rotate_anim.setDuration(2000)
        self._qr_rotate_anim.setStartValue(0)
        self._qr_rotate_anim.setEndValue(360)
        self._qr_rotate_anim.setLoopCount(-1)

        self._right_stack.addWidget(qr_card)  # index 1
        self._right_stack.setCurrentIndex(0)

        main.addWidget(left_scroll)
        main.addWidget(self._right_stack, stretch=1)
        self.setLayout(main)

    def _toggle_monitor(self, platform: str):
        running = {"douyin": self._dy_running,
                   "bilibili": self._bili_running,
                   "kuaishou": self._ks_running}.get(platform, False)
        if running:
            self.stop_monitor.emit(platform)
        else:
            self.start_monitor.emit(platform)

    def set_monitor_running(self, platform: str, running: bool):
        if platform == "douyin":
            self._dy_running = running
            self.dy_monitor.setText("停止" if running else "启动")
        elif platform == "bilibili":
            self._bili_running = running
            self.bili_monitor.setText("停止" if running else "启动")
        elif platform == "kuaishou":
            self._ks_running = running
            self.ks_monitor.setText("停止" if running else "启动")

    def on_connected(self, platform: str):
        if platform == "douyin":
            self._has_dy = True
            self.dy_monitor.setVisible(True)
        elif platform == "bilibili":
            self._has_bili = True
            self.bili_monitor.setVisible(True)
        elif platform == "kuaishou":
            self._has_ks = True
            self.ks_monitor.setVisible(True)

    def on_disconnected(self, platform: str):
        if platform == "douyin":
            self._has_dy = False
            self.dy_monitor.setVisible(False)
        elif platform == "bilibili":
            self._has_bili = False
            self.bili_monitor.setVisible(False)
        elif platform == "kuaishou":
            self._has_ks = False
            self.ks_monitor.setVisible(False)

    def _auto_fetch(self, platform: str):
        if self._worker and self._worker.isRunning():
            status_map = {"douyin": self.dy_status, "bilibili": self.bili_status, "kuaishou": self.ks_status}
            if platform in status_map:
                status_map[platform].setText("请完成当前扫码操作")
            return
        self._stop_worker()

        cfg = database.load_config()
        has_cookie = {
            "douyin": bool(cfg.douyin_cookie),
            "bilibili": bool(cfg.bilibili_sessdata),
            "kuaishou": bool(cfg.ks_cookie),
        }.get(platform, False)
        if has_cookie:
            self._clear_cookie(platform)

        status_map = {"douyin": self.dy_status, "bilibili": self.bili_status, "kuaishou": self.ks_status}
        if platform in status_map:
            status_map[platform].setText("请扫码登录...")

        self._qr_container.hide()
        while self._qr_card_layout.count() > 5:
            item = self._qr_card_layout.takeAt(5)
            if item.widget():
                item.widget().deleteLater()
        self._qr_rotate_anim.start()
        self._qr_spinner.show()
        self._qr_status.setText("正在启动浏览器...")
        self._qr_status.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 13px;")
        self._qr_hint_inline.setText("")
        self._right_stack.setCurrentIndex(1)

        self._worker = LoginWorker(platform)
        self._worker.result.connect(self._on_cookie_ready)
        if platform == "xiaohongshu":
            if hasattr(self, 'xhs_status'):
                self._worker.xhs_qr_ready.connect(self._on_xhs_qr_ready)
        elif platform == "douyin":
            self._worker.dy_qr_ready.connect(self._on_dy_qr_ready)
        elif platform == "bilibili":
            self._worker.bili_qr_ready.connect(self._on_bili_qr_ready)
        self._worker.start()

    def _on_xhs_qr_ready(self, png_bytes):
        if not hasattr(self, 'xhs_status'): return
        if self._qr_dialog:
            self._qr_dialog.close()
        if png_bytes:
            self._qr_dialog = _QRDialog("小红书", self)
            self._qr_dialog.set_qr_image(png_bytes)
            self._qr_dialog.show()
            self.xhs_status.setText("请扫码登录...")
        else:
            self.xhs_status.setText("请在浏览器中扫码...")

    def _on_dy_qr_ready(self, b64_data):
        self._qr_rotate_anim.stop()
        self._qr_spinner.hide()
        self._qr_status.setText("请使用抖音APP扫描")
        self._qr_hint_inline.setText("扫码后在手机上确认登录")
        try:
            if b64_data.startswith("data:image/"):
                _, encoded = b64_data.split(",", 1)
                img_bytes = base64.b64decode(encoded)
            else:
                img_bytes = b64_data.encode() if isinstance(b64_data, str) else b64_data
            pixmap = QPixmap()
            if pixmap.loadFromData(img_bytes, 'PNG'):
                self._qr_inline_label.setPixmap(
                    pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self._qr_container.show()
        except Exception:
            pass
        self.dy_status.setText("请扫码登录...")

    def _on_bili_qr_ready(self, b64_data):
        self._qr_rotate_anim.stop()
        self._qr_spinner.hide()
        self._qr_status.setText("请使用B站APP扫描")
        self._qr_hint_inline.setText("扫码后确认登录")
        try:
            if isinstance(b64_data, str) and b64_data.startswith("data:image/"):
                _, encoded = b64_data.split(",", 1)
                img_bytes = base64.b64decode(encoded)
            else:
                img_bytes = b64_data if isinstance(b64_data, bytes) else b64_data.encode()
            pixmap = QPixmap()
            if pixmap.loadFromData(img_bytes, 'PNG'):
                self._qr_inline_label.setPixmap(
                    pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self._qr_container.show()
        except Exception:
            pass
        self.bili_status.setText("请扫码登录...")

    def _stop_worker(self):
        if self._worker:
            try: self._worker.result.disconnect()
            except Exception: pass
            try: self._worker.xhs_qr_ready.disconnect()
            except (Exception, RuntimeError): pass
            try: self._worker.dy_qr_ready.disconnect()
            except (Exception, RuntimeError): pass
            try: self._worker.bili_qr_ready.disconnect()
            except (Exception, RuntimeError): pass
            if self._worker.isRunning():
                self._worker.stop()
        self._worker = None

    def _on_cookie_ready(self, platform: str, cookies):
        if self._qr_dialog:
            self._qr_dialog.fade_out()
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(600, lambda: setattr(self, '_qr_dialog', None))

        self._stop_worker()
        if platform == "douyin":
            if cookies and isinstance(cookies, dict) and cookies.get("cookie"):
                database.update_config_field("douyin_cookie", cookies["cookie"])
                wp = cookies.get("web_protect", "")
                if wp:
                    database.update_config_field("douyin_web_protect", wp)
                keys_v = cookies.get("keys", "")
                if keys_v:
                    database.update_config_field("douyin_keys", keys_v)
                self.dy_status.setText("已保存，自动登录中...")
                self.connect_platform.emit("douyin")
            else:
                self.dy_status.setText("未登录，请重试")
        elif platform == "bilibili":
            if cookies and isinstance(cookies, dict) and cookies.get("SESSDATA"):
                database.update_config_field("bilibili_sessdata", cookies["SESSDATA"])
                database.update_config_field("bilibili_jct", cookies.get("bili_jct", ""))
                database.update_config_field("bilibili_buvid3", cookies.get("buvid3", ""))
                database.update_config_field("bilibili_buvid4", cookies.get("buvid4", ""))
                database.update_config_field("bilibili_dedeuserid", cookies.get("dedeuserid", ""))
                database.update_config_field("bilibili_ac_time_value", cookies.get("ac_time_value", ""))
                self.bili_status.setText("已保存，自动登录中...")
                self.connect_platform.emit("bilibili")
            else:
                self.bili_status.setText("未登录，请重试")
        elif platform == "kuaishou":
            if cookies and isinstance(cookies, dict):
                database.update_config_field("ks_cookie", json.dumps(cookies, ensure_ascii=False))
                self.ks_status.setText("已保存，自动登录中...")
                self.connect_platform.emit("kuaishou")
            else:
                self.ks_status.setText("未登录，请重试")

        self._right_stack.setCurrentIndex(0)
        self._qr_rotate_anim.stop()
        while self._qr_card_layout.count() > 5:
            item = self._qr_card_layout.takeAt(5)
            if item.widget():
                item.widget().deleteLater()

    def _clear_cookie(self, platform: str):
        cfg = database.load_config()
        if platform == "douyin":
            cfg.douyin_cookie = ""
            cfg.douyin_web_protect = ""
            cfg.douyin_keys = ""
            self.dy_status.setText("已清理")
            self.dy_monitor.setVisible(False)
            self._dy_running = False
        elif platform == "bilibili":
            cfg.bilibili_sessdata = ""
            cfg.bilibili_jct = ""
            self.bili_status.setText("已清理")
            self.bili_monitor.setVisible(False)
            self._bili_running = False
        elif platform == "kuaishou":
            cfg.ks_cookie = ""
            self.ks_status.setText("已清理")
            self.ks_monitor.setVisible(False)
            self._ks_running = False
        database.save_config(cfg)
        self.clear_platform.emit(platform)

    def set_status(self, platform: str, text: str):
        if platform == "douyin":
            self.dy_status.setText(text)
        elif platform == "bilibili":
            self.bili_status.setText(text)
        elif platform == "kuaishou":
            self.ks_status.setText(text)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            status_map = {
                self.dy_status: "douyin", self.bili_status: "bilibili",
                self.ks_status: "kuaishou"
            }
            platform = status_map.get(obj)
            if platform:
                self._toggle_monitor(platform)
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)