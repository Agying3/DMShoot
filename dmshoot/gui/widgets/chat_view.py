"""对话视图：Telegram 风格消息分组、气泡和头像吸附。"""

from datetime import date, datetime
from pathlib import Path
import hashlib

import markdown

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QTextBrowser, QPushButton, QFrame,
)
from PySide6.QtCore import QEvent, Qt, QTimer, QRect, QSize, QPoint
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap, QPen, QTextOption,
)

from dmshoot.storage.models import ChatMessage
from dmshoot.gui.app_icon import application_icon_path


AVATAR_SIZE = 36
AVATAR_SLOT_WIDTH = 52
AVATAR_STICK_BOTTOM = 4
BUBBLE_RADIUS = 13
SEAM_RADIUS = 4
GROUP_SPACING = 9
MESSAGE_SEAM = 2
MESSAGE_BURST_WINDOW = 60
MAX_BUBBLE_WIDTH = 480
BUBBLE_FONT_FAMILY = "Microsoft YaHei"
BUBBLE_FONT_SIZE = 16
META_FONT_SIZE = 12
BUBBLE_MIN_HEIGHT = 30
CHECK_FONT_SIZE = 11
BUBBLE_TAIL_WIDTH = 6
BUBBLE_TAIL_HEIGHT = 7
BUBBLE_PADDING_LEFT = 8
BUBBLE_PADDING_RIGHT = 7
BUBBLE_PADDING_TOP = 4
BUBBLE_PADDING_BOTTOM = 5
BUBBLE_META_SPACING = 4
META_ITEM_SPACING = 2
CHECK_WIDTH = 18

INCOMING_BUBBLE_COLOR = "#212121"
OUTGOING_BUBBLE_COLOR = "#8774E1"
INCOMING_META_COLOR = "#A7A7A7"
OUTGOING_META_COLOR = "#B3A7EC"
OUTGOING_CHECK_COLOR = "#F7F4FF"


def _message_is_self(message: ChatMessage) -> bool:
    return bool(message.is_self or message.is_auto)


def _message_date(message: ChatMessage) -> date | None:
    timestamp = message.timestamp or 0
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp).date()
    except (OverflowError, OSError, ValueError):
        return None


def _sender_key(message: ChatMessage) -> str:
    """用稳定身份分组；所有我方消息共用一个 Telegram 消息组。"""
    if _message_is_self(message):
        # AI 本地消息和平台 self 回显的 sender_id 不同，不能拿平台 ID 分组。
        return "self:me"
    identity = message.sender_id or message.sender_name
    return identity or f"unknown:{id(message)}"


def _group_key(message: ChatMessage) -> tuple[str, bool, date | None]:
    return _sender_key(message), _message_is_self(message), _message_date(message)


def _can_join_group(previous: ChatMessage, current: ChatMessage) -> bool:
    """相邻消息只按身份、方向和日期分组，时间差只影响组内留白。"""
    return _group_key(previous) == _group_key(current)


def _message_gap_before(previous: ChatMessage | None, current: ChatMessage) -> int:
    """同一轮快速连发保持紧凑，隔了一段时间则留出清晰呼吸位。"""
    if previous is None:
        return 0
    previous_ts = float(previous.timestamp or 0)
    current_ts = float(current.timestamp or 0)
    if previous_ts <= 0 or current_ts <= 0:
        return 0
    return 8 if abs(current_ts - previous_ts) > MESSAGE_BURST_WINDOW else 0


def _group_messages(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """按相邻发送者、方向和日期分组，日期变化会强制断组。"""
    groups: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    for message in messages:
        if current and not _can_join_group(current[-1], message):
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    return groups


def _avatar_cache_path(url: str) -> Path | None:
    if not url:
        return None
    candidate = Path(url)
    if candidate.exists() and candidate.is_file():
        return candidate
    project_root = Path(__file__).parents[3]
    cached = project_root / "dmshoot" / "data" / "avatars" / f"{hashlib.md5(url.encode()).hexdigest()[:16]}.png"
    return cached if cached.exists() else None


class AvatarWidget(QWidget):
    """36px 圆形头像；网络头像只读取已有本地缓存，不在聊天渲染时发请求。"""

    def __init__(self, text: str = "?", avatar_url: str = "", parent=None):
        super().__init__(parent)
        self.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self._text = (text or "?")[:2]
        self._pixmap = QPixmap()
        self.set_avatar(avatar_url)

    def set_avatar(self, avatar_url: str = ""):
        path = _avatar_cache_path(avatar_url)
        self._pixmap = QPixmap(str(path)) if path else QPixmap()
        self.update()

    def set_text(self, text: str):
        self._text = (text or "?")[:2]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        path = QPainterPath()
        path.addEllipse(rect)
        painter.setClipPath(path)

        if not self._pixmap.isNull():
            pixmap = self._pixmap.scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            source_x = max(0, (pixmap.width() - rect.width()) // 2)
            source_y = max(0, (pixmap.height() - rect.height()) // 2)
            painter.drawPixmap(rect, pixmap, QRect(source_x, source_y, rect.width(), rect.height()))
        else:
            painter.fillPath(path, QColor("#394B63"))
            painter.setPen(QColor(255, 255, 255, 220))
            painter.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.DemiBold))
            painter.drawText(rect, Qt.AlignCenter, self._text)
        painter.end()


def _rounded_path(left: float, top: float, right: float, bottom: float,
                  radii: tuple[int, int, int, int]) -> QPainterPath:
    """绘制四角可独立控制的圆角矩形，顺序为左上、右上、右下、左下。"""
    top_left, top_right, bottom_right, bottom_left = radii
    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    max_radius = min(width, height) / 2
    top_left = min(top_left, max_radius)
    top_right = min(top_right, max_radius)
    bottom_right = min(bottom_right, max_radius)
    bottom_left = min(bottom_left, max_radius)
    k = 0.5522848

    path = QPainterPath()
    path.moveTo(left + top_left, top)
    path.lineTo(right - top_right, top)
    path.cubicTo(
        right - top_right + top_right * k, top,
        right, top + top_right - top_right * k,
        right, top + top_right,
    )
    path.lineTo(right, bottom - bottom_right)
    path.cubicTo(
        right, bottom - bottom_right + bottom_right * k,
        right - bottom_right + bottom_right * k, bottom,
        right - bottom_right, bottom,
    )
    path.lineTo(left + bottom_left, bottom)
    path.cubicTo(
        left + bottom_left - bottom_left * k, bottom,
        left, bottom - bottom_left + bottom_left * k,
        left, bottom - bottom_left,
    )
    path.lineTo(left, top + top_left)
    path.cubicTo(
        left, top + top_left - top_left * k,
        left + top_left - top_left * k, top,
        left + top_left, top,
    )
    path.closeSubpath()
    return path


class CheckLabel(QLabel):
    """自绘 Telegram 双勾，避免 Windows 字体缺少勾形导致方框或裁切。"""

    def __init__(self, parent=None):
        super().__init__("✓✓", parent)
        self.setObjectName("tgBubbleCheck")
        self.setFixedSize(CHECK_WIDTH, 15)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.NoBrush)
        pen_color = self.palette().color(self.foregroundRole())
        if not pen_color.isValid() or pen_color.alpha() == 0:
            pen_color = QColor(247, 244, 255)
        pen = QPen(pen_color)
        pen.setWidthF(1.25)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for offset in (0, 5):
            painter.drawLine(offset + 1, 7, offset + 4, 10)
            painter.drawLine(offset + 4, 10, offset + 9, 3)
        painter.end()


