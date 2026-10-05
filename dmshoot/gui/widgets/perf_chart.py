"""性能图表 — QPainter 纯手绘 + 动画 + 双列布局"""
from PySide6.QtCore import (
    Qt, QTimer, QRect, QRectF, QPoint, QPointF, QPropertyAnimation,
    QEasingCurve, Property, Signal, QEvent, QVariantAnimation
)
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QRegion, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QCheckBox, QDialog, QFrame, QScrollArea, QSizePolicy,
)
from shiboken6 import isValid
from dmshoot.core.perf_monitor import get_monitor
import math

_SCHEMES = {
    "blue":   {"p": "#378add", "a": "#74c7ec", "g": 4, "t": 180},
    "teal":   {"p": "#1d9e75", "a": "#9fe1cb", "g": 4, "t": 180},
    "purple": {"p": "#7f77dd", "a": "#cecbf6", "g": 4, "t": 180},
    "orange": {"p": "#d85a30", "a": "#f5c4b3", "g": 4, "t": 180},
    "mono":   {"p": "#5f5e5a", "a": "#d3d1c7", "g": 4, "t": 180},
}
_BARC = ["#378add","#74c7ec","#a6e3a1","#fab387","#cba6f7","#f9e2af","#f38ba8"]

_CHART_NAMES = (
    "请求管道甘特图", "API 指标", "各平台消息速率",
    "时间分布", "线程 & 工作线程", "消息分析",
)
_CHART_SHORT_NAMES = ("请求管道", "API 指标", "消息速率", "时间分布", "线程", "消息分析")
_PIE_COLORS = {
    "base": "#1A1B25", "sector": "#252630", "hover": "#34343F",
    "text": "#E6E3DD", "muted": "#9A98A1", "accent": "#F0C060",
}
_PIE_SURFACE_OPACITY = 0.94


class _PieTrigger(QPushButton):
    def __init__(self, selector):
        super().__init__(selector)
        self._selector = selector
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(200)
        self._hold_timer.timeout.connect(self._open_on_hold)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("选择性能图表")
        self.setToolTip("单击打开圆盘 · 长按拖动预览，松开确认")

    def hitButton(self, point):
        return math.hypot(point.x() - 22, point.y() - 22) <= 22

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton and self.hitButton(event.position().toPoint()):
            self._hold_timer.start()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._hold_timer.stop()
        super().mouseReleaseEvent(event)

    def _open_on_hold(self):
        if self.isVisible() and self.isEnabled():
            self.setDown(False)
            self._selector._popup.show_for(self, self._selector.currentIndex(), drag_select=True)

    def hideEvent(self, event):
        self._hold_timer.stop()
        self.setDown(False)
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._selector.colors()
        surface = QColor(colors["hover"] if self.underMouse() else colors["sector"])
        surface.setAlphaF(_PIE_SURFACE_OPACITY)
        painter.setBrush(surface)
        border = colors["accent"] if self.hasFocus() or self._selector._popup.isVisible() else colors["muted"]
        painter.setPen(QPen(QColor(border), 1.2))
        painter.drawEllipse(QRectF(1, 1, 42, 42))
        painter.setPen(Qt.NoPen)
        for index in range(6):
            color = QColor(colors["accent"] if index == self._selector._display_index() else colors["muted"])
            painter.setBrush(color)
            painter.drawPie(QRectF(12, 12, 20, 20), (120 - index * 60) * 16, -56 * 16)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class _ChartPiePopup(QWidget):
    chosen = Signal(int)

    def __init__(self, selector):
        super().__init__(selector, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("ChartPiePopup")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setAccessibleName("性能图表圆盘菜单")
        self._selector = selector
        self._current_index = 0
        self._focus_index = 0
        self._drag_selecting = False
        self._hover_index = -1
        self._hover_levels = [0.0] * 6
        self._hover_from = self._hover_levels.copy()
        self._hover_to = self._hover_levels.copy()
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(140)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.setStartValue(0.0)
        self._hover_animation.setEndValue(1.0)
        self._hover_animation.valueChanged.connect(self._advance_hover)
        self._pressed_index = None
        self._buttons = []
        for index, title in enumerate(_CHART_NAMES):
            button = QPushButton(_CHART_SHORT_NAMES[index], self)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setMouseTracking(True)
            button.installEventFilter(self)
            button.clicked.connect(lambda checked=False, selected=index: self._choose(selected))
            self._buttons.append(button)
        self._center_button = QPushButton(self)
        self._center_button.setObjectName("ChartPieCenter")
        self._center_button.setCursor(Qt.PointingHandCursor)
        self._center_button.setMouseTracking(True)
        self._center_button.setToolTip("关闭菜单，保留当前图表")
        self._center_button.setAccessibleName("关闭图表选择")
        self._center_button.installEventFilter(self)
        self._center_button.clicked.connect(self.hide)
        self.resize(320, 320)
        self.update_style()

    def update_style(self):
        colors = self._selector.colors()
        self.setStyleSheet(
            "QWidget#ChartPiePopup { background: transparent; border: none; }"
            f"QPushButton {{ background: transparent; border: none; padding: 0;"
            f"color: {colors['text']}; font-size: 12px; font-weight: 500; }}"
            f"QPushButton:checked {{ color: {colors['accent']}; font-weight: 600; }}"
            f"QPushButton#ChartPieCenter {{ color: {colors['accent']}; font-size: 11px; }}"
        )
        self.update()

    def _advance_hover(self, progress):
        self._hover_levels = [
            start + (target - start) * progress
            for start, target in zip(self._hover_from, self._hover_to)
        ]
        self.update()

    def _set_hover(self, index):
        if not self.isVisible():
            return
        index = index if index is not None and index >= 0 else -1
        if index == self._hover_index:
            return
        self._hover_index = index
        if self._drag_selecting:
            self._selector._set_preview(index)
            title = _CHART_SHORT_NAMES[self._selector._display_index()]
            self._center_button.setText(("预览\n" if index >= 0 else "当前\n") + title)
        self._hover_animation.stop()
        self._hover_from = self._hover_levels.copy()
        self._hover_to = [1.0 if position == index else 0.0 for position in range(6)]
        self._hover_animation.start()

    def _reset_hover(self):
        self._hover_animation.stop()
        self._hover_index = -1
        self._hover_levels = [0.0] * 6
        self._hover_from = self._hover_levels.copy()
        self._hover_to = self._hover_levels.copy()

    def _center(self):
        return QPointF(self.width() / 2, self.height() / 2)

    def _sector_path(self, index):
        center = self._center()
        radius = self.width() / 2 - 6
        outer = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        inner = QRectF(center.x() - 40, center.y() - 40, 80, 80)
        angle = math.radians(-120 + index * 60)
        end_angle = angle + math.pi / 3
        path = QPainterPath()
        path.moveTo(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle))
        path.arcTo(outer, 120 - index * 60, -60)
        path.lineTo(center.x() + 40 * math.cos(end_angle), center.y() + 40 * math.sin(end_angle))
        path.arcTo(inner, 60 - index * 60, 60)
        path.closeSubpath()
        return path

    def _hit_index(self, point):
        center = self._center()
        offset_x, offset_y = point.x() - center.x(), point.y() - center.y()
        radius = math.hypot(offset_x, offset_y)
        if radius < 40:
            return -1
        if radius > self.width() / 2 - 6:
            return None
        angle = math.degrees(math.atan2(offset_y, offset_x))
        return int((round((angle + 120) % 360, 9) % 360) // 60)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMask(QRegion(self.rect(), QRegion.Ellipse))
        center = self._center()
        radius = self.width() * 0.33
        button_width = 84 if self.width() >= 320 else 76
        for index, button in enumerate(self._buttons):
            angle = math.radians(-90 + index * 60)
            button.setGeometry(
                round(center.x() + radius * math.cos(angle) - button_width / 2),
                round(center.y() + radius * math.sin(angle) - 16), button_width, 32,
            )
        self._center_button.setGeometry(round(center.x() - 40), round(center.y() - 40), 80, 80)
        self._center_button.setMask(QRegion(self._center_button.rect(), QRegion.Ellipse))

    def show_for(self, anchor, current_index, drag_select=False):
        anchor_center = anchor.mapToGlobal(anchor.rect().center())
        screen = QApplication.screenAt(anchor_center) or anchor.screen()
        available = screen.availableGeometry()
        diameter = 320 if min(available.width(), available.height()) >= 344 else 280
        self.resize(diameter, diameter)
        origin_x = anchor_center.x() - diameter // 2
        origin_y = (
            anchor_center.y() - diameter // 2 if drag_select
            else anchor.mapToGlobal(QPoint(0, anchor.height())).y() + 8
        )
        if not drag_select and origin_y + diameter > available.bottom() - 4:
            origin_y = anchor.mapToGlobal(QPoint(0, 0)).y() - diameter - 8
        origin_x = max(available.left() + 4, min(origin_x, available.right() - diameter - 3))
        origin_y = max(available.top() + 4, min(origin_y, available.bottom() - diameter - 3))
        self.move(origin_x, origin_y)
        self._current_index = current_index
        self._focus_index = current_index
        self._reset_hover()
        self._pressed_index = None
        self._drag_selecting = drag_select
        if drag_select:
            QApplication.instance().installEventFilter(self)
        for index, button in enumerate(self._buttons):
            button.setChecked(index == current_index)
            button.setAccessibleDescription("当前图表" if index == current_index else "切换图表")
        self._center_button.setText("当前\n" + _CHART_SHORT_NAMES[current_index])
        self._center_button.setToolTip(
            "松开取消预览，恢复原图表" if drag_select else "关闭菜单，保留当前图表"
        )
        self.show()
        self._buttons[current_index].setFocus(Qt.PopupFocusReason)
        if drag_select:
            self._set_hover(self._drag_index(QCursor.pos()))
        self.update()
        anchor.update()

    def _drag_index(self, global_point):
        anchor = self._selector._button
        if anchor.hitButton(anchor.mapFromGlobal(global_point)):
            return -1
        return self._hit_index(self.mapFromGlobal(global_point))

    def _finish_drag(self, global_point):
        index = self._drag_index(global_point)
        if index is not None and index >= 0:
            self._choose(index)
        else:
            self.hide()

    def _choose(self, index):
        self.chosen.emit(index)
        self.hide()

    def _handle_key(self, key, source=None):
        if key == Qt.Key_Escape:
            self.hide()
        elif key in (Qt.Key_Left, Qt.Key_Up, Qt.Key_Right, Qt.Key_Down):
            direction = -1 if key in (Qt.Key_Left, Qt.Key_Up) else 1
            self._focus_index = (self._focus_index + direction) % 6
            self._set_hover(-1)
            self._buttons[self._focus_index].setFocus(Qt.TabFocusReason)
            self.update()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            if source is self._center_button:
                self.hide()
            else:
                self._choose(self._focus_index)
        else:
            return False
        return True

    def eventFilter(self, watched, event):
        if self._drag_selecting:
            if event.type() == QEvent.MouseMove:
                self._set_hover(self._drag_index(event.globalPosition().toPoint()))
                return True
            if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._finish_drag(event.globalPosition().toPoint())
                return True
            if event.type() in (QEvent.Enter, QEvent.Leave):
                self._set_hover(self._drag_index(QCursor.pos()))
                return super().eventFilter(watched, event)
        if event.type() == QEvent.KeyPress and self._handle_key(event.key(), watched):
            return True
        if watched in self._buttons or watched is self._center_button:
            if event.type() in (QEvent.Enter, QEvent.MouseMove):
                point = watched.mapTo(self, event.position().toPoint())
                self._set_hover(self._hit_index(point))
            elif event.type() == QEvent.Leave:
                self._set_hover(self._hit_index(self.mapFromGlobal(QCursor.pos())))
        if watched in self._buttons:
            index = self._buttons.index(watched)
            if event.type() == QEvent.FocusIn:
                self._focus_index = index
                self.update()
            elif event.type() == QEvent.FocusOut:
                self.update()
        return super().eventFilter(watched, event)

    def focusNextPrevChild(self, forward):
        buttons = self._buttons + [self._center_button]
        focused = self.focusWidget()
        index = buttons.index(focused) if focused in buttons else self._current_index
        buttons[(index + (1 if forward else -1)) % len(buttons)].setFocus(Qt.TabFocusReason)
        return True

    def keyPressEvent(self, event):
        if self._handle_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        self._set_hover(self._hit_index(event.position()))

    def leaveEvent(self, event):
        self._set_hover(self._hit_index(self.mapFromGlobal(QCursor.pos())))
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed_index = self._hit_index(event.position())
            if self._pressed_index is None:
                self.hide()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self._hit_index(event.position())
            if index == self._pressed_index:
                if index == -1:
                    self.hide()
                elif index is not None:
                    self._choose(index)
            self._pressed_index = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        if self._drag_selecting:
            self._drag_selecting = False
            QApplication.instance().removeEventFilter(self)
            self._selector._button._hold_timer.stop()
            self._selector._button.setDown(False)
            self._selector._set_preview(-1)
        self._reset_hover()
        super().hideEvent(event)
        self._selector._button.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._selector.colors()
        surface = QColor(colors["sector"])
        surface.setAlphaF(_PIE_SURFACE_OPACITY)
        for index in range(6):
            path = self._sector_path(index)
            painter.fillPath(path, surface)
            painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            if self._hover_levels[index] > 0:
                hover = QColor(colors["hover"])
                hover.setAlphaF(self._hover_levels[index])
                painter.fillPath(path, hover)
            if index == self._current_index:
                selected = QColor(colors["accent"])
                selected.setAlpha(31)
                painter.fillPath(path, selected)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            border = QColor(colors["accent"] if index == self._current_index else colors["muted"])
            if index != self._current_index:
                border.setAlpha(65)
            painter.setPen(QPen(border, 1.3 if index == self._current_index else 0.8))
            painter.drawPath(path)
            if self._buttons[index].hasFocus() and index != self._current_index:
                painter.setPen(QPen(QColor(colors["text"]), 1.1, Qt.DashLine))
                painter.drawPath(path)
        center = self._center()
        center_surface = QColor(colors["base"])
        center_surface.setAlphaF(_PIE_SURFACE_OPACITY)
        painter.setBrush(center_surface)
        painter.setPen(QPen(QColor(colors["muted"]), 0.8))
        painter.drawEllipse(QRectF(center.x() - 40, center.y() - 40, 80, 80))
        if self._center_button.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(colors["text"]), 1.1, Qt.DashLine))
            painter.drawEllipse(QRectF(center.x() - 37, center.y() - 37, 74, 74))


