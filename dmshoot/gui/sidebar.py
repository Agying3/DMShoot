"""侧边栏导航 — 状态点阵放在上方，避免底部圆角裁切"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Signal, Qt

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
        self.set_active("home")

    def set_active(self, key: str):
        for k, btn in self._buttons.items():
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setStyleSheet(btn.styleSheet())

    def _on_click(self, key: str):
        self.set_active(key)
        self.page_changed.emit(key)

    def update_status(self, platform: str, status: str):
        """更新侧边栏平台状态（关键词 → 点阵四态）"""
        row = self._status_rows.get(platform)
        if not row:
            return
        text = str(status or "")
        if any(kw in text for kw in ["认证失败", "过期", "未登录", "Cookie"]):
            row.set_status("error")
        elif any(kw in text for kw in ["连接中", "启动", "正在", "等待", "自动登录中", "同步"]):
            row.set_status("connecting")
        elif text.strip() in ("online", "●", "✓") or any(kw in text for kw in ["已连接", "在线", "connected"]):
            row.set_status("online")
        else:
            row.set_status("offline")

    def update_ai_status(self, text: str):
        self.status_ai.setText(f"AI {text}")