class BubbleWidget(QFrame):
    """一条 Telegram 气泡，时间戳嵌在正文右下角。"""

    def __init__(
        self,
        message: ChatMessage = None,
        position: str = "single",
        parent=None,
        content_family: str = "",
        meta_family: str = "",
    ):
        super().__init__(parent)
        self.setObjectName("tgBubble")
        # 气泡按内容自然撑高；不能让组布局把短消息均分成大块空白。
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._message = None
        self._is_self = False
        self._position = "single"
        self._max_width = MAX_BUBBLE_WIDTH
        self._radii = (BUBBLE_RADIUS,) * 4
        self._tail_side = ""
        self._natural_height = 0
        self._content_family = content_family or BUBBLE_FONT_FAMILY
        self._meta_family = meta_family or "Segoe UI"

        self._content_font = QFont(self._content_family)
        self._content_font.setPixelSize(BUBBLE_FONT_SIZE)
        self._content_font.setWeight(QFont.Weight.Normal)
        self._meta_font = QFont(self._meta_family)
        self._meta_font.setPixelSize(META_FONT_SIZE)

        self._content_label = QLabel()
        self._content_label.setObjectName("tgBubbleText")
        self._content_label.setFont(self._content_font)
        self._content_label.setTextFormat(Qt.PlainText)
        self._content_label.setWordWrap(True)
        self._content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._content_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._meta_label = QLabel()
        self._meta_label.setObjectName("tgBubbleMeta")
        self._meta_label.setFont(self._meta_font)
        self._meta_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self._meta_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._check_label = CheckLabel()
        self._check_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self._check_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._check_label.hide()

        self._meta_widget = QWidget()
        self._meta_widget.setObjectName("tgBubbleMetaWidget")
        meta_layout = QHBoxLayout(self._meta_widget)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(META_ITEM_SPACING)
        meta_layout.addWidget(self._meta_label, 0, Qt.AlignBottom)
        meta_layout.addWidget(self._check_label, 0, Qt.AlignBottom)

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(
            BUBBLE_PADDING_LEFT, BUBBLE_PADDING_TOP,
            BUBBLE_PADDING_RIGHT, BUBBLE_PADDING_BOTTOM,
        )
        self._row.setSpacing(BUBBLE_META_SPACING)
        self._row.addWidget(self._content_label, 0, Qt.AlignBottom)
        self._row.addWidget(self._meta_widget, 0, Qt.AlignBottom)

        if message is not None:
            self.rebind(message, position)

    def rebind(self, message: ChatMessage, position: str = "single"):
        self._message = message
        self._is_self = _message_is_self(message)
        self._content_label.setText(message.content or "")
        timestamp = message.timestamp or 0
        try:
            time_text = datetime.fromtimestamp(timestamp).strftime("%H:%M") if timestamp > 0 else ""
        except (OverflowError, OSError, ValueError):
            time_text = ""
        self._meta_label.setText(time_text)
        self._meta_label.setVisible(bool(time_text))
        self._check_label.setVisible(self._is_self and bool(time_text))
        self._check_label.setStyleSheet(
            f"color: {OUTGOING_CHECK_COLOR}; background: transparent;"
        )
        self._meta_label.setFixedWidth(
            QFontMetrics(self._meta_font).horizontalAdvance(time_text)
            if time_text else 0
        )
        self._check_label.setFixedWidth(CHECK_WIDTH if self._is_self and time_text else 0)
        self.set_position(position)
        self._refresh_width()

    def set_font_families(self, content_family: str, meta_family: str):
        """切换字体后重测气泡，避免新 family 沿用旧字宽。"""
        self._content_family = content_family or BUBBLE_FONT_FAMILY
        self._meta_family = meta_family or "Segoe UI"
        self._content_font = QFont(self._content_family)
        self._content_font.setPixelSize(BUBBLE_FONT_SIZE)
        self._content_font.setWeight(QFont.Weight.Normal)
        self._meta_font = QFont(self._meta_family)
        self._meta_font.setPixelSize(META_FONT_SIZE)
        self._content_label.setFont(self._content_font)
        self._meta_label.setFont(self._meta_font)
        meta_text = self._meta_label.text()
        self._meta_label.setFixedWidth(
            QFontMetrics(self._meta_font).horizontalAdvance(meta_text)
            if meta_text else 0
        )
        self.set_position(self._position)
        self._refresh_width()

    def set_position(self, position: str):
        self._position = position if position in {"single", "first", "middle", "last"} else "single"
        # Telegram Web keeps the tail-opposite side round. Consecutive rows
        # compact only the tail-side corners; the final row then adds a tail.
        self._radii = (BUBBLE_RADIUS,) * 4
        if self._position == "first":
            self._radii = (
                (BUBBLE_RADIUS, BUBBLE_RADIUS, SEAM_RADIUS, BUBBLE_RADIUS)
                if self._is_self
                else (BUBBLE_RADIUS, BUBBLE_RADIUS, BUBBLE_RADIUS, SEAM_RADIUS)
            )
        elif self._position in {"middle", "last"}:
            self._radii = (
                (BUBBLE_RADIUS, SEAM_RADIUS, SEAM_RADIUS, BUBBLE_RADIUS)
                if self._is_self
                else (SEAM_RADIUS, BUBBLE_RADIUS, BUBBLE_RADIUS, SEAM_RADIUS)
            )
        self._tail_side = ""
        if self._position in {"single", "last"}:
            self._tail_side = "right" if self._is_self else "left"

        tail_left = BUBBLE_TAIL_WIDTH if self._tail_side == "left" else 0
        tail_right = BUBBLE_TAIL_WIDTH if self._tail_side == "right" else 0
        self._row.setContentsMargins(
            BUBBLE_PADDING_LEFT + tail_left, BUBBLE_PADDING_TOP,
            BUBBLE_PADDING_RIGHT + tail_right, BUBBLE_PADDING_BOTTOM,
        )

        text_color = "#FFFFFF"
        meta_color = OUTGOING_META_COLOR if self._is_self else INCOMING_META_COLOR
        # 保留 radius 信息供调试和旧测试读取；实际轮廓由 paintEvent 绘制，
        # 因此尾巴不会被 QSS 的矩形裁掉。
        top_left, top_right, bottom_right, bottom_left = self._radii
        self.setStyleSheet(
            "QFrame#tgBubble { background: transparent; border: none;"
            f" border-top-left-radius: {top_left}px;"
            f" border-top-right-radius: {top_right}px;"
            f" border-bottom-right-radius: {bottom_right}px;"
            f" border-bottom-left-radius: {bottom_left}px; }}"
            f"QLabel#tgBubbleText {{ color: {text_color}; background: transparent;"
            f' font-family: "{self._content_family}"; font-size: {BUBBLE_FONT_SIZE}px; font-weight: 400; }}'
            f'QLabel#tgBubbleMeta {{ color: {meta_color}; background: transparent;'
            f' font-family: "{self._meta_family}"; font-size: {META_FONT_SIZE}px; }}'
            f'QLabel#tgBubbleCheck {{ color: {OUTGOING_CHECK_COLOR}; background: transparent; }}'
        )
        self.update()

    def set_max_width(self, width: int):
        self._max_width = max(140, min(MAX_BUBBLE_WIDTH, int(width)))
        self._refresh_width()

    def _refresh_width(self):
        if self._message is None:
            return
        # 用实际显示字体测量。元信息先占位，再决定正文是否换行，
        # 这样长消息不会把时间或双勾挤进正文。
        metrics = QFontMetrics(self._content_font)
        text = self._message.content or ""
        longest_line = max((metrics.horizontalAdvance(line) for line in text.split("\n")), default=0)
        has_meta = bool(self._meta_label.text())
        has_check = self._is_self and has_meta
        meta_width = 0
        if has_meta:
            meta_width = QFontMetrics(self._meta_font).horizontalAdvance(self._meta_label.text())
        check_width = CHECK_WIDTH if has_check else 0
        meta_total = meta_width + (META_ITEM_SPACING + check_width if check_width else 0)
        margins = self._row.contentsMargins()
        horizontal = margins.left() + margins.right()
        desired = horizontal + longest_line + (BUBBLE_META_SPACING if meta_total else 0) + meta_total
        width = max(72, min(self._max_width, desired))

        content_width = max(
            1,
            width - horizontal
            - (BUBBLE_META_SPACING if meta_total else 0)
            - meta_total,
        )
        wrapped = "\n" in text or desired >= self._max_width
        if not wrapped:
            content_width = max(1, longest_line)
        self._content_label.setWordWrap(wrapped)
        self._content_label.setFixedWidth(content_width)
        measured_height = self._content_label.heightForWidth(content_width)
        if measured_height <= 0:
            line_count = max(1, len(text.split("\n")))
            measured_height = metrics.lineSpacing() * line_count
        content_height = max(metrics.height(), measured_height)
        self._content_label.setFixedHeight(content_height)
        self._meta_widget.setFixedWidth(meta_total)
        self._meta_widget.setFixedHeight(max(
            self._meta_label.sizeHint().height() if has_meta else 0,
            self._check_label.height() if has_check else 0,
        ))
        self._natural_height = max(
            BUBBLE_MIN_HEIGHT,
            margins.top() + margins.bottom() + max(
                content_height,
                self._meta_label.sizeHint().height() if has_meta else 0,
            ),
        )
        self.setFixedWidth(width)
        self.setFixedHeight(self._natural_height)
        self.updateGeometry()

    def sizeHint(self):
        if self._message is not None and self._natural_height:
            return QSize(self.width(), self._natural_height)
        return super().sizeHint()

    def minimumSizeHint(self):
        if self._message is not None and self._natural_height:
            return QSize(self.width(), self._natural_height)
        return super().minimumSizeHint()

    def _bubble_path(self) -> QPainterPath:
        """绘制连续外轮廓，尾巴与主体共用边界，不产生黑色接缝。"""
        width = float(self.width())
        height = float(self.height())
        if self._tail_side == "right":
            body_right = max(0.0, width - BUBBLE_TAIL_WIDTH)
            top_left, top_right, _, bottom_left = self._radii
            path = QPainterPath()
            path.moveTo(top_left, 0)
            path.lineTo(body_right - top_right, 0)
            path.cubicTo(
                body_right - top_right + top_right * 0.5522848, 0,
                body_right, top_right - top_right * 0.5522848,
                body_right, top_right,
            )
            path.lineTo(body_right, max(top_right, height - BUBBLE_TAIL_HEIGHT))
            path.cubicTo(
                body_right + 1, height - 4,
                body_right + 4, height - 1,
                width, height,
            )
            path.lineTo(max(0.0, body_right - 8), height)
            path.lineTo(bottom_left, height)
            path.cubicTo(
                bottom_left - bottom_left * 0.5522848, height,
                0, height - bottom_left + bottom_left * 0.5522848,
                0, height - bottom_left,
            )
            path.lineTo(0, top_left)
            path.cubicTo(
                0, top_left - top_left * 0.5522848,
                top_left - top_left * 0.5522848, 0,
                top_left, 0,
            )
            path.closeSubpath()
            return path
        if self._tail_side == "left":
            body_left = min(width, float(BUBBLE_TAIL_WIDTH))
            top_left, top_right, bottom_right, _ = self._radii
            path = QPainterPath()
            path.moveTo(body_left + top_left, 0)
            path.lineTo(width - top_right, 0)
            path.cubicTo(
                width - top_right + top_right * 0.5522848, 0,
                width, top_right - top_right * 0.5522848,
                width, top_right,
            )
            path.lineTo(width, height - bottom_right)
            path.cubicTo(
                width, height - bottom_right + bottom_right * 0.5522848,
                width - bottom_right + bottom_right * 0.5522848, height,
                width - bottom_right, height,
            )
            path.lineTo(body_left + 8, height)
            path.cubicTo(
                body_left + 4, height - 1,
                body_left + 1, height - 4,
                0, height,
            )
            path.lineTo(body_left, max(top_left, height - BUBBLE_TAIL_HEIGHT))
            path.lineTo(body_left, top_left)
            path.cubicTo(
                body_left, top_left - top_left * 0.5522848,
                body_left + top_left - top_left * 0.5522848, 0,
                body_left + top_left, 0,
            )
            path.closeSubpath()
            return path
        return _rounded_path(0, 0, width, height, self._radii)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        if self._is_self:
            painter.setBrush(QColor(OUTGOING_BUBBLE_COLOR))
        else:
            painter.setBrush(QColor(INCOMING_BUBBLE_COLOR))
        painter.drawPath(self._bubble_path())
        painter.end()