class _ChartPieSelector(QWidget):
    """保持原图表索引和信号的圆盘选择器。"""
    currentIndexChanged = Signal(int)
    previewIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChartPieSelector")
        self._current_index = 0
        self._preview_index = None
        self._dark = True
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._button = _PieTrigger(self)
        self._popup = _ChartPiePopup(self)
        self._popup.chosen.connect(self.setCurrentIndex)
        self._button.clicked.connect(self._show_popup)
        layout.addWidget(self._button)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        self._caption = QLabel("图表视图", self)
        self._label = QLabel(_CHART_NAMES[0], self)
        self._label.setToolTip(_CHART_NAMES[0])
        self._button.setAccessibleDescription("当前图表：" + _CHART_NAMES[0])
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        labels.addWidget(self._caption)
        labels.addWidget(self._label)
        layout.addLayout(labels, stretch=1)
        self.setMinimumHeight(48)
        self.setDark(True)

    def colors(self):
        if self._dark:
            return _PIE_COLORS
        return {
            "base": "#FAF8F5", "sector": "#FFFFFF", "hover": "#F4ECE7",
            "text": "#50202D", "muted": "#8C7480", "accent": "#AD783A",
        }

    def currentIndex(self):
        return self._current_index

    def _display_index(self):
        return self._current_index if self._preview_index is None else self._preview_index

    def _update_display(self):
        index = self._display_index()
        previewing = self._preview_index is not None
        self._caption.setText("预览 · 松开确认" if previewing else "图表视图")
        self._label.setText(_CHART_NAMES[index])
        self._label.setToolTip(_CHART_NAMES[index])
        self._button.setAccessibleDescription(("正在预览：" if previewing else "当前图表：") + _CHART_NAMES[index])
        self._button.update()

    def _set_preview(self, index):
        index = index if 0 <= index < len(_CHART_NAMES) else None
        if index == self._preview_index:
            return
        previous = self._display_index()
        self._preview_index = index
        self._update_display()
        displayed = self._display_index()
        if displayed != previous:
            self.previewIndexChanged.emit(displayed)

    def setCurrentIndex(self, index):
        if not isinstance(index, int) or not 0 <= index < len(_CHART_NAMES):
            return
        if index == self._current_index and self._preview_index is None:
            return
        changed = index != self._current_index
        previous = self._display_index()
        self._current_index = index
        self._preview_index = None
        self._update_display()
        if changed:
            self.currentIndexChanged.emit(index)
        elif previous != index:
            self.previewIndexChanged.emit(index)

    def setDark(self, dark):
        self._dark = bool(dark)
        colors = self.colors()
        self.setStyleSheet("QWidget#ChartPieSelector { background: transparent; border: none; }")
        self._caption.setStyleSheet(
            f"QLabel {{ background: transparent; border: none; padding: 0; color: {colors['muted']}; font-size: 10px; }}"
        )
        self._label.setStyleSheet(
            f"QLabel {{ background: transparent; border: none; padding: 0; color: {colors['text']}; font-size: 13px; }}"
        )
        self._popup.update_style()
        self._button.update()

    def _show_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self._popup.show_for(self._button, self._current_index)

    def hideEvent(self, event):
        self._popup.hide()
        super().hideEvent(event)


