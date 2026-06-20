"""
斜线进度条 - 连续 //// 纹理，不分格
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen


class GlowProgressBar(QWidget):
    """斜线进度条

    整个长条画连续 //// 斜线纹理，前段有色后段淡，不分格。

    用法:
        bar = GlowProgressBar(self)
        bar.setValue(68)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._target_value = 0
        self._smooth_value = 0.0

        self._fill_color = QColor(240, 192, 96)         # DMShoot 金
        self._empty_color = QColor(255, 255, 255, 25)    # 极淡白
        self._bg_color = QColor(255, 255, 255, 8)
        self._text_color = QColor(255, 255, 255, 160)

        self._line_width = 1.0
        self._line_spacing = 3          # 密排斜线

        # 圆角 (0=直角, -1=自动胶囊半高)
        self._radius = -1

        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._on_tick)
        # 不自动启动，只在 setValue 需要动画时启动

        self.setMinimumSize(200, 20)

    # ====== API ======

    def value(self) -> int:
        return self._value

    def setValue(self, v: int):
        self._target_value = max(0, min(100, v))
        if not self._ticker.isActive():
            self._ticker.start()

    def setValueNow(self, v: int):
        self._value = max(0, min(100, v))
        self._target_value = self._value
        self._smooth_value = self._value
        self.update()

    def setColor(self, c: QColor):
        self._fill_color = c
        self.update()

    def setLineSpacing(self, s: int):
        self._line_spacing = max(2, s)
        self.update()

    def setRadius(self, r: int):
        """-1=自动胶囊, 0=直角, >0=自定义圆角"""
        self._radius = max(-1, r)
        self.update()

    # ====== tick ======

    def _on_tick(self):
        diff = self._target_value - self._smooth_value
        if abs(diff) < 0.15:
            self._value = self._target_value
            self._smooth_value = self._target_value
            self._ticker.stop()
        else:
            self._smooth_value += diff * 0.12
            self._value = round(self._smooth_value)
        self.update()

    # ====== 绘制 ======

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        bar_rect = QRectF(2, 4, w - 4, h - 8)
        r = bar_rect.height() / 2 if self._radius < 0 else self._radius
        fill_w = bar_rect.width() * (self._value / 100.0)

        # --- 整体圆角裁剪 ---
        from PySide6.QtGui import QPainterPath
        bar_path = QPainterPath()
        bar_path.addRoundedRect(bar_rect, r, r)

        p.save()
        p.setClipPath(bar_path)

        # --- 1. 底 ---
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._bg_color)
        p.drawPath(bar_path)

        # --- 2. 后段淡斜线 ---
        self._drawStripes(p, bar_rect, self._empty_color, left_clip=fill_w)

        # --- 3. 前段有色斜线 ---
        self._drawStripes(p, bar_rect, self._fill_color, right_clip=fill_w)

        p.restore()

        # --- 4. 细边框 ---
        p.setPen(QPen(QColor(255, 255, 255, 30), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(bar_rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)

        # --- 5. 百分比 ---
        if self._value > 0:
            font = QFont("Microsoft YaHei", 10, QFont.Weight.Bold)
            p.setFont(font)
            p.setPen(self._text_color)
            p.drawText(QRectF(0, 0, w, h),
                       Qt.AlignmentFlag.AlignCenter, f"{self._value}%")

        p.end()

    def _drawStripes(self, p, bar_rect, color, left_clip=None, right_clip=None):
        """画一组斜线条纹，裁剪边界跟随斜线角度"""
        p.save()

        bh = bar_rect.height()
        x0, y0 = bar_rect.x(), bar_rect.y()
        bw = bar_rect.width()
        x1 = x0 + bw
        y1 = y0 + bh

        # 构建裁剪多边形 (边界线是斜的，与条纹同向)
        from PySide6.QtGui import QPainterPath
        clip_path = QPainterPath()

        if left_clip is not None:
            # 后段: 从斜线边界到右端
            fill_x = x0 + left_clip
            clip_path.moveTo(fill_x, y0)               # 左上
            clip_path.lineTo(x1, y0)                    # 右上
            clip_path.lineTo(x1, y1)                    # 右下
            clip_path.lineTo(fill_x + bh, y1)           # 左下 (斜线)
            clip_path.closeSubpath()
        elif right_clip is not None:
            # 前段: 从左端到斜线边界
            fill_x = x0 + right_clip
            clip_path.moveTo(x0, y0)                    # 左上
            clip_path.lineTo(fill_x, y0)                # 右上
            clip_path.lineTo(fill_x + bh, y1)           # 右下 (斜线)
            clip_path.lineTo(x0, y1)                    # 左下
            clip_path.closeSubpath()
        else:
            clip_path.addRect(bar_rect)

        p.setClipPath(clip_path)

        # 底色
        if left_clip is not None or right_clip is not None:
            bg = QColor(color.red(), color.green(), color.blue(), 25)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawPath(clip_path)

        # 画斜线 (左上→右下)
        p.setPen(QPen(color, self._line_width))
        step = self._line_spacing
        start_x = bar_rect.x() - bh * 2
        end_x = bar_rect.right() + bh

        x = start_x
        while x < end_x:
            p.drawLine(
                QPointF(x, y0),
                QPointF(x + bh, y1)
            )
            x += step

        p.restore()

    def sizeHint(self):
        return self.minimumSize()

    def minimumSizeHint(self):
        return self.minimumSize()


# ================================================================
#  测试入口
# ================================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QVBoxLayout,
        QSlider, QLabel, QHBoxLayout, QComboBox
    )
    from PySide6.QtCore import Qt as QCore_Qt

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = QMainWindow()
    win.setWindowTitle("斜线进度条 //////")
    win.setStyleSheet("""
        QMainWindow { background-color: #12121f; }
        QLabel { color: #aaa; font-size: 13px; }
        QSlider::groove:horizontal {
            background: rgba(255,255,255,0.06); height: 6px; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #55aaff; width: 16px; height: 16px;
            margin: -5px 0; border-radius: 8px;
        }
        QComboBox {
            background: rgba(255,255,255,0.06); color: #ccc;
            border: 1px solid rgba(255,255,255,0.10); border-radius: 6px;
            padding: 6px 14px; font-size: 13px;
        }
        QComboBox QAbstractItemView {
            background: #1a1a30; color: #ccc;
            selection-background-color: #3388cc;
        }
    """)

    from PySide6.QtWidgets import QWidget as W
    cw = W()
    layout = QVBoxLayout(cw)
    layout.setContentsMargins(40, 36, 40, 36)
    layout.setSpacing(18)

    t = QLabel("斜线进度条  (连续 //// 不分格)")
    t.setStyleSheet("font-size:18px;font-weight:bold;color:#d0d0d0;")
    layout.addWidget(t)

    layout.addWidget(QLabel("蓝色 · 线距 5px"))
    b1 = GlowProgressBar()
    b1.setValue(68)
    layout.addWidget(b1)

    layout.addWidget(QLabel("青绿色 · 线距 4px"))
    b2 = GlowProgressBar()
    b2.setColor(QColor(0, 210, 170))
    b2.setLineSpacing(4)
    b2.setValue(42)
    layout.addWidget(b2)

    layout.addWidget(QLabel("橙粉色 · 线距 7px"))
    b3 = GlowProgressBar()
    b3.setColor(QColor(255, 120, 70))
    b3.setLineSpacing(7)
    b3.setValue(85)
    layout.addWidget(b3)

    layout.addWidget(QLabel("金色 · 线距 3px 密排"))
    b4 = GlowProgressBar()
    b4.setColor(QColor(255, 200, 50))
    b4.setLineSpacing(3)
    b4.setValue(55)
    layout.addWidget(b4)

    layout.addSpacing(12)
    layout.addWidget(QLabel("交互控制"))
    b5 = GlowProgressBar()
    b5.setValue(50)
    layout.addWidget(b5)

    sr = QHBoxLayout()
    sl = QLabel("进度: 50%")
    s = QSlider(QCore_Qt.Orientation.Horizontal)
    s.setRange(0, 100)
    s.setValue(50)
    s.valueChanged.connect(lambda v: b5.setValue(v))
    s.valueChanged.connect(lambda v: sl.setText(f"进度: {v}%"))
    sr.addWidget(sl)
    sr.addWidget(s)
    layout.addLayout(sr)

    combo = QComboBox()
    combo.addItems(["蓝色", "青绿", "橙粉", "金色", "紫色"])
    colors = [
        QColor(80, 180, 255), QColor(0, 210, 170),
        QColor(255, 120, 70), QColor(255, 200, 50),
        QColor(160, 100, 255),
    ]
    combo.currentIndexChanged.connect(lambda i: b5.setColor(colors[i]))
    hr = QHBoxLayout()
    hr.addWidget(QLabel("颜色:"))
    hr.addWidget(combo)
    hr.addStretch()
    layout.addLayout(hr)

    layout.addStretch()
    win.setCentralWidget(cw)
    win.resize(620, 520)
    win.show()
    sys.exit(app.exec())