class BubbleRowWidget(QWidget):
    """让组尾的尾巴向外伸，而不是挤掉同组消息的对齐边。"""

    def __init__(self, bubble: BubbleWidget, is_self: bool, parent=None, top_gap: int = 0):
        super().__init__(parent)
        self.bubble = bubble
        self._top_gap = max(0, int(top_gap))
        self._tail_gutter = BUBBLE_TAIL_WIDTH if not bubble._tail_side else 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, self._top_gap, 0, 0)
        layout.setSpacing(0)
        if is_self:
            layout.addStretch(1)
            layout.addWidget(bubble, 0, Qt.AlignRight)
            if self._tail_gutter:
                layout.addSpacing(self._tail_gutter)
        else:
            if self._tail_gutter:
                layout.addSpacing(self._tail_gutter)
            layout.addWidget(bubble, 0, Qt.AlignLeft)
            layout.addStretch(1)
        self.sync_height()

    @property
    def tail_gutter(self) -> int:
        return self._tail_gutter

    def sync_height(self):
        height = max(1, self.bubble.height() + self._top_gap)
        if self.height() != height:
            self.setFixedHeight(height)
        self.updateGeometry()


class MessageGroupWidget(QWidget):
    """一个发送者在同一天连续发送的消息组，头像独立于消息栈滚动。"""

    def __init__(
        self,
        messages: list[ChatMessage],
        peer_avatar_url: str = "",
        parent=None,
        my_avatar_url: str = "",
    ):
        super().__init__(parent)
        # 组只在横向填满聊天区，纵向保持气泡栈的自然高度，避免和底部 stretch 平分空白。
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._messages: list[ChatMessage] = []
        self._group_key = None
        self._peer_avatar_url = peer_avatar_url
        self._my_avatar_url = my_avatar_url
        self._bubble_rows: list[BubbleRowWidget] = []
        self._sender_labels: list[QLabel] = []
        self._avatar_y: int | None = None
        self._content_family = "Microsoft YaHei"
        self._meta_family = "Segoe UI"

        self.avatar_slot = QWidget(self)
        self.avatar_slot.setFixedWidth(AVATAR_SLOT_WIDTH)
        self.avatar_slot.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.avatar = AvatarWidget(parent=self.avatar_slot)

        self.stack = QVBoxLayout()
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.setSpacing(MESSAGE_SEAM)
        self.stack.setAlignment(Qt.AlignTop)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.rebind(messages, peer_avatar_url, self._my_avatar_url)

    @property
    def group_key(self):
        return self._group_key

    @property
    def is_self(self) -> bool:
        return bool(self._messages and _message_is_self(self._messages[0]))

    @property
    def last_date(self) -> date | None:
        return _message_date(self._messages[-1]) if self._messages else None

    def can_append(self, message: ChatMessage) -> bool:
        return bool(self._messages and _can_join_group(self._messages[-1], message))

    def rebind(
        self,
        messages: list[ChatMessage],
        peer_avatar_url: str = "",
        my_avatar_url: str = "",
    ):
        self.setMinimumHeight(0)
        self._avatar_y = None
        self._messages = list(messages)
        self._peer_avatar_url = peer_avatar_url or self._peer_avatar_url
        self._my_avatar_url = my_avatar_url or self._my_avatar_url
        self._group_key = _group_key(self._messages[0]) if self._messages else None
        self._clear_stack()

        if not self._messages:
            return
        first = self._messages[0]
        is_self = _message_is_self(first)
        sender_name = first.sender_name or ("AI" if first.is_auto else "")
        avatar_text = ("AI" if first.is_auto else "我") if is_self else (sender_name or "?")
        self.avatar.set_text(avatar_text)
        self.avatar.set_avatar(self._my_avatar_url if is_self else self._peer_avatar_url)

        if not is_self and sender_name:
            name_label = QLabel(sender_name)
            name_label.setObjectName("tgSenderName")
            name_label.setFont(QFont(self._content_family, 13, QFont.Weight.DemiBold))
            self._sender_labels.append(name_label)
            self.stack.addWidget(name_label, 0, Qt.AlignLeft)

        for index, message in enumerate(self._messages):
            if len(self._messages) == 1:
                position = "single"
            elif index == 0:
                position = "first"
            elif index == len(self._messages) - 1:
                position = "last"
            else:
                position = "middle"
            bubble = BubbleWidget(
                message,
                position,
                content_family=self._content_family,
                meta_family=self._meta_family,
            )
            previous = self._messages[index - 1] if index else None
            row = BubbleRowWidget(
                bubble,
                is_self,
                self,
                top_gap=_message_gap_before(previous, message),
            )
            self._bubble_rows.append(row)
            self.stack.addWidget(row)

        if is_self:
            self._layout.addLayout(self.stack, 1)
            self._layout.addWidget(self.avatar_slot, 0)
        else:
            self._layout.addWidget(self.avatar_slot, 0)
            self._layout.addLayout(self.stack, 1)
        self._refresh_minimum_height()
        self._refresh_avatar_position()

    def append_message(self, message: ChatMessage):
        if not self.can_append(message):
            return False
        self._messages.append(message)
        self.rebind(self._messages, self._peer_avatar_url, self._my_avatar_url)
        return True

    def set_max_width(self, width: int, refresh: bool = True):
        for row in self._bubble_rows:
            row.bubble.set_max_width(width)
            row.sync_height()
        if refresh:
            self._refresh_minimum_height()
            self.updateGeometry()

    def set_font_families(self, content_family: str, meta_family: str):
        """把聊天组内的正文、元信息和发送者名统一切换到同一模式。"""
        self._content_family = content_family or "Microsoft YaHei"
        self._meta_family = meta_family or "Segoe UI"
        for row in self._bubble_rows:
            row.bubble.set_font_families(self._content_family, self._meta_family)
        for label in self._sender_labels:
            label.setFont(QFont(self._content_family, 13, QFont.Weight.DemiBold))
        self._refresh_minimum_height()
        self.updateGeometry()

    def refresh_layout(self):
        """在子气泡完成字体/宽度计算后同步组的自然高度。"""
        self._refresh_minimum_height()
        self.updateGeometry()

    def _refresh_minimum_height(self):
        for row in self._bubble_rows:
            row.sync_height()
        # 不依赖 QVBoxLayout 尚未完成的 sizeHint，直接按可见子项计算自然高度。
        # 首帧布局时这能避免多条气泡暂时共享同一个旧高度而挤在一起。
        item_count = self.stack.count()
        natural_height = 0
        for index in range(item_count):
            item = self.stack.itemAt(index)
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, BubbleRowWidget):
                child_height = widget.height()
            else:
                # 标签实际高度可能暂时被外层布局拉满；自然高度只能采用
                # sizeHint，否则这次错误分配会把整组气泡永久推到底部。
                child_height = widget.sizeHint().height()
            natural_height += max(1, child_height)
        if item_count > 1:
            natural_height += self.stack.spacing() * (item_count - 1)
        margins = self.stack.contentsMargins()
        natural_height += margins.top() + margins.bottom()
        self.setFixedHeight(max(AVATAR_SIZE, natural_height))
        # 先确定 group 高度，再激活两层布局，确保首帧就拿到正确的 row.y。
        self.stack.invalidate()
        self._layout.invalidate()
        self._layout.activate()
        self.stack.activate()

    def _clear_stack(self):
        self._bubble_rows.clear()
        self._sender_labels.clear()
        while self.stack.count():
            item = self.stack.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        while self._layout.count():
            self._layout.takeAt(0)

    def _refresh_avatar_position(self):
        slot_height = max(0, self.avatar_slot.height())
        max_offset = max(0, self.height() - AVATAR_SIZE)
        if self._avatar_y is None:
            y = max(0, slot_height - AVATAR_SIZE)
        else:
            y = max(0, min(self._avatar_y, max_offset))
        self._avatar_y = y
        self.avatar.move((AVATAR_SLOT_WIDTH - AVATAR_SIZE) // 2, y)

    def update_avatar_position(self, viewport: QWidget, viewport_height: int):
        # 直接读取组在 viewport 中的实际坐标，避免 scrollbar value、内容
        # 容器边距和 QScrollArea frame 之间出现一像素到多像素的偏移。
        group_top = self.mapTo(viewport, QPoint(0, 0)).y()
        max_offset = max(0, self.height() - AVATAR_SIZE)
        stick_vp = viewport_height - AVATAR_SIZE - AVATAR_STICK_BOTTOM
        target = stick_vp - group_top
        y = max(0, min(target, max_offset))
        self._avatar_y = y
        self.avatar.move((AVATAR_SLOT_WIDTH - AVATAR_SIZE) // 2, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_avatar_position()


class DateSeparatorWidget(QFrame):
    """日期变化时的居中胶囊，同时切断消息分组。"""

    def __init__(self, day: date, parent=None, font_family: str = "Microsoft YaHei"):
        super().__init__(parent)
        self.setObjectName("tgDateSeparator")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        label = QLabel(f"{day.year}年{day.month}月{day.day}日")
        label.setObjectName("tgDateText")
        label.setFont(QFont(font_family, 12))
        label.setAlignment(Qt.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(label, 0, Qt.AlignCenter)
        layout.addStretch(1)

    def set_font_family(self, font_family: str):
        for index in range(self.layout().count()):
            widget = self.layout().itemAt(index).widget()
            if isinstance(widget, QLabel):
                widget.setFont(QFont(font_family or "Microsoft YaHei", 12))


class ChatView(QWidget):
    def __init__(self, font_manager=None):
        super().__init__()
        self._font_manager = font_manager
        self._font_mode = getattr(font_manager, "current_mode", "system")
        if font_manager is not None:
            self._content_family, self._meta_family = font_manager.chat_families(self._font_mode)
        else:
            self._content_family, self._meta_family = "Microsoft YaHei", "Segoe UI"
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title_row = QWidget()
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(16, 12, 16, 12)
        title_layout.setSpacing(8)
        self.title_icon = QLabel()
        self.title_icon.setFixedSize(20, 20)
        self.title_icon.setScaledContents(True)
        self.title_icon.hide()
        title_layout.addWidget(self.title_icon)
        self.title_label = QLabel("选择会话")
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setStyleSheet("font-size: 15px;")
        title_layout.addWidget(self.title_label, stretch=1)
        layout.addWidget(title_row)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("chatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.bubble_container = QWidget()
        self.bubble_container.setObjectName("chatBubbleContainer")
        self.bubble_layout = QVBoxLayout()
        self.bubble_layout.setContentsMargins(8, 8, 8, 8)
        self.bubble_layout.setSpacing(GROUP_SPACING)
        self.bubble_layout.addStretch()
        self.bubble_container.setLayout(self.bubble_layout)

        self.scroll.setWidget(self.bubble_container)
        layout.addWidget(self.scroll, stretch=1)
        self.setLayout(layout)

        self._conversation_id = ""
        self._peer_avatar_url = ""
        self._my_avatar_url = ""
        self._content_items: list[QWidget] = []
        self._display_messages: list[ChatMessage] = []
        self._new_message_count = 0
        self._placeholder = None
        self._md_browser = None
        self._new_message_button = QPushButton(self.scroll.viewport())
        self._new_message_button.setObjectName("newMessagesButton")
        self._new_message_button.setFixedSize(132, 32)
        self._new_message_button.setFocusPolicy(Qt.NoFocus)
        self._new_message_button.setCursor(Qt.PointingHandCursor)
        self._new_message_button.clicked.connect(self._jump_to_latest)
        self._new_message_button.hide()
        self.scroll.viewport().installEventFilter(self)
        self.bubble_container.installEventFilter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._smart_scroll)
        self._scroll_force = False
        self._history_pending: list[ChatMessage] = []
        self._history_timer = QTimer(self)
        self._history_timer.setInterval(30)
        self._history_timer.timeout.connect(self._load_history_chunk)

    def set_conversation(self, conversation_id: str, peer_avatar_url: str = ""):
        self._conversation_id = conversation_id or ""
        self._peer_avatar_url = peer_avatar_url or ""

    def set_account_avatar(self, avatar_url: str = ""):
        """更新当前账号头像，并立即刷新已显示的消息组。"""
        self._my_avatar_url = avatar_url or ""
        if self._display_messages:
            self._render_message_items(self._display_messages, preserve_scroll=True)

    def set_font_mode(self, mode: str):
        """切换聊天字体并重新测量已显示的气泡。"""
        self._font_mode = mode
        if self._font_manager is not None:
            self._content_family, self._meta_family = self._font_manager.chat_families(mode)
        else:
            self._content_family, self._meta_family = "Microsoft YaHei", "Segoe UI"
        for item in self._content_items:
            if isinstance(item, MessageGroupWidget):
                item.set_font_families(self._content_family, self._meta_family)
            elif isinstance(item, DateSeparatorWidget):
                item.set_font_family(self._content_family)
        self._update_bubble_widths()
        self._refresh_group_heights()
        self._update_avatar_positions()

    def show_placeholder(self, text: str):
        """显示空状态引导文字。"""
        self.title_icon.hide()
        self.title_label.setText("")
        self._clear_content()
        self._placeholder = QLabel(text)
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet(
            "color: rgba(255,255,255,0.35); font-size: 14px; padding: 40px;"
        )
        self.bubble_layout.insertWidget(self.bubble_layout.count() - 1, self._placeholder)

    def _clear_content(self):
        """清除所有消息、Markdown 和占位内容。"""
        self._reset_new_message_notice()
        self._history_timer.stop()
        self._history_pending.clear()
        self._display_messages.clear()
        self._content_items.clear()
        while self.bubble_layout.count():
            item = self.bubble_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._placeholder = None
        self._md_browser = None
        self.bubble_layout.addStretch()

    _MD_CSS = """
        body {
            font-family: "CHAT_FONT_FAMILY", "Microsoft YaHei", "Segoe UI", sans-serif;
            line-height: 1.8; background: transparent; color: #cdd6f4;
            padding: 16px 20px; margin: 0;
        }
        h1 { color: #cba6f7; border-bottom: 2px solid rgba(255,255,255,0.1); padding-bottom: 10px; margin-top: 8px; font-size: 20px; }
        h2 { color: #89b4fa; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 6px; margin-top: 24px; font-size: 16px; }
        h3 { color: #a6e3a1; margin-top: 18px; font-size: 14px; }
        table { border-collapse: collapse; width: 100%; margin: 12px 0; }
        th { background: rgba(255,255,255,0.08); color: #f5c2e7; padding: 8px 10px; text-align: left; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.12); }
        td { border-bottom: 1px solid rgba(255,255,255,0.06); padding: 8px 10px; font-size: 12px; }
        tr:nth-child(even) td { background: rgba(255,255,255,0.02); }
        code { background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 3px; font-family: 'Consolas', monospace; font-size: 12px; }
        pre { background: rgba(0,0,0,0.25); padding: 12px 16px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
        pre code { background: none; padding: 0; }
        hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 20px 0; }
        blockquote { border-left: 3px solid #cba6f7; padding-left: 14px; margin-left: 0; color: #a6adc8; }
        a { color: #89b4fa; text-decoration: none; }
        strong { color: #f9e2af; }
        em { color: #f38ba8; }
        ul, ol { padding-left: 20px; }
        li { margin: 4px 0; }
        p { margin: 8px 0; }
    """

    def show_markdown(self, md_path: str, title: str = ""):
        """渲染 Markdown，替代空白聊天区域。"""
        icon_path = application_icon_path()
        if icon_path.is_file():
            self.title_icon.setPixmap(QPixmap(str(icon_path)))
            self.title_icon.show()
        else:
            self.title_icon.hide()
        self.title_label.setText(title)
        self._clear_content()
        self.bubble_layout.takeAt(self.bubble_layout.count() - 1)
        self._md_browser = QTextBrowser()
        self._md_browser.setOpenExternalLinks(True)
        self._md_browser.setFrameShape(QTextBrowser.NoFrame)
        self._md_browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,0.12); border-radius: 4px; min-height: 40px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._md_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._md_browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self._md_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._md_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        try:
            md_content = Path(md_path).read_text(encoding="utf-8")
            html_body = markdown.markdown(
                md_content, extensions=["tables", "fenced_code", "codehilite", "nl2br"],
            )
            safe_family = self._content_family.replace('"', "")
            md_css = self._MD_CSS.replace("CHAT_FONT_FAMILY", safe_family)
            full_html = f"<html><head><style>{md_css}</style></head><body>{html_body}</body></html>"
            self._md_browser.setHtml(full_html)
        except Exception as e:
            self._md_browser.setPlainText(f"无法加载日志：{e}")
        self.bubble_layout.addWidget(self._md_browser, stretch=1)

    def clear_markdown(self):
        """清除 Markdown 视图，恢复消息模式。"""
        self.title_icon.hide()
        self.title_label.setText("选择会话")
        self._clear_content()

    MAX_VISIBLE = 50
    MAX_READING_BUFFER = 20
    # 保留旧方法的兼容常量；打开会话已不再启动历史分批加载。
    HISTORY_CHUNK = 4

    def load_messages(
        self,
        title: str,
        messages: list[ChatMessage],
        peer_avatar_url: str = "",
        my_avatar_url: str = "",
    ):
        """一次性加载当前消息窗口，避免用户看到历史分批重排的中间态。"""
        self.title_icon.hide()
        self._reset_new_message_notice()
        self.title_label.setText(title)
        if peer_avatar_url:
            self._peer_avatar_url = peer_avatar_url
        if my_avatar_url:
            self._my_avatar_url = my_avatar_url
        if self._md_browser or self._placeholder:
            self._clear_content()
        self._history_timer.stop()
        self._history_pending.clear()

        visible_messages = list(messages[-self.MAX_VISIBLE:])
        self._display_messages = visible_messages
        # 批量创建期间不让 viewport 绘制半成品；所有 group 建好后一次显示。
        self.setUpdatesEnabled(False)
        self.scroll.setUpdatesEnabled(False)
        try:
            self._render_message_items(visible_messages)
        finally:
            self.scroll.setUpdatesEnabled(True)
            self.setUpdatesEnabled(True)
        self._schedule_scroll(0, force=True)

    def _render_message_items(self, messages: list[ChatMessage], preserve_scroll: bool = False):
        """按消息组重排；重排时尽量复用同位置、同身份的组控件。"""
        scrollbar = self.scroll.verticalScrollBar()
        old_value = scrollbar.value()
        old_maximum = scrollbar.maximum()
        old_items = list(self._content_items)
        target_items: list[QWidget] = []
        old_index = 0
        previous_day = None

        for group_messages in _group_messages(messages):
            day = _message_date(group_messages[0])
            # 首条消息不需要日期胶囊；只有相邻消息跨天时才插入。
            if previous_day is not None and day is not None and day != previous_day:
                old = old_items[old_index] if old_index < len(old_items) else None
                if isinstance(old, DateSeparatorWidget):
                    separator = old
                    old_index += 1
                else:
                    separator = DateSeparatorWidget(
                        day, self.bubble_container, self._content_family
                    )
                target_items.append(separator)
            previous_day = day

            old = old_items[old_index] if old_index < len(old_items) else None
            group_key = _group_key(group_messages[0])
            if isinstance(old, MessageGroupWidget) and old.group_key == group_key:
                group = old
                group.rebind(
                    group_messages, self._peer_avatar_url, self._my_avatar_url
                )
                old_index += 1
            else:
                group = MessageGroupWidget(
                    group_messages,
                    self._peer_avatar_url,
                    self.bubble_container,
                    self._my_avatar_url,
                )
                group.set_font_families(self._content_family, self._meta_family)
            target_items.append(group)

        reused = set(target_items)
        for old in old_items:
            if old not in reused:
                old.deleteLater()

        while self.bubble_layout.count():
            item = self.bubble_layout.takeAt(0)
            widget = item.widget()
            if widget and widget not in reused:
                widget.deleteLater()
        for widget in target_items:
            self.bubble_layout.addWidget(widget, 0, Qt.AlignTop)
        self.bubble_layout.addStretch()
        self._content_items = target_items
        self._update_bubble_widths()

        def restore_position():
            if preserve_scroll and scrollbar.value() == old_value:
                scrollbar.setValue(old_value + max(0, scrollbar.maximum() - old_maximum))
            self._update_avatar_positions()

        self._defer(restore_position)

    def _load_history_chunk(self):
        if not self._history_pending:
            self._history_timer.stop()
            return
        scrollbar = self.scroll.verticalScrollBar()
        was_at_bottom = self._is_near_bottom()
        old_value = scrollbar.value()
        old_maximum = scrollbar.maximum()
        chunk = self._history_pending[-self.HISTORY_CHUNK:]
        del self._history_pending[-len(chunk):]
        self._display_messages = chunk + self._display_messages
        self._render_message_items(self._display_messages, preserve_scroll=not was_at_bottom)

        def keep_position():
            if was_at_bottom:
                # 历史批次的延迟回调不能抢回用户刚滚动到的位置。
                # 只有滚动条仍在底部时，才执行加载期间的自动跟随。
                if self._is_near_bottom():
                    scrollbar.setValue(scrollbar.maximum())
            elif scrollbar.value() == old_value:
                # 用户未介入时，为保持原消息锚点补上新增历史高度；
                # 如果当前值已变化，说明用户已经主动滚动，应保留其选择。
                scrollbar.setValue(old_value + max(0, scrollbar.maximum() - old_maximum))
            self._update_avatar_positions()

        QTimer.singleShot(0, keep_position)

    def append_message(self, message: ChatMessage):
        from dmshoot.storage.database import deduplicate_messages

        merged = deduplicate_messages(self._display_messages + [message])
        if len(merged) == len(self._display_messages):
            return False
        merged.sort(key=lambda item: (item.timestamp or 0, item.id or 0))
        # 正常实时消息应位于末尾；若收到补发的旧消息，完整重排以免破坏顺序。
        if merged[-1] is not message:
            self._display_messages = merged
            self._render_message_items(merged, preserve_scroll=True)
            return True
        message = merged[-1]
        was_at_bottom = self._is_near_bottom()
        if self._history_pending:
            self._history_pending.pop(0)
        elif ((was_at_bottom and len(self._display_messages) >= self.MAX_VISIBLE)
              or len(self._display_messages) >= self.MAX_VISIBLE + self.MAX_READING_BUFFER):
            self._display_messages.pop(0)
            self._render_message_items(self._display_messages, preserve_scroll=not was_at_bottom)

        self._display_messages.append(message)
        if self._content_items:
            last = self._content_items[-1]
            if isinstance(last, MessageGroupWidget) and last.can_append(message):
                last.append_message(message)
            else:
                previous_day = _message_date(self._display_messages[-2]) if len(self._display_messages) > 1 else None
                current_day = _message_date(message)
                if current_day is not None and current_day != previous_day:
                    separator = DateSeparatorWidget(
                        current_day, self.bubble_container, self._content_family
                    )
                    self.bubble_layout.insertWidget(
                        self.bubble_layout.count() - 1, separator, 0, Qt.AlignTop
                    )
                    self._content_items.append(separator)
                group = MessageGroupWidget(
                    [message], self._peer_avatar_url, self.bubble_container,
                    self._my_avatar_url,
                )
                group.set_font_families(self._content_family, self._meta_family)
                self.bubble_layout.insertWidget(
                    self.bubble_layout.count() - 1, group, 0, Qt.AlignTop
                )
                self._content_items.append(group)
            self._update_bubble_widths()
        else:
            self._render_message_items(self._display_messages)

        if was_at_bottom:
            self._schedule_scroll(60, force=True)
        else:
            self._new_message_count += 1
            self._update_new_message_notice()
        QTimer.singleShot(0, self._update_avatar_positions)
        return True

    def _bubble_count(self):
        """兼容旧调用方：现在返回消息数，而不是组控件数。"""
        return len(self._display_messages)

    def _trim_bubbles(self):
        if len(self._display_messages) <= self.MAX_VISIBLE:
            return
        self._display_messages = self._display_messages[-self.MAX_VISIBLE:]
        self._render_message_items(self._display_messages, preserve_scroll=False)

    def _is_near_bottom(self):
        scrollbar = self.scroll.verticalScrollBar()
        return scrollbar.value() >= scrollbar.maximum() - 60

    def _update_new_message_notice(self):
        count = "99+" if self._new_message_count > 99 else str(self._new_message_count)
        self._new_message_button.setText(f"↓  {count}条新消息")
        self._position_new_message_button()
        self._new_message_button.show()
        self._new_message_button.raise_()

    def _reset_new_message_notice(self):
        self._new_message_count = 0
        if hasattr(self, "_new_message_button"):
            self._new_message_button.hide()

    def _jump_to_latest(self):
        self._trim_bubbles()
        self._reset_new_message_notice()
        self._schedule_scroll(0, force=True)

    def _on_scroll_value_changed(self, _value):
        self._update_avatar_positions()
        if self._new_message_count and self._is_near_bottom():
            self._trim_bubbles()
            self._reset_new_message_notice()
            self._schedule_scroll(0, force=True)

    def _update_bubble_widths(self):
        viewport_width = self.scroll.viewport().width()
        max_width = min(MAX_BUBBLE_WIDTH, max(140, int(viewport_width * 0.65)))
        for item in self._content_items:
            if isinstance(item, MessageGroupWidget):
                item.set_max_width(max_width, refresh=False)
        # 宽度变化后立即同步组高度，首帧不再等待延迟 timer 才摆正气泡。
        self._refresh_group_heights()

    def _refresh_group_heights(self):
        for item in self._content_items:
            if isinstance(item, MessageGroupWidget):
                item.refresh_layout()
        self.bubble_layout.invalidate()
        self.bubble_layout.activate()
        self.bubble_container.updateGeometry()
        self._update_avatar_positions()

    def _update_avatar_positions(self):
        viewport = self.scroll.viewport()
        for item in self._content_items:
            if isinstance(item, MessageGroupWidget):
                item.update_avatar_position(viewport, viewport.height())

    def _defer(self, callback):
        """使用归属于视图的定时器，避免销毁后执行悬空的延迟回调。"""
        timer = QTimer(self)
        timer.setSingleShot(True)

        def invoke():
            timer.deleteLater()
            callback()

        timer.timeout.connect(invoke)
        timer.start(0)

    def _position_new_message_button(self):
        viewport = self.scroll.viewport()
        self._new_message_button.move(
            max(8, (viewport.width() - self._new_message_button.width()) // 2),
            max(8, viewport.height() - self._new_message_button.height() - 16),
        )

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            self._position_new_message_button()
            self._update_bubble_widths()
            self._defer(self._update_avatar_positions)
        elif watched is self.bubble_container and event.type() in (
            QEvent.Resize, QEvent.LayoutRequest,
        ):
            self._defer(self._update_avatar_positions)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_bubble_widths()
        self._defer(self._update_avatar_positions)

    def _schedule_scroll(self, delay: int = 60, force: bool = False):
        """合并短时间内的滚动请求，消息洪峰时只重排一次。"""
        self._scroll_force = self._scroll_force or force
        if not self._scroll_timer.isActive():
            self._scroll_timer.start(delay)

    def _smart_scroll(self):
        scrollbar = self.scroll.verticalScrollBar()
        if self._scroll_force or scrollbar.value() >= scrollbar.maximum() - 60:
            scrollbar.setValue(scrollbar.maximum())
            self._reset_new_message_notice()
        self._scroll_force = False
        self._update_avatar_positions()