def _ch_str(val: float, threshold: float, lower_is_better: bool = False) -> str:
    """根据值生成变化说明文字"""
    if val == 0:
        return "无数据"
    if lower_is_better:
        return "正常" if val < threshold else "偏高"
    return "正常" if val > threshold else "偏低"


def _ch_clr(val: float, threshold: float) -> str:
    """根据值生成变化颜色"""
    if val == 0:
        return "#888888"
    return "#a6e3a1" if val < threshold else "#fab387"


def _hex_rgba(h, a):
    h = h.lstrip("#")
    return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), a)


# ═══════════════════════════════════════════
#  顶部指标卡
# ═══════════════════════════════════════════

class _MetricCard(QFrame):
    def __init__(self, label, value, change, color, ch_color, parent=None, dark=True):
        super().__init__(parent)
        self.setObjectName("PerfMetricCard")
        background = "#252630" if dark else "#FFFFFF"
        border = "rgba(255,255,255,0.07)" if dark else "rgba(210,120,140,0.22)"
        label_color = "#9A98A1" if dark else "rgba(80,30,45,0.65)"
        self.setStyleSheet(
            f"QFrame#PerfMetricCard {{ background: {background}; border: 1px solid {border};"
            "border-radius: 12px; padding: 0; }"
            "QLabel { background: transparent; border: none; padding: 0; }"
        )
        self.setFixedHeight(96)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        ly = QVBoxLayout(self); ly.setContentsMargins(12, 10, 12, 10); ly.setSpacing(3)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{label_color};font-size:11px")
        ly.addWidget(lbl)
        val = QLabel(value); val.setStyleSheet(f"color:{color};font-size:24px;font-weight:600")
        val.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        val.setToolTip(value)
        ly.addWidget(val)
        ch = QLabel(change)
        ch.setStyleSheet(f"color:{ch_color};font-size:11px")
        ly.addWidget(ch)


class _MetricCardLight(_MetricCard):
    """浅色主题指标卡 — 粉色系边框+文字"""
    def __init__(self, label, value, change, color, ch_color, parent=None):
        super().__init__(label, value, change, color, ch_color, parent, dark=False)


# ═══════════════════════════════════════════
#  动画图表基类
# ═══════════════════════════════════════════

class _AnimatedChart(QWidget):
    """带动画属性的图表基类"""
    def __init__(self, chart, parent=None):
        super().__init__(parent)
        self._chart = chart
        self._anim_val = 0.0  # 0~1 动画进度
        self._anim = QPropertyAnimation(self, b"animProgress")
        self._anim.setDuration(800)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        QTimer.singleShot(100, self._anim.start)

    def getAnim(self): return self._anim_val
    def setAnim(self, v): self._anim_val = v; self.update()
    animProgress = Property(float, getAnim, setAnim)

    def textColor(self):
        return QColor(255,255,255,self._chart.sc()["t"]) if self._chart._d else QColor(80,30,45,200)

    def gridColor(self):
        return QColor(255,255,255,self._chart.sc()["g"]) if self._chart._d else QColor(200,140,155,45)

    def bgColor(self):
        return QColor("#111216") if self._chart._d else QColor("#faf8f5")


# ═══════════════════════════════════════════
#  甘特图
# ═══════════════════════════════════════════

class _GanttWidget(QWidget):
    def __init__(self, chart, p=None):
        super().__init__(p); self._chart = chart
        self.setMinimumHeight(165)

    def _build_rows(self):
        """从 PerfMonitor 构建真实甘特图行"""
        mon = get_monitor()
        m = mon.metrics
        rows = []
        # API 延迟 (阈值 500ms = 100%)
        api_val = m["api_ms"].latest
        api_pct = min(100, max(5, (api_val / 500) * 100)) if api_val else 0
        rows.append(("API 响应", api_pct, "#378add", f"{api_val:.0f}ms" if api_val else "-"))
        # 错误率 (阈值 5% = 100%)
        err_val = m["error_pct"].latest
        err_pct = min(100, max(5, (err_val / 5) * 100)) if err_val else 0
        rows.append(("错误率", err_pct, "#f38ba8", f"{err_val:.1f}%" if err_val else "0%"))
        # 内存 (阈值 1GB = 100%)
        mem_val = m["mem_mb"].latest
        mem_pct = min(100, max(5, (mem_val / 1024) * 100)) if mem_val else 0
        rows.append(("内存占用", mem_pct, "#a6e3a1", f"{mem_val:.0f}MB" if mem_val else "-"))
        # DB 延迟 (阈值 100ms = 100%)
        db_val = m["db_ms"].latest
        db_pct = min(100, max(5, (db_val / 100) * 100)) if db_val else 0
        rows.append(("DB 写入", db_pct, "#fab387", f"{db_val:.0f}ms" if db_val else "-"))
        # 线程池 (阈值 90% = 100%)
        w_val = m["workers_pct"].latest
        w_pct = min(100, max(5, (w_val / 90) * 100)) if w_val else 0
        rows.append(("线程池", w_pct, "#cba6f7", f"{w_val:.0f}%" if w_val else "-"))
        return rows

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        dark = self._chart._d
        w, h = self.width(), self.height()
        rows = self._build_rows()
        row_h = (h - 24) / len(rows)
        for i, (lb, pc, clr, ms) in enumerate(rows):
            y = 14 + i * row_h
            track_w = w - 260
            bx = 110
            tc = QColor(255,255,255,140) if dark else QColor(75,28,42,150)
            p.setPen(tc); p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(12, y, 88, 22), Qt.AlignVCenter | Qt.AlignLeft, lb)
            # 轨道
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255,255,255,12) if dark else QColor(0,0,0,8))
            p.drawRoundedRect(QRectF(bx, y + 1, track_w, 20), 4, 4)
            # 条
            bw = max(20, track_w * pc / 100)
            p.setBrush(QColor(clr))
            p.drawRoundedRect(QRectF(bx, y + 1, bw, 20), 4, 4)
            # 时间
            p.setPen(QColor(255,255,255,230) if dark else QColor(80,30,45,220))
            if bw > 68:
                p.drawText(QRectF(bx + bw - 64, y, 56, 22), Qt.AlignVCenter | Qt.AlignRight, ms)
            else:
                p.drawText(QRectF(bx + bw + 4, y, 56, 22), Qt.AlignVCenter | Qt.AlignLeft, ms)
            # 百分比
            p.setPen(QColor(255,255,255,70) if dark else QColor(180,120,135,150))
            p.drawText(QRectF(w - 56, y, 48, 22), Qt.AlignVCenter | Qt.AlignRight, f"{pc:.0f}%")


# ═══════════════════════════════════════════
#  折线/面积图（带动画）
# ═══════════════════════════════════════════

