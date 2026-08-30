"""平台状态点阵指示器 — 2×2 点阵，自绘 + QTimer 驱动

状态语义（set_status 接收五态字符串）:
  online      → 4 点全亮，整体微呼吸
  connecting  → 对角两两反相呼吸
  reconnecting → 4 点顺序追逐
  error       → 第 1 点红色闪烁，其余暗红
  offline     → 4 点暗灰静止
"""

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

COLOR = {
    "online":     QColor("#97C459"),
    "connecting": QColor("#EF9F27"),
    "reconnecting": QColor("#F97316"),
    "error":      QColor("#E24B4A"),
    "offline":    QColor("#888780"),
}

STATUS_TEXT = {
    "online": "在线",
    "connecting": "连接中",
    "reconnecting": "重连中",
    "error": "登录失效或连接错误",
    "offline": "未连接",
}


class StatusDots(QWidget):
    """2×2 点阵本体"""

    DOT = 5   # 单点边长
    GAP = 4   # 点间距
    M = 2     # 边距

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = "offline"
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        size = self.DOT * 2 + self.GAP + self.M * 2
        self.setFixedSize(size, size)

    def set_status(self, status: str, msg: str = ""):
        self._status = status if status in COLOR else "offline"
        self.setToolTip(msg or STATUS_TEXT[self._status])
        self._frame = 0
        self._timer.stop()
        if self._status in ("connecting", "reconnecting", "online"):
            self._timer.start(120)
        elif self._status == "error":
            self._timer.start(400)
        self.update()

    def _tick(self):
        self._frame += 1
        self.update()

    def _alphas(self) -> list:
        f, s = self._frame, self._status
        if s == "online":
            t = 0.85 + 0.15 * math.sin(f * 0.15)
            return [t] * 4
        if s == "connecting":
            ph = (math.sin(f * 0.13) + 1) / 2
            return [0.35 + 0.65 * ph, 0.35 + 0.65 * (1 - ph),
                    0.35 + 0.65 * (1 - ph), 0.35 + 0.65 * ph]
        if s == "reconnecting":
            active = f % 4
            return [1.0 if i == active else (0.55 if i == (active - 1) % 4 else 0.2)
                    for i in range(4)]
        if s == "error":
            blink = 0.95 if (f // 2) % 2 == 0 else 0.15
            return [blink, 0.22, 0.22, 0.22]
        return [0.3, 0.3, 0.3, 0.3]

    def paintEvent(self, event):
        p = QPainter(self)
        base = COLOR[self._status]
        for (r, c), a in zip(((0, 0), (0, 1), (1, 0), (1, 1)), self._alphas()):
            color = QColor(base)
            color.setAlphaF(a)
            x = self.M + c * (self.DOT + self.GAP)
            y = self.M + r * (self.DOT + self.GAP)
            p.fillRect(x, y, self.DOT, self.DOT, color)
        p.end()


class PlatformStatusRow(QWidget):
    """点阵 + 平台名 一行，替换侧边栏旧的状态 QLabel"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._display_name = name
        self.dots = StatusDots()
        self.name = QLabel(name)
        self.name.setStyleSheet(
            "color:rgba(255,255,255,0.75);font-size:10px;background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 1, 0, 1)
        lay.setSpacing(5)
        lay.addWidget(self.dots)
        lay.addWidget(self.name)
        lay.addStretch()

    def set_status(self, status: str, msg: str = ""):
        self.dots.set_status(status, msg)
        state_text = STATUS_TEXT.get(status, STATUS_TEXT["offline"])
        detail = f"\n{msg}" if msg and msg != state_text else ""
        self.setToolTip(f"{self._display_name} · {state_text}{detail}")
