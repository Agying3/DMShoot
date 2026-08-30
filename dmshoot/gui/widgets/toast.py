"""非模态轻提示，同一宿主窗口只显示一个。"""

from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow, QWidget,
)


_ICONS = {
    "info": "i",
    "success": "✓",
    "warning": "!",
}


class Toast(QFrame):
    """停靠在宿主右下角的自动消失提示。"""

    def __init__(self, parent: QWidget, text: str, kind: str, duration: int):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("kind", kind if kind in _ICONS else "info")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 14, 9)
        layout.setSpacing(9)
        icon = QLabel(_ICONS.get(kind, "i"))
        icon.setObjectName("toastIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(20, 20)
        message = QLabel(text)
        message.setObjectName("toastText")
        message.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(message, 1)

        available = max(160, min(360, parent.width() - 32))
        message.setMaximumWidth(max(110, available - 56))
        self.setMaximumWidth(available)
        self.adjustSize()
        self.setFixedWidth(min(available, max(220, self.sizeHint().width())))

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)
        self._duration = max(600, duration)
        self._dismissing = False
        parent.installEventFilter(self)
        QTimer.singleShot(0, self._show_animated)

    def _show_animated(self):
        self._position()
        self.show()
        self.raise_()
        self._animation.stop()
        self._animation.setDuration(120)
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.start()
        self._dismiss_timer.start(self._duration)

    def _position(self):
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(
            max(16, parent.width() - self.width() - 18),
            max(16, parent.height() - self.height() - 18),
        )

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show):
            self._position()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dismiss()
        super().mousePressEvent(event)

    def dismiss(self):
        if self.isHidden() or self._dismissing:
            return
        self._dismissing = True
        self._dismiss_timer.stop()
        self._animation.stop()
        self._animation.setDuration(160)
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.InCubic)
        self._animation.finished.connect(self.close)
        self._animation.start()

    def closeEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
            if getattr(parent, "_dmshoot_toast", None) is self:
                parent._dmshoot_toast = None
        super().closeEvent(event)


def show_toast(parent: QWidget, text: str, kind: str = "info", duration: int = 2000):
    """显示轻提示；新提示会替换同一窗口中的旧提示。"""
    if parent is None:
        return None
    host = parent.centralWidget() if isinstance(parent, QMainWindow) else parent
    current = getattr(host, "_dmshoot_toast", None)
    if current is not None:
        current.close()
    toast = Toast(host, text, kind, duration)
    host._dmshoot_toast = toast
    return toast