class _LineAreaWidget(_AnimatedChart):
    def __init__(self, chart, mode="line", parent=None):
        super().__init__(chart, parent)
        self._mode = mode
        self.setMinimumHeight(200)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        ch = self._chart
        prog = self._anim_val
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 48, 120, 12, 24
        px, py = float(pad_l), float(pad_t)
        pw = float(w - pad_l - pad_r)
        ph = float(h - pad_t - pad_b)

        p.fillRect(self.rect(), self.bgColor())

        # 数据
        s = ch.sc()
        if self._mode == "line":
            datasets = ch._ld
            colors = [s["p"], "#a6e3a1", "#f38ba8"]
            names = ["延迟", "队列深度", "错误率"]
            units = ["ms", "条", "%"]
            ymax = 500.0
            tgs = ch._line_c.togs() if ch._line_c and ch._line_c.tg.count() else []
        else:
            datasets = ch._ad
            colors = [s["p"], "#a6e3a1"]
            names = ["消息速率", "DB延迟"]
            units = ["msg/s", "ms"]
            ymax = 25.0
            tgs = ch._area_c.togs() if ch._area_c and ch._area_c.tg.count() else []

        n = len(datasets[0]) if datasets else 30
        max_idx = int((n - 1) * prog) + 1

        # 网格
        pen_g = QPen(self.gridColor(), 1, Qt.DotLine)
        for i in range(1, 5):
            p.setPen(pen_g)
            gy = py + ph * i / 4
            p.drawLine(QPointF(px, gy), QPointF(px + pw, gy))

        # 坐标轴标签
        tc = self.textColor()
        p.setPen(tc); p.setFont(QFont("Segoe UI", 9))
        for i in range(5):
            tv = ymax * (1 - i / 4)
            p.drawText(QRectF(2, int(py + ph * i / 4 - 8), pad_l - 6, 16),
                       Qt.AlignRight | Qt.AlignVCenter, f"{int(tv)}")
        for i in range(5):
            x = px + pw * i / 4
            p.drawText(QRectF(int(x - 16), int(py + ph + 2), 32, 16),
                       Qt.AlignCenter, f"{int(n * i / 4)}s")

        # 曲线
        for s_idx, (vals, clr, name) in enumerate(zip(datasets, colors, names)):
            if tgs and s_idx < len(tgs) and not tgs[s_idx].isChecked():
                continue
            pts = []
            for j in range(min(max_idx, len(vals))):
                x = px + pw * j / max(n - 1, 1)
                y = py + ph - (ph * min(vals[j], ymax) / ymax)
                pts.append(QPointF(x, y))

            if len(pts) < 2: continue

            path = QPainterPath()
            path.moveTo(pts[0])
            for j in range(1, len(pts)):
                x0, y0 = pts[j-1].x(), pts[j-1].y()
                x1, y1 = pts[j].x(), pts[j].y()
                dx = (x1 - x0) * 0.35
                path.cubicTo(x0 + dx, y0, x1 - dx, y1, x1, y1)

            if self._mode == "area":
                path.lineTo(pts[-1].x(), py + ph)
                path.lineTo(px, py + ph)
                path.closeSubpath()
                r, g, b, _ = _hex_rgba(clr, 20)
                p.setPen(Qt.NoPen); p.setBrush(QColor(r, g, b, 30))
                p.drawPath(path)
                # 重走折线
                path2 = QPainterPath(); path2.moveTo(pts[0])
                for j in range(1, len(pts)):
                    x0, y0 = pts[j-1].x(), pts[j-1].y()
                    x1, y1 = pts[j].x(), pts[j].y()
                    dx = (x1 - x0) * 0.35
                    path2.cubicTo(x0 + dx, y0, x1 - dx, y1, x1, y1)
                pen = QPen(QColor(clr), 2)
                p.setPen(pen); p.setBrush(Qt.NoBrush)
                p.drawPath(path2)
            else:
                pen = QPen(QColor(clr), 2)
                if s_idx == 2:  # Error rate 虚线
                    pen.setStyle(Qt.DashLine)
                    pen.setDashPattern([3, 3])
                p.setPen(pen); p.setBrush(Qt.NoBrush)
                p.drawPath(path)

        # 右侧图例
        if prog > 0.9:
            legend_x = px + pw + 8
            p.setFont(QFont("Segoe UI", 10))
            for s_idx, (clr, name) in enumerate(zip(colors, names)):
                if tgs and s_idx < len(tgs) and not tgs[s_idx].isChecked():
                    continue
                vals = datasets[s_idx]
                v = vals[-1] if vals else 0
                ly = int(py + s_idx * 24)
                p.setPen(Qt.NoPen); p.setBrush(QColor(clr))
                p.drawRect(QRectF(legend_x, ly + 2, 8, 8))
                p.setPen(QColor(255,255,255,180) if self._chart._d else QColor(75,28,42,180))
                p.drawText(QRectF(legend_x + 12, ly - 2, 96, 16),
                           Qt.AlignLeft | Qt.AlignVCenter, name)
                p.setPen(QColor(255,255,255,255) if self._chart._d else QColor(80,30,45,245))
                p.setFont(QFont("Segoe UI", 10))
                u = units[s_idx] if s_idx < len(units) else ""
                p.drawText(QRectF(legend_x + 12, ly + 12, 96, 14),
                           Qt.AlignLeft | Qt.AlignVCenter, f"{int(v)}{u}")


# ═══════════════════════════════════════════
#  饼图（带动画）
# ═══════════════════════════════════════════

class _DoughWidget(_AnimatedChart):
    def __init__(self, chart, parent=None):
        super().__init__(chart, parent)
        self.setMinimumHeight(200)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        ch = self._chart
        prog = self._anim_val
        w, h = self.width(), self.height()
        dark = ch._d
        p.fillRect(self.rect(), self.bgColor())

        s = ch.sc()
        mon = get_monitor()
        # ── 真实数据：PerfMonitor 指标 ──
        api_total = mon._api_total
        api_errors = mon._api_errors
        mem_mb = mon.metrics["mem_mb"].latest
        msg_rate = mon.metrics["msg_rate"].latest
        workers_pct = mon.metrics["workers_pct"].latest

        total = max(1, api_total + max(0, mem_mb) + max(0, msg_rate) + max(0, workers_pct))
        if api_total > 0:
            slices = [
                ("API 成功", max(1, api_total - api_errors), _hex_rgba("#a6e3a1", 60)),
                ("API 错误", max(1, api_errors),           _hex_rgba("#f38ba8", 60)),
                ("内存占用", max(1, int(mem_mb)),           _hex_rgba(s["p"], 60)),
                ("线程活跃", max(1, int(workers_pct)),      _hex_rgba("#fab387", 60)),
                ("消息吞吐", max(1, int(msg_rate)),         _hex_rgba("#74c7ec", 60)),
            ]
            center_val = str(api_total)
            center_label = "API 调用"
        else:
            slices = [
                ("等待连接", 100, _hex_rgba("#888888", 60)),
            ]
            center_val = "—"
            center_label = "无数据"

        cx, cy = w / 2 - 50, h / 2
        outer = min(w, h) / 2 - 20
        inner = outer * 0.65
        total_s = sum(v for _, v, _ in slices)
        full_angle = 360.0 * prog
        current = 0.0

        for name, val, (r, g, b, a) in slices:
            span = 360.0 * val / total_s
            if current + span > full_angle:
                span = max(0, full_angle - current)
            if span <= 0: break
            p.setPen(QPen(QColor(r, g, b, 180), 1))
            p.setBrush(QColor(r, g, b, min(a + 60, 255)))
            p.drawPie(QRectF(cx - outer, cy - outer, outer * 2, outer * 2),
                      int((-90 + current) * 16), int(span * 16))
            current += span

        # 右侧图例
        if prog > 0.9:
            lx = cx + outer + 12
            ly_base = cy - 40
            p.setFont(QFont("Segoe UI", 10))
            for i, (name, val, (r, g, b, a)) in enumerate(slices):
                ly = ly_base + i * 22
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(r, g, b, min(a + 60, 255)))
                p.drawRoundedRect(QRectF(lx, ly, 12, 12), 2, 2)
                pct = int(val / total_s * 100)
                txt = f"{name}  {pct}%" if w > 350 else f"{name}"
                p.setPen(QColor(255,255,255,180) if dark else QColor(75,28,42,180))
                p.drawText(QRectF(lx + 16, ly, 120, 14), Qt.AlignVCenter | Qt.AlignLeft, txt)

        # 中心孔
        p.setBrush(self.bgColor())
        p.setPen(QPen(QColor(255,255,255,40) if dark else QColor(200,140,155,50), 1))
        p.drawEllipse(QRectF(cx - inner, cy - inner, inner * 2, inner * 2))

        # 中心文字
        if prog > 0.8:
            p.setPen(QColor(255,255,255,200) if dark else QColor(75,28,42,200))
            p.setFont(QFont("Segoe UI", 18, QFont.DemiBold))
            p.drawText(QRectF(cx - 40, cy - 12, 80, 24), Qt.AlignCenter, center_val)
            p.setPen(QColor(255,255,255,100) if dark else QColor(180,120,135,150))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(cx - 50, cy + 12, 100, 16), Qt.AlignCenter, center_label)


