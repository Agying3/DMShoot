#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DMShoot 渲染帧率探针（独立脚本，不修改项目源码）

用途：用与聊天列表相同的渲染方式（半透明圆角气泡 + 头像 + 阴影 + 连续滚动），
      在你本机实测 Qt Widgets 软件光栅化下的真实帧率，作为性能优化基线。

用法：用你运行 DMShoot 的同一个 python 跑（需已装 PySide6）
      python tools/fps_probe.py            # 默认 500 条
      python tools/fps_probe.py 2000       # 模拟超长会话
      python tools/fps_probe.py 50         # 模拟短会话

输出：控制台每秒打印一行 [FPS] 近似值。窗口会自动持续滚动以制造渲染负载。
注意：这是"相同渲染方式"的近似实测，不是 DMShoot 真实运行时的帧率（真实值还受
      实际消息结构、图片缩略图、AI 回调等影响），但能反映当前架构在你机器上的上限。
"""
import sys

from PySide6.QtWidgets import (
    QApplication, QScrollArea, QWidget, QVBoxLayout, QLabel
)
from PySide6.QtCore import QElapsedTimer, QTimer, Qt
from PySide6.QtGui import QPainter, QColor, QFont, QPen


N = int(sys.argv[1]) if len(sys.argv) > 1 else 500


class FPSMeter:
    """每秒统计一次 paintEvent 调用次数，近似 FPS（每帧至少一次 paint）。"""
    def __init__(self):
        self.n = 0
        self.t = QElapsedTimer()
        self.t.start()

    def tick(self):
        self.n += 1
        dt = self.t.elapsed()
        if dt >= 1000:
            fps = self.n / (dt / 1000.0)
            print("[FPS] ~%.1f  (frames=%d, dt=%dms, N=%d)" % (fps, self.n, dt, N))
            self.n = 0
            self.t.restart()


METER = FPSMeter()


class Bubble(QWidget):
    """模拟一条聊天气泡：头像 + 半透明圆角气泡 + 阴影 + 文本。"""
    def __init__(self, i):
        super().__init__()
        self.setFixedHeight(56)
        self.text = "消息%d: " % i + \
            "这是一条较长的私信内容用于模拟真实聊天气泡的渲染负担。" * (i % 3 + 1)

    def paintEvent(self, event):
        METER.tick()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 头像（圆角方块）
        p.setBrush(QColor(120, 120, 140))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(6, 8, 36, 36, 18, 18)
        # 气泡（半透明深色圆角矩形，模拟 QSS 圆角 + rgba 背景）
        p.setBrush(QColor(24, 37, 51, 235))
        r = QRect(50, 8, self.width() - 62, 40)
        p.drawRoundedRect(r, 13, 13)
        # 文本
        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(QFont("Segoe UI", 12))
        p.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignVCenter, self.text[:42])


def main():
    app = QApplication(sys.argv)
    scroll = QScrollArea()
    scroll.setWindowTitle("DMShoot FPS 探针 (N=%d)" % N)
    scroll.resize(420, 760)

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setSpacing(2)
    layout.setContentsMargins(8, 8, 8, 8)
    for i in range(N):
        layout.addWidget(Bubble(i))
    layout.addStretch()

    scroll.setWidget(container)
    scroll.show()

    # 自动滚动，制造持续渲染负载
    sb = scroll.verticalScrollBar()

    def do_scroll():
        v = sb.value() + 6
        if v > sb.maximum():
            v = 0
        sb.setValue(v)

    timer = QTimer(scroll)
    timer.timeout.connect(do_scroll)
    timer.start(16)  # ~60Hz 滚动驱动

    print("探针启动，N=%d。Ctrl+C 或关闭窗口退出。每秒输出一次 FPS。" % N)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
