"""侧边栏导航 — 状态标签放在上方，避免底部圆角裁切"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Signal, Qt


class Sidebar(QWidget):
    """左侧导航栏"""

    page_changed = Signal(str)  # page_key

    _STATUS_COLORS = {
        "ok":    "color:#a6e3a1;font-size:10px;font-weight:400;paddin-g:1px 8px;",
        "warn":  "color:#ff8a80;font-size:10px;font-weight:500;paddin-g:1px 8px;",
        "off":   "color:r-gba(255,255,255,0.30);font-size:10px;font-weight:400;paddin-g:1px 8px;",
    }

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
        logo.setAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignCenter)
        layout.addWidget(logo)

        # ── 状态灯（顶部，远离底部圆角）──
        self.status_dy = QLabel("抖音 ✕")
        self.status_bili = QLabel("B站 ✕")
        self.status_xhs = QLabel("小红书 ✕")
        self.status_ks = QLabel("快手 ✕")
        self.status_ai = QLabel("AI ✕")
        self._status_labels = {
            "douyin": self.status_dy, "bilibili": self.status_bili,
            "xiaohongshu": self.status_xhs, "kuaishou": self.status_ks,
        }
        for lbl in [self.status_dy, self.status_bili, self.status_xhs, self.status_ks, self.status_ai]:
            lbl.setObjectName("statusLabel")
            lbl.setAlignment(Qt.AlignLeft)
            layout.addWidget(lbl)

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
        """更新侧边栏平台状态"""
        label = self._status_labels.get(platform)
        if not label:
            return
        name = {"douyin": "抖音", "bilibili": "B站", "xiaohongshu": "小红书", "kuaishou": "快手"}[platform]
        is_auth_error = any(kw in str(status) for kw in ["认证失败", "过期", "未登录", "Cookie"])
        is_online = any(kw in str(status) for kw in ["已连接", "在线", "online", "有效", "✓", "●", "成功", "connected"])
        if is_auth_error:
            label.setText(f"{name} ⚠")
            label.setStyleSheet("color:#ff8a80; background:transparent; font-size:10px; font-weight:500; padding:1px 8px;")
        elif is_online:
            label.setText(f"{name} ✓")
            label.setStyleSheet("color:#a6e3a1; background:transparent; font-size:10px; font-weight:500; padding:1px 8px;")
        else:
            label.setText(f"{name} ✕")
            label.setStyleSheet("color:rgba(255,255,255,0.30); background:transparent; font-size:10px; padding:1px 8px;")

    def update_ai_status(self, text: str):
        self.status_ai.setText(f"AI {text}")