# ═══════════════════════════════════════════
#  柱状图（带动画）
# ═══════════════════════════════════════════

class _BarWidget(_AnimatedChart):
    def __init__(self, chart, parent=None):
        super().__init__(chart, parent)
        self.setMinimumHeight(200)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        ch = self._chart
        prog = self._anim_val
        w, h = self.width(), self.height()
        dark = ch._d
        pad_l, pad_r, pad_t, pad_b = 36, 36, 12, 30
        px, py = float(pad_l), float(pad_t)
        pw = float(w - pad_l - pad_r)
        ph = float(h - pad_t - pad_b)

        p.fillRect(self.rect(), self.bgColor())

        # ── 真实数据：PerfMonitor 指标 ──
        mon = get_monitor()
        m = mon.metrics
        labels = ["内存", "CPU", "线程", "API延迟", "DB延迟", "消息速率"]
        raw_vals = [
            m["mem_mb"].latest,
            mon._process.cpu_percent() if hasattr(mon, '_process') else 0,
            mon._process.num_threads() if hasattr(mon, '_process') else 0,
            m["api_ms"].latest,
            m["db_ms"].latest,
            m["msg_rate"].latest,
        ]
        # 归一化到 0~ymax 范围
        maxes = [1024, 100, 32, 500, 100, 25]
        ymax = 10.0
        values = []
        for v, mx in zip(raw_vals, maxes):
            if v > 0 and mx > 0:
                values.append(min(ymax, v / mx * ymax))
            else:
                values.append(0.0)
        n = len(labels)
        bar_w = pw / n * 0.55
        gap = pw / n * 0.45

        # 网格
        pen_g = QPen(self.gridColor(), 1, Qt.DotLine)
        for i in range(1, 5):
            p.setPen(pen_g)
            gy = py + ph * i / 4
            p.drawLine(QPointF(px, gy), QPointF(px + pw, gy))

        # Y轴
        tc = self.textColor()
        p.setPen(tc); p.setFont(QFont("Segoe UI", 9))
        for i in range(5):
            p.drawText(QRectF(2, int(py + ph * i / 4 - 8), pad_l - 4, 16),
                       Qt.AlignRight | Qt.AlignVCenter, str(int(ymax * (4 - i) / 4)))

        # 柱子
        for i, (lbl, val, hexc, raw_v) in enumerate(zip(labels, values, _BARC, raw_vals)):
            bx = px + gap / 2 + i * (bar_w + gap)
            target_h = ph * val / ymax
            bh = target_h * prog  # 从下往上动画
            by = py + ph - bh
            r, g, b, _ = _hex_rgba(hexc, 0)
            # 填充
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(r, g, b, 60))
            p.drawRoundedRect(QRectF(bx - 1, by + 1, bar_w + 2, bh - 1), 3, 3)
            # 边框
            p.setPen(QPen(QColor(hexc), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 3, 3)
            # 标签
            p.setPen(tc); p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(int(bx - 4), int(py + ph + 2), int(bar_w + 8), 16),
                       Qt.AlignCenter, lbl)
            # 数值 — 显示原始单位
            if prog > 0.5:
                p.setPen(QColor(255,255,255,250) if dark else QColor(80,30,45,240))
                units = ["MB", "%", "个", "ms", "ms", "/s"]
                txt = f"{raw_v:.0f}{units[i]}" if raw_v > 0 else "-"
                p.drawText(QRectF(int(bx - 4), int(by - 16), int(bar_w + 8), 14),
                           Qt.AlignCenter, txt)


# ═══════════════════════════════════════════
#  消息分析面板
# ═══════════════════════════════════════════

class _AnalyticsWidget(QWidget):
    """消息分析 — 每日统计 + 平台分布 + 时段热力图"""
    def __init__(self, chart, parent=None):
        super().__init__(parent)
        self._chart = chart
        self.setMinimumHeight(320)

    def minimumSizeHint(self):
        return self.minimumSize()

    def sizeHint(self):
        return self.minimumSize()

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        ch = self._chart; w, h = self.width(), self.height()
        dark = ch._d
        p.fillRect(self.rect(), QColor("#1a1b25") if dark else QColor("#faf8f5"))

        try:
            from dmshoot.core.message_analytics import daily_summary, platform_distribution, hourly_distribution
            daily = daily_summary(7)
            platforms = platform_distribution(7)
            hourly = hourly_distribution(7)
        except Exception:
            p.setPen(QColor("#f38ba8")); p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "数据加载失败")
            p.end()
            return

        tc = QColor(255,255,255,220) if dark else QColor(80,30,45,200)
        sub = QColor(255,255,255,100) if dark else QColor(180,140,150,180)
        accent = QColor("#a6e3a1")
        warn = QColor("#fab387")

        pad = 14; y = 8
        # ── 标题 ──
        if not ch._compact:
            p.setPen(tc); p.setFont(QFont("Segoe UI", 13, QFont.Bold))
            p.drawText(pad, y, w - pad * 2, 20, Qt.AlignLeft, "消息分析 · 近7天")
            y += 24

        # ── 每日摘要行 ──
        p.setFont(QFont("Segoe UI", 10))
        for d in daily[:4]:
            line = f"{d['date'][-5:]}  收到{d['incoming']}  回复{d['outgoing']}  回复率{d['reply_rate']}%  均{d['avg_response_ms']}ms"
            color = tc if d["incoming"] > 0 else sub
            p.setPen(color)
            p.drawText(pad, y, w - pad * 2, 16, Qt.AlignLeft, line)
            y += 16

        y += 8
        p.setPen(QPen(QColor(255,255,255,20) if dark else QColor(200,120,140,30), 1))
        p.drawLine(pad, y, w - pad, y); y += 10

        # ── 平台分布 ──
        p.setPen(tc); p.setFont(QFont("Segoe UI", 12, QFont.Bold))
        p.drawText(pad, y, w - pad * 2, 18, Qt.AlignLeft, "平台分布")
        y += 20

        total = sum(platforms.values()) or 1
        bar_h = 16; bar_w = w - pad * 2 - 100
        colors_p = {"bilibili": "#a6e3a1", "douyin": "#fab387", "kuaishou": "#f38ba8", "xiaohongshu": "#cba6f7"}
        for pl, cnt in sorted(platforms.items(), key=lambda x: -x[1]):
            ratio = cnt / total
            bw = int(bar_w * ratio)
            clr = colors_p.get(pl, "#74c7ec")
            name = {"bilibili":"B站","douyin":"抖音","kuaishou":"快手","xiaohongshu":"小红书"}.get(pl, pl)
            p.setPen(Qt.NoPen); p.setBrush(QColor(clr))
            p.drawRoundedRect(QRectF(pad + 70, y, bw, bar_h), 3, 3)
            p.setPen(tc); p.setFont(QFont("Segoe UI", 9))
            p.drawText(pad, y - 1, 66, bar_h + 2, Qt.AlignRight | Qt.AlignVCenter, name)
            p.drawText(pad + 73 + bw + 4, y - 1, 40, bar_h + 2, Qt.AlignLeft, str(cnt))
            y += bar_h + 4

        y += 8
        p.setPen(QPen(QColor(255,255,255,20) if dark else QColor(200,120,140,30), 1))
        p.drawLine(pad, y, w - pad, y); y += 10

        # ── 时段热力 ──
        p.setPen(tc); p.setFont(QFont("Segoe UI", 12, QFont.Bold))
        p.drawText(pad, y, w - pad * 2, 18, Qt.AlignLeft, "时段分布")
        y += 22

        hour_counts = {h: 0 for h in range(24)}
        for hd in hourly:
            hour_counts[hd["h"]] += hd["cnt"]
        max_cnt = max(hour_counts.values()) or 1

        cell_w = (w - pad * 2) / 24
        for h_i in range(24):
            cnt = hour_counts[h_i]
            intensity = cnt / max_cnt
            r = int(166 * (1 - intensity) + 14 * intensity)
            g = int(227 * (1 - intensity) + 200 * intensity)
            b = int(225 * (1 - intensity) + 50 * intensity)
            p.setPen(Qt.NoPen); p.setBrush(QColor(r, g, b))
            rx = pad + h_i * cell_w
            p.drawRoundedRect(QRectF(rx + 1, y, cell_w - 2, 28), 2, 2)
            if cnt > 0:
                p.setPen(QColor(255,255,255,200) if dark else QColor(80,30,45,200))
                p.setFont(QFont("Segoe UI", 8))
                p.drawText(QRectF(rx + 1, y + 4, cell_w - 2, 20), Qt.AlignCenter, str(cnt))

        # ── 底部结论 ──
        y += 36
        p.setPen(sub); p.setFont(QFont("Segoe UI", 9))
        peak_hour = max(hour_counts, key=hour_counts.get) if max_cnt > 0 else None
        if peak_hour is not None:
            status_line = f"高峰时段: {peak_hour}:00   |   总消息: {total}"
        else:
            status_line = "暂无数据"
        p.drawText(pad, y, w - pad * 2, 16, Qt.AlignLeft, status_line)
        p.end()
        if ch._compact and self.minimumHeight() != y + 28:
            self.setMinimumHeight(y + 28)


