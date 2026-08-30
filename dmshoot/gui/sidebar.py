"""侧边栏导航 — 状态点阵放在上方，避免底部圆角裁切"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QFrame
from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRect, QTimer, Signal, Qt,
)

from dmshoot.gui.widgets.platform_status import PlatformStatusRow


class Sidebar(QWidget):
    """左侧导航栏"""

    page_changed = Signal(str)  # page_key

    def __init__(self):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(90)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)

        # 标题
        logo = QLabel("DMShoot")
        logo.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #FFD580; "
            "background:transparent; padding: 4px 0 6px 0;"
        )
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        # ── 状态点阵（顶部，远离底部圆角）──
        self.status_dy = PlatformStatusRow("抖音")
        self.status_bili = PlatformStatusRow("B站")
        self.status_xhs = PlatformStatusRow("小红书")
        self.status_ks = PlatformStatusRow("快手")
        self.status_ai = QLabel("AI ✕")
        self._status_rows = {
            "douyin": self.status_dy, "bilibili": self.status_bili,
            "xiaohongshu": self.status_xhs, "kuaishou": self.status_ks,
        }
        for row in [self.status_dy, self.status_bili, self.status_xhs, self.status_ks]:
            layout.addWidget(row)
        self.status_ai.setObjectName("statusLabel")
        self.status_ai.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.status_ai)

        # 分隔
        sep = QLabel("")
        sep.setFixedHeight(4)
        layout.addWidget(sep)

        # 导航按钮
        self._buttons: dict[str, QPushButton] = {}
        pages = [
            ("home", "首页"),
            ("login", "登录"),
            ("deepseek", "AI"),
            ("prompt", "提示词"),
        ]

        for key, label in pages:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.clicked.connect(lambda checked, k=key: self._on_click(k))
            layout.addWidget(btn)
            self._buttons[key] = btn

        layout.addStretch()

        self.setLayout(layout)
        self._active_key = ""
        self._indicator_pending_animation = False
        self._indicator = QFrame(self)
        self._indicator.setObjectName("navIndicator")
        self._indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._indicator.hide()
        self._indicator_animation = QPropertyAnimation(
            self._indicator, b"geometry", self
        )
        self._indicator_animation.setDuration(150)
        self._indicator_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.set_active("home")

    def set_active(self, key: str):
        if key not in self._buttons:
            return
        changed = key != self._active_key
        self._active_key = key
        for k, btn in self._buttons.items():
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setStyleSheet(btn.styleSheet())
        self._indicator_pending_animation = changed and self.isVisible()
        QTimer.singleShot(0, self._sync_indicator)

    def _sync_indicator(self):
        btn = self._buttons.get(self._active_key)
        if btn is None or btn.height() <= 0:
            return
        top_left = btn.mapTo(self, QPoint(0, 0))
        target = QRect(2, top_left.y() + 6, 3, max(12, btn.height() - 12))
        animate = self._indicator_pending_animation and self._indicator.isVisible()
        self._indicator_pending_animation = False
        self._indicator_animation.stop()
        if animate:
            self._indicator_animation.setStartValue(self._indicator.geometry())
            self._indicator_animation.setEndValue(target)
            self._indicator_animation.start()
        else:
            self._indicator.setGeometry(target)
        self._indicator.show()
        self._indicator.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._indicator_pending_animation = False
        QTimer.singleShot(0, self._sync_indicator)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_indicator)

    def _on_click(self, key: str):
        self.set_active(key)
        self.page_changed.emit(key)

    def update_status(self, platform: str, status: str):
        """更新侧边栏平台状态（关键词 → 点阵四态）"""
        row = self._status_rows.get(platform)
        if not row:
            return
        text = str(status or "")
        lower = text.lower()
        if (any(kw in text for kw in ["认证失败", "过期", "未登录", "Cookie", "失效"])
                or any(kw in lower for kw in ["error", "failed", "unauthorized"])):
            row.set_status("error", text)
        elif any(kw in text for kw in ["重连", "断线恢复", "稍后重试", "重试间隔"]):
            row.set_status("reconnecting", text)
        elif any(kw in text for kw in ["连接中", "启动", "正在", "等待", "自动登录中", "同步"]):
            row.set_status("connecting", text)
        elif (text.strip() in ("online", "●", "✓")
              or any(kw in text for kw in ["已连接", "在线", "connected"])):
            row.set_status("online", text)
        else:
            row.set_status("offline", text)

    def update_ai_status(self, text: str):
        self.status_ai.setText(f"AI {text}")