# ═══════════════════════════════════════════
#  Card 容器
# ═══════════════════════════════════════════

class _Card(QFrame):
    clicked = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("c")
        self._inner = None
        self.setCursor(Qt.PointingHandCursor)
        self.l = QVBoxLayout(self)
        self.l.setContentsMargins(14, 12, 14, 12); self.l.setSpacing(6)
        self.h = QLabel(title.upper())
        self.l.addWidget(self.h)
        self.tg = QHBoxLayout(); self.tg.setSpacing(14)
        self.l.addLayout(self.tg)

    def setStyle(self, dark):
        if dark:
            self.setStyleSheet(
                "#c{background:#1a1b25;border:1px solid rgba(255,255,255,0.06);"
                "border-radius:12px;padding:0}")
            self.h.setStyleSheet(
                "background:transparent;border:none;padding:0;"
                "color:#E6E3DD;font-size:12px;font-weight:600")
        else:
            self.setStyleSheet(
                "#c{background:#fff;border:1px solid rgba(210,120,140,0.22);"
                "border-radius:12px;padding:0}")
            self.h.setStyleSheet(
                "background:transparent;border:none;padding:0;"
                "color:rgba(80,30,45,0.75);font-size:12px;font-weight:600")

    def setw(self, w):
        if self._inner:
            self.l.replaceWidget(self._inner, w); self._inner.deleteLater()
        else:
            self.l.addWidget(w, stretch=1)
        self._inner = w

    def togs(self):
        return [self.tg.itemAt(i).widget() for i in range(self.tg.count())]

    def addt(self, lbl, clr="#378add", chk=True, dark=True):
        cb = QCheckBox(lbl); cb.setChecked(chk)
        if dark:
            cb.setStyleSheet(
                f"QCheckBox{{color:{clr};font-size:11px;spacing:6px}}"
                f"QCheckBox::indicator{{width:11px;height:11px;border-radius:2px;"
                f"border:1px solid rgba(255,255,255,0.12);background:transparent}}"
                f"QCheckBox::indicator:checked{{background:{clr}30;border-color:{clr}}}")
        else:
            cb.setStyleSheet(
                f"QCheckBox{{color:{clr};font-size:11px;spacing:6px}}"
                f"QCheckBox::indicator{{width:11px;height:11px;border-radius:2px;"
                f"border:1px solid rgba(200,120,140,0.35);background:transparent}}"
                f"QCheckBox::indicator:checked{{background:{clr}30;border-color:{clr}}}")
        self.tg.addWidget(cb)
        return cb

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._click_pos = e.pos()

    def mouseReleaseEvent(self, e):
        if hasattr(self, '_click_pos') and (e.pos() - self._click_pos).manhattanLength() < 5:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# ═══════════════════════════════════════════
#  PerfChart — 主面板（双列网格）
# ═══════════════════════════════════════════

class PerfChart(QWidget):
    def __init__(self, m=None, parent=None, compact: bool = False):
        super().__init__(parent)
        self.setObjectName("PerfChart")
        self._s = "blue"; self._d = True
        self._m = m or get_monitor()
        self._compact = compact

        ly = QVBoxLayout(self); ly.setContentsMargins(0, 0, 0, 0); ly.setSpacing(12)

        # ── 工具栏（仅非 compact 模式，即 PerfWindow 中显示）──
        if not compact:
            tb = QHBoxLayout(); tb.setSpacing(6); self._sb = {}
            for n in _SCHEMES:
                b = QPushButton(n.capitalize()); b.setCheckable(True)
                b.setChecked(n == "blue")
                b.setProperty("class", "sb")
                b.clicked.connect(lambda _, x=n: self._ss(x))
                self._sb[n] = b; tb.addWidget(b)
            tb.addStretch()
            self._tl = QPushButton("浅色图表"); self._tl.setCheckable(True)
            self._tl.setProperty("class", "tb")
            self._tl.clicked.connect(lambda: self._st(False))
            self._td = QPushButton("深色图表"); self._td.setCheckable(True)
            self._td.setChecked(True)
            self._td.setProperty("class", "tb")
            self._td.clicked.connect(lambda: self._st(True))
            tb.addWidget(self._tl); tb.addWidget(self._td); ly.addLayout(tb)

        # ── 指标卡 ──
        self._metrics_row = QGridLayout(); self._metrics_row.setSpacing(12)
        self._metric_columns = 4
        ly.addLayout(self._metrics_row)

        # 紧凑模式：下拉选择器（在图表区上方）
        if compact:
            self._chart_combo = _ChartPieSelector(self)
            self._chart_combo.currentIndexChanged.connect(self._on_chart_select)
            self._chart_combo.previewIndexChanged.connect(self._on_chart_select)
            ly.addWidget(self._chart_combo)
            self._update_combo_style()

        # ── 图表区 ──
        if compact:
            ct = QWidget(); ct.setStyleSheet("background:transparent")
            self._grid = QVBoxLayout(ct)
            self._grid.setContentsMargins(0, 4, 0, 8)
            self._grid.setSpacing(12)
            ly.addWidget(ct, stretch=1)
        else:
            sc = QScrollArea(); sc.setWidgetResizable(True)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setStyleSheet("QScrollArea{background:transparent;border:none}")
            sc.setFrameShape(QFrame.NoFrame)
            ct = QWidget(); ct.setStyleSheet("background:transparent")
            self._grid = QGridLayout(ct)
            self._grid.setContentsMargins(0, 4, 0, 8)
            self._grid.setSpacing(12)
            self._grid.setColumnStretch(0, 1); self._grid.setColumnStretch(1, 1)
            # 底部大量空白：程序回退只在空白区内移动，不影响图表可见性
            _pad = QWidget(); _pad.setFixedHeight(300); _pad.setStyleSheet("background:transparent")
            self._grid.addWidget(_pad, 4, 0, 1, 2)
            sc.setWidget(ct); ly.addWidget(sc, stretch=1)

        # 甘特（全宽或首项）
        self._gantt_c = _Card("请求管道甘特图 (近 60s)")
        # 折线 + 面积
        self._line_c = _Card("API 指标")
        self._area_c = _Card("各平台消息速率")
        # 饼图 + 柱状
        self._dough_c = _Card("时间分布")
        self._bar_c = _Card("线程 & 工作线程")
        # 消息分析
        self._analytics_c = _Card("消息分析 (近7天)")

        if compact:
            self._grid.addWidget(self._gantt_c, 0, Qt.AlignTop)
            self._grid.addWidget(self._line_c, 0, Qt.AlignTop)
            self._grid.addWidget(self._area_c, 0, Qt.AlignTop)
            self._grid.addWidget(self._dough_c, 0, Qt.AlignTop)
            self._grid.addWidget(self._bar_c, 0, Qt.AlignTop)
            self._grid.addWidget(self._analytics_c, 0, Qt.AlignTop)
            self._chart_cards = [self._gantt_c, self._line_c, self._area_c, self._dough_c, self._bar_c, self._analytics_c]
            for i, card in enumerate(self._chart_cards):
                card.setVisible(i == 0)
        else:
            self._grid.addWidget(self._gantt_c, 0, 0, 1, 2)
            self._grid.addWidget(self._line_c, 1, 0)
            self._grid.addWidget(self._area_c, 1, 1)
            self._grid.addWidget(self._dough_c, 2, 0)
            self._grid.addWidget(self._bar_c, 2, 1)
            self._grid.addWidget(self._analytics_c, 3, 0, 1, 2)  # 全宽

        # 使用 PerfMonitor 真实数据初始化环形缓冲
        self._ld = [[0.0] * 60 for _ in range(3)]  # 延迟/队列深度/错误率
        self._ad = [[0.0] * 60 for _ in range(2)]  # 平台消息速率

        # 点击事件
        self._gantt_c.clicked.connect(lambda: self._show_modal("gantt"))
        self._line_c.clicked.connect(lambda: self._show_modal("line"))
        self._area_c.clicked.connect(lambda: self._show_modal("area"))
        self._dough_c.clicked.connect(lambda: self._show_modal("dough"))
        self._bar_c.clicked.connect(lambda: self._show_modal("bar"))
        self._analytics_c.clicked.connect(lambda: self._show_modal("analytics"))

        QTimer.singleShot(0, self._rb)
        self.setStyleSheet("QWidget#PerfChart { background: transparent; }" if compact else "QWidget#PerfChart { background: #111216; }")
        self._tm = QTimer(self); self._tm.timeout.connect(self._tk)
        self._tm.start(3000)

    def sc(self): return _SCHEMES[self._s]

    def _on_chart_select(self, idx: int):
        """紧凑模式：只显示选中的图表"""
        if not self._compact:
            return
        for i, card in enumerate(self._chart_cards):
            card.setVisible(i == idx)

    def _ss(self, n):
        self._s = n
        for x, b in self._sb.items(): b.setChecked(x == n)
        self._rb()

    def _st(self, d):
        self._d = d
        self._td.setChecked(d); self._tl.setChecked(not d)
        self._update_styles()
        self._rb()
        # 更新自身背景
        background = "transparent" if self._compact else ("#111216" if d else "#faf8f5")
        self.setStyleSheet(f"QWidget#PerfChart {{ background: {background}; }}")
        if hasattr(self, '_theme_cb') and self._theme_cb:
            self._theme_cb()

    def _update_styles(self):
        dark = self._d
        for card in [self._gantt_c, self._line_c, self._area_c, self._dough_c, self._bar_c, self._analytics_c]:
            card.setStyle(dark)
        self._rebuild_metrics()
        if self._compact:
            self._update_combo_style()
        # 工具栏按钮样式
        self._update_toolbar_styles()

    def _update_combo_style(self):
        self._chart_combo.setDark(self._d)

    def _update_toolbar_styles(self):
        """工具栏按钮（sb/tb）适配浅色/深色"""
        dark = self._d
        if dark:
            for b in self._sb.values():
                b.setStyleSheet("")
            self._tl.setStyleSheet(""); self._td.setStyleSheet("")
        else:
            sb_style = (
                "QPushButton{background:rgba(210,120,140,0.10);border:1px solid rgba(200,120,140,0.3);"
                "border-radius:8px;color:rgba(80,30,45,0.75);font-size:12px;font-weight:500;padding:5px 10px;}"
                "QPushButton:hover{background:rgba(210,120,140,0.2);color:rgba(80,30,45,0.9);}"
                "QPushButton:checked{background:rgba(210,120,140,0.25);border:1px solid rgba(200,120,140,0.55);"
                "color:rgba(200,100,120,0.95);font-weight:600;}"
            )
            tb_style = (
                "QPushButton{background:rgba(210,120,140,0.08);border:1px solid rgba(200,120,140,0.25);"
                "border-radius:8px;color:rgba(80,30,45,0.7);font-size:12px;font-weight:500;padding:5px 10px;}"
                "QPushButton:hover{background:rgba(210,120,140,0.18);color:rgba(80,30,45,0.85);}"
                "QPushButton:checked{background:rgba(210,120,140,0.22);border:1px solid rgba(200,120,140,0.5);"
                "color:rgba(200,100,120,0.9);font-weight:600;}"
            )
            for b in self._sb.values():
                b.setStyleSheet(sb_style)
            self._tl.setStyleSheet(tb_style); self._td.setStyleSheet(tb_style)

    def _rebuild_metrics(self):
        """首次调用创建指标卡，后续仅更新数值（不触发 layout 重建导致滚动重置）"""
        mon = get_monitor()
        api_latest = mon.metrics["api_ms"].latest
        pending_latest = mon.metrics["pending"].latest
        msg_rate = mon.metrics["msg_rate"].latest
        error_pct = mon.metrics["error_pct"].latest

        s = _SCHEMES[self._s]
        sc = s["p"]

        vals = [
            f"{api_latest:.0f}ms" if api_latest else "-",
            f"{pending_latest:.0f}" if pending_latest else "-",
            f"{msg_rate:.0f}/s" if msg_rate else "-",
            f"{error_pct:.1f}%" if error_pct else "0%",
        ]
        changes = [
            _ch_str(api_latest, 200),
            _ch_str(pending_latest, 10),
            _ch_str(msg_rate, 5),
            _ch_str(error_pct, 1, True),
        ]
        ch_colors = [
            _ch_clr(api_latest, 200),
            _ch_clr(pending_latest, 10),
            _ch_clr(msg_rate, 5),
            _ch_clr(error_pct, 1),
        ]

        if not hasattr(self, '_metric_refs') or len(self._metric_refs) != 4:
            # 首次创建
            self._metric_refs = ([], [])
            while self._metrics_row.count():
                w = self._metrics_row.takeAt(0).widget()
                if w: w.deleteLater()
            data = [
                ("API 延迟",  vals[0], changes[0], sc, ch_colors[0]),
                ("队列深度", vals[1], changes[1], "#a6e3a1", ch_colors[1]),
                ("消息速率", vals[2], changes[2], sc, ch_colors[2]),
                ("错误率",   vals[3], changes[3], "#f38ba8", ch_colors[3]),
            ]
            for label, val, ch, col, chc in data:
                if self._d:
                    card = _MetricCard(label, val, ch, col, chc)
                else:
                    card = _MetricCardLight(label, val, ch, col, chc)
                # 找到 card 内的 value label 和 change label
                inner = card.layout()
                val_lbl = inner.itemAt(1).widget()  # 第二个是数值
                ch_lbl = inner.itemAt(2).widget()   # 第三个是变化
                val_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                ch_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._metric_refs[0].append(card)
                self._metric_refs[1].append((val_lbl, ch_lbl))
            self._layout_metrics(force=True)
        else:
            # 仅更新数值文本
            for i, (val_lbl, ch_lbl) in enumerate(self._metric_refs[1]):
                val_lbl.setText(vals[i])
                ch_lbl.setText(changes[i])

    def _layout_metrics(self, force=False):
        if not hasattr(self, '_metric_refs'):
            return
        columns = 2 if self._compact and self.width() < 480 else 4
        if not force and columns == self._metric_columns:
            return
        self._metric_columns = columns
        while self._metrics_row.count():
            self._metrics_row.takeAt(0)
        for column in range(4):
            self._metrics_row.setColumnStretch(column, 1 if column < columns else 0)
        for index, card in enumerate(self._metric_refs[0]):
            self._metrics_row.addWidget(card, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_metrics()

    def _rb(self):
        self._rebuild_metrics()
        dark = self._d
        for card in [self._gantt_c, self._line_c, self._area_c, self._dough_c, self._bar_c, self._analytics_c]:
            card.setStyle(dark)

        self._gw = _GanttWidget(self); self._gantt_c.setw(self._gw)
        self._build_line(); self._build_area()
        self._build_dough(); self._build_bar()
        self._build_analytics()

    def _build_line(self):
        s = _SCHEMES[self._s]; dark = self._d
        if self._line_c.tg.count() == 0:
            for l, c in [("延迟", s["p"]), ("队列深度", "#a6e3a1"),
                         ("错误率", "#f38ba8")]:
                self._line_c.addt(l, c, True, dark)
        else:
            # 更新已有 checkbox 颜色样式
            for cb, (l, c) in zip(self._line_c.togs(),
                                   [("延迟", s["p"]), ("队列深度", "#a6e3a1"),
                                    ("错误率", "#f38ba8")]):
                cb.setStyleSheet(
                    f"QCheckBox{{color:{c};font-size:11px;spacing:6px}}"
                    f"QCheckBox::indicator{{width:11px;height:11px;border-radius:2px;"
                    f"border:1px solid rgba({'255' if dark else '200'},{'255' if dark else '120'},{'255' if dark else '140'},{'0.12' if dark else '0.35'});background:transparent}}"
                    f"QCheckBox::indicator:checked{{background:{c}30;border-color:{c}}}")
        w = _LineAreaWidget(self, "line")
        for cb in self._line_c.togs():
            try:
                if cb.receivers(cb.toggled) > 0:
                    cb.toggled.disconnect()
            except (RuntimeError, TypeError, AttributeError): pass
            cb.toggled.connect(lambda _checked, w=w: w.update() if isValid(w) else None)
        self._line_c.setw(w)

    def _build_area(self):
        s = _SCHEMES[self._s]; dark = self._d
        if self._area_c.tg.count() == 0:
            for l, c in [("消息速率", s["p"]), ("DB延迟", "#a6e3a1")]:
                self._area_c.addt(l, c, True, dark)
        else:
            for cb, (l, c) in zip(self._area_c.togs(),
                                   [("消息速率", s["p"]), ("DB延迟", "#a6e3a1")]):
                cb.setStyleSheet(
                    f"QCheckBox{{color:{c};font-size:11px;spacing:6px}}"
                    f"QCheckBox::indicator{{width:11px;height:11px;border-radius:2px;"
                    f"border:1px solid rgba({'255' if dark else '200'},{'255' if dark else '120'},{'255' if dark else '140'},{'0.12' if dark else '0.35'});background:transparent}}"
                    f"QCheckBox::indicator:checked{{background:{c}30;border-color:{c}}}")
        w = _LineAreaWidget(self, "area")
        for cb in self._area_c.togs():
            try:
                if cb.receivers(cb.toggled) > 0:
                    cb.toggled.disconnect()
            except (RuntimeError, TypeError, AttributeError): pass
            cb.toggled.connect(lambda _checked, w=w: w.update() if isValid(w) else None)
        self._area_c.setw(w)

    def _build_dough(self):
        w = _DoughWidget(self)
        self._dough_c.setw(w)

    def _build_bar(self):
        w = _BarWidget(self)
        self._bar_c.setw(w)

    def _build_analytics(self):
        w = _AnalyticsWidget(self)
        self._analytics_c.setw(w)

    def _tk(self):
        if getattr(self, '_modal_open', False):
            return  # 弹窗打开时跳过刷新，避免滚动跳动
        mon = get_monitor()
        with mon._lock:
            # 折线数据：API延迟、队列深度、错误率
            if mon.metrics["api_ms"]._buf:
                self._ld[0].pop(0); self._ld[0].append(mon.metrics["api_ms"].latest)
            if mon.metrics["pending"]._buf:
                self._ld[1].pop(0); self._ld[1].append(mon.metrics["pending"].latest)
            if mon.metrics["error_pct"]._buf:
                self._ld[2].pop(0); self._ld[2].append(mon.metrics["error_pct"].latest)
            # 面积图数据：消息速率 + DB延迟
            if mon.metrics["msg_rate"]._buf:
                self._ad[0].pop(0); self._ad[0].append(mon.metrics["msg_rate"].latest)
            if mon.metrics["db_ms"]._buf:
                self._ad[1].pop(0); self._ad[1].append(mon.metrics["db_ms"].latest)
        self._rebuild_metrics()
        for card in [self._line_c, self._area_c, self._gantt_c, self._analytics_c]:
            if card._inner: card._inner.update()

    def _show_modal(self, chart_type):
        """点击图表弹出放大窗口"""
        from PySide6.QtCore import Qt
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        dlg.setFixedSize(820, 640)

        layout = QVBoxLayout(dlg); layout.setContentsMargins(0, 0, 0, 0)
        wrapper = QFrame()
        if self._d:
            wrapper.setStyleSheet("background:#1a1b25;border-radius:14px;border:1px solid rgba(255,255,255,0.08)")
        else:
            wrapper.setStyleSheet("background:#fff;border-radius:14px;border:1px solid rgba(210,120,140,0.25)")
        wl = QVBoxLayout(wrapper); wl.setContentsMargins(14, 10, 14, 10)

        title_map = {
            "gantt":"请求管道甘特图","line":"API 指标","area":"各平台消息速率",
            "dough":"时间分布","bar":"线程 & 工作线程","analytics":"消息分析"}
        header = QHBoxLayout()
        tl = QLabel(title_map.get(chart_type, "Chart"))
        if self._d:
            tl.setStyleSheet("color:rgba(255,255,255,0.6);font-size:16px;font-weight:500")
        else:
            tl.setStyleSheet("color:rgba(80,30,45,0.6);font-size:16px;font-weight:500")
        header.addWidget(tl); header.addStretch()
        close_btn = QPushButton("×"); close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            f"color:{'rgba(255,255,255,0.5)' if self._d else 'rgba(200,120,140,0.6)'};"
            f"font-size:20px}}QPushButton:hover{{color:{'#fff' if self._d else '#d4788a'}}}")
        close_btn.clicked.connect(dlg.close)
        header.addWidget(close_btn)
        wl.addLayout(header)

        if chart_type == "gantt":       w = _GanttWidget(self)
        elif chart_type == "line":      w = _LineAreaWidget(self, "line")
        elif chart_type == "area":      w = _LineAreaWidget(self, "area")
        elif chart_type == "dough":     w = _DoughWidget(self)
        elif chart_type == "analytics": w = _AnalyticsWidget(self)
        else:                           w = _BarWidget(self)

        # 底部空白 300px ≈ 程序回退最大距离，刚好吸收回退
        # viewport ≈ 580，内容 ~350
        w.setFixedSize(780, 880)

        scroll = QScrollArea(); scroll.setWidgetResizable(False); scroll.setWidget(w)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        scroll.setFrameShape(QFrame.NoFrame)
        wl.addWidget(scroll)

        layout.addWidget(wrapper)
        self._modal_open = True
        dlg.exec()
        self._modal_open = False

    def tick(self): pass


# ═══════════════════════════════════════════
#  PerfWindow — 弹出窗口
# ═══════════════════════════════════════════

class PerfWindow(QDialog):
    _instances = []

    @classmethod
    def open(cls, parent=None, m=None):
        w = cls(m or get_monitor(), parent)
        w.show()
        return w

    def __init__(self, m=None, p=None):
        super().__init__(p)
        self.setWindowTitle("性能监控")
        self.setMinimumSize(900, 700)
        self.resize(1000, 800)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag = None

        self._chart = PerfChart(m, self)
        self._chart._st(False)  # 默认浅色模式

        o = QVBoxLayout(self)
        o.setContentsMargins(0, 0, 0, 0); o.setAlignment(Qt.AlignCenter)
        self._cd = QWidget()
        cl = QVBoxLayout(self._cd)
        cl.setContentsMargins(16, 12, 16, 12); cl.setSpacing(12)

        tb = QHBoxLayout()
        self._title_lbl = QLabel("性能监控")
        tb.addWidget(self._title_lbl); tb.addStretch()
        close_btn = QPushButton("×"); close_btn.setFixedSize(36, 36)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:rgba(255,255,255,0.5);"
            "font-size:22px}QPushButton:hover{color:#fff}")
        close_btn.clicked.connect(self.close)
        self._close_btn = close_btn  # 保存引用供主题切换
        tb.addWidget(close_btn)
        cl.addLayout(tb)

        cl.addWidget(self._chart, stretch=1)
        o.addWidget(self._cd)
        self._chart._theme_cb = self._update_window_theme
        self._update_window_theme()  # 初始化主题（在 _title_lbl 创建之后）
        self._instances.append(self)

    def _update_window_theme(self):
        dark = self._chart._d
        if dark:
            self._cd.setStyleSheet("background:#1a1b25;border:1px solid rgba(255,255,255,0.06);border-radius:14px")
            self._title_lbl.setStyleSheet("color:rgba(255,255,255,0.8);font-size:18px;font-weight:500")
        else:
            self._cd.setStyleSheet("background:#fff;border:1px solid rgba(210,120,140,0.22);border-radius:14px")
            self._title_lbl.setStyleSheet("color:rgba(80,30,45,0.82);font-size:18px;font-weight:500")
        # 关闭按钮跟随主题
        if hasattr(self, '_close_btn'):
            self._close_btn.setStyleSheet(
                "QPushButton{background:transparent;border:none;"
                f"color:{'rgba(255,255,255,0.5)' if dark else 'rgba(200,120,140,0.6)'};"
                f"font-size:22px}}QPushButton:hover{{color:{'#fff' if dark else '#d4788a'}}}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._drag:
            d = e.globalPosition().toPoint() - self._drag
            self.move(self.x() + d.x(), self.y() + d.y())
            self._drag = e.globalPosition().toPoint()

    def mouseReleaseEvent(self, e): self._drag = None

    def closeEvent(self, e):
        if self in self._instances: self._instances.remove(self)
        super().closeEvent(e)

    @classmethod
    def open(cls, parent=None, m=None):
        w = cls(m or get_monitor(), parent); w.show(); return w
