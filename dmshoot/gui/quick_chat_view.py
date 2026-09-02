"""Qt Quick 虚拟聊天区。

消息数据由 QAbstractListModel 持有，QML ListView 只创建视口附近的消息组。
旧版 QWidget ChatView 作为图形后端不可用时的自动降级路径。
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFont, QFontMetrics, QTextOption
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QTextBrowser,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from dmshoot.storage.models import ChatMessage
from dmshoot.gui.widgets.chat_view import (
    BUBBLE_RADIUS,
    META_FONT_SIZE,
    SEAM_RADIUS,
    _avatar_cache_path,
    _group_key,
    _group_messages,
    _message_date,
    _message_is_self,
    ChatView as LegacyChatView,
)


PAGE_SIZE = 100
MAX_BUBBLE_WIDTH = 480
_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def _message_key(message: ChatMessage) -> str:
    """生成可用于历史分页锚定的稳定消息键。"""
    if message.message_key:
        return f"key:{message.message_key}"
    if message.id:
        return f"id:{message.id}"
    return "fallback:{:.6f}:{}:{}:{}".format(
        message.timestamp or 0,
        message.sender_id or message.sender_name,
        int(_message_is_self(message)),
        message.content,
    )


def _format_time(message: ChatMessage) -> str:
    timestamp = message.timestamp or 0
    if timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(timestamp).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def _rich_content(text: str) -> str:
    """转义正文并把 URL 转成可点击链接，避免消息内容注入 HTML。"""
    escaped = html.escape(text or "", quote=False)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,!?;:)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        href = html.escape(raw, quote=True)
        label = html.escape(raw, quote=False)
        return f'<a href="{href}"><font color="#A9C8FF">{label}</font></a>{trailing}'

    return _URL_RE.sub(replace, escaped).replace("\n", "<br/>")


class ChatMessageModel(QAbstractListModel):
    """按日期分隔和发送者分组的轻量聊天模型。"""

    KindRole = Qt.UserRole + 1
    MessagesRole = Qt.UserRole + 2
    MessagesJsonRole = Qt.UserRole + 9
    DateTextRole = Qt.UserRole + 3
    FirstKeyRole = Qt.UserRole + 4
    IsSelfRole = Qt.UserRole + 5
    SenderNameRole = Qt.UserRole + 6
    AvatarTextRole = Qt.UserRole + 7
    AvatarSourceRole = Qt.UserRole + 8

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._messages: list[ChatMessage] = []
        self._items: list[dict] = []
        self._peer_avatar_url = ""
        self._content_family = "Microsoft YaHei"
        self._meta_family = "Segoe UI"

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == self.KindRole:
            return item["kind"]
        if role == self.MessagesRole:
            return item.get("messages", [])
        if role == self.MessagesJsonRole:
            return json.dumps(item.get("messages", []), ensure_ascii=False, separators=(",", ":"))
        if role == self.DateTextRole:
            return item.get("dateText", "")
        if role == self.FirstKeyRole:
            return item.get("firstKey", "")
        if role == self.IsSelfRole:
            return item.get("isSelf", False)
        if role == self.SenderNameRole:
            return item.get("senderName", "")
        if role == self.AvatarTextRole:
            return item.get("avatarText", "")
        if role == self.AvatarSourceRole:
            return item.get("avatarSource", "")
        return None

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.KindRole: b"kind",
            self.MessagesRole: b"messages",
            self.MessagesJsonRole: b"messagesJson",
            self.DateTextRole: b"dateText",
            self.FirstKeyRole: b"firstKey",
            self.IsSelfRole: b"isSelf",
            self.SenderNameRole: b"senderName",
            self.AvatarTextRole: b"avatarText",
            self.AvatarSourceRole: b"avatarSource",
        }

    @property
    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    @property
    def oldest_message(self) -> ChatMessage | None:
        return self._messages[0] if self._messages else None

    def set_font_families(self, content_family: str, meta_family: str) -> None:
        self._content_family = content_family or "Microsoft YaHei"
        self._meta_family = meta_family or "Segoe UI"
        if self._messages:
            self._reset_items()

    def set_messages(
        self,
        messages: list[ChatMessage],
        peer_avatar_url: str = "",
    ) -> None:
        self._messages = list(messages)
        self._peer_avatar_url = peer_avatar_url or ""
        self._reset_items()

    def prepend_messages(self, messages: list[ChatMessage]) -> None:
        if not messages:
            return
        self._messages = list(messages) + self._messages
        self._reset_items()

    def append_message(self, message: ChatMessage) -> None:
        self._messages.append(message)
        if not self._items:
            self._reset_items()
            return

        last = self._items[-1]
        if last["kind"] == "group" and last["groupKey"] == _group_key(message):
            group_size = len(last["messages"]) + 1
            group_messages = self._messages[-group_size:]
            self._items[-1] = self._group_dict(group_messages)
            index = self.index(len(self._items) - 1, 0)
            self.dataChanged.emit(index, index, [
                self.MessagesRole,
                self.MessagesJsonRole,
                self.FirstKeyRole,
                self.IsSelfRole,
                self.SenderNameRole,
                self.AvatarTextRole,
                self.AvatarSourceRole,
            ])
            return

        day = _message_date(message)
        previous_day = self._item_last_day()
        new_items = []
        if previous_day is not None and day is not None and day != previous_day:
            new_items.append({
                "kind": "date",
                "dateText": f"{day.year}年{day.month}月{day.day}日",
                "messages": [],
                "firstKey": "",
            })
        new_items.append(self._group_dict([message]))
        first = len(self._items)
        last_index = first + len(new_items) - 1
        self.beginInsertRows(QModelIndex(), first, last_index)
        self._items.extend(new_items)
        self.endInsertRows()

    @Slot(str, result=int)
    def groupIndexForMessage(self, message_key: str) -> int:
        for index, item in enumerate(self._items):
            if item["kind"] != "group":
                continue
            if any(row["messageKey"] == message_key for row in item["messages"]):
                return index
        return -1

    def _reset_items(self) -> None:
        self.beginResetModel()
        self._items = self._build_items(self._messages)
        self.endResetModel()

    def _build_items(self, messages: list[ChatMessage]) -> list[dict]:
        items: list[dict] = []
        previous_day = None
        for group in _group_messages(messages):
            day = _message_date(group[0])
            if previous_day is not None and day is not None and day != previous_day:
                items.append({
                    "kind": "date",
                    "dateText": f"{day.year}年{day.month}月{day.day}日",
                    "messages": [],
                    "firstKey": "",
                })
            items.append(self._group_dict(group))
            previous_day = day
        return items

    def _group_dict(self, messages: list[ChatMessage]) -> dict:
        first = messages[0]
        is_self = _message_is_self(first)
        rows = [self._message_dict(message, index, len(messages)) for index, message in enumerate(messages)]
        avatar_path = "" if is_self else _avatar_cache_path(self._peer_avatar_url)
        avatar_source = QUrl.fromLocalFile(str(avatar_path)).toString() if avatar_path else ""
        return {
            "kind": "group",
            "groupKey": _group_key(first),
            "messages": rows,
            "firstKey": rows[0]["messageKey"],
            "isSelf": is_self,
            "senderName": first.sender_name or ("AI" if first.is_auto else ""),
            "avatarText": ("AI" if first.is_auto else "我") if is_self else (first.sender_name or "?"),
            "avatarSource": avatar_source,
        }

    def _message_dict(
        self,
        message: ChatMessage,
        index: int,
        total: int | None = None,
    ) -> dict:
        total = total or 1
        is_self = _message_is_self(message)
        if total == 1:
            position = "single"
        elif index == 0:
            position = "first"
        elif index == total - 1:
            position = "last"
        else:
            position = "middle"

        if position == "first":
            radii = (
                (BUBBLE_RADIUS, BUBBLE_RADIUS, SEAM_RADIUS, BUBBLE_RADIUS)
                if is_self else
                (BUBBLE_RADIUS, BUBBLE_RADIUS, BUBBLE_RADIUS, SEAM_RADIUS)
            )
        elif position in {"middle", "last"}:
            radii = (
                (BUBBLE_RADIUS, SEAM_RADIUS, SEAM_RADIUS, BUBBLE_RADIUS)
                if is_self else
                (SEAM_RADIUS, BUBBLE_RADIUS, BUBBLE_RADIUS, SEAM_RADIUS)
            )
        else:
            radii = (BUBBLE_RADIUS,) * 4

        tail_side = ""
        if position in {"single", "last"}:
            tail_side = "right" if is_self else "left"

        content = message.content or ""
        content_font = QFont(self._content_family)
        content_font.setPixelSize(16)
        meta_font = QFont(self._meta_family)
        meta_font.setPixelSize(META_FONT_SIZE)
        metrics = QFontMetrics(content_font)
        natural_width = max(
            (metrics.horizontalAdvance(line) for line in content.split("\n")),
            default=0,
        )
        time_text = _format_time(message)
        meta_width = QFontMetrics(meta_font).horizontalAdvance(time_text) if time_text else 0
        check_width = 18 if is_self and time_text else 0
        return {
            "messageKey": _message_key(message),
            "content": content,
            "richContent": _rich_content(content),
            "time": time_text,
            "isSelf": is_self,
            "position": position,
            "tailSide": tail_side,
            "radii": list(radii),
            "naturalWidth": natural_width,
            "metaWidth": meta_width + (2 + check_width if check_width else 0),
            "showName": not is_self and index == 0 and bool(message.sender_name),
        }

    def _item_last_day(self):
        for item in reversed(self._items):
            if item["kind"] == "group" and item["messages"]:
                key = item["messages"][-1]["messageKey"]
                for message in reversed(self._messages):
                    if _message_key(message) == key:
                        return _message_date(message)
        return None


class ChatView(QWidget):
    """Qt Quick 优先的聊天视图，失败时透明降级到旧 QWidget 实现。"""

    history_requested = Signal(str)

    def __init__(self, font_manager=None, parent=None):
        super().__init__(parent)
        self._font_manager = font_manager
        self._font_mode = getattr(font_manager, "current_mode", "system")
        if font_manager is not None:
            self._content_family, self._meta_family = font_manager.chat_families(self._font_mode)
        else:
            self._content_family, self._meta_family = "Microsoft YaHei", "Segoe UI"
        self._conversation_id = ""
        self._peer_avatar_url = ""
        self._messages: list[ChatMessage] = []
        self._at_bottom = True
        self._history_available = True
        self._quick: QQuickWidget | None = None
        self._root = None
        self._legacy: LegacyChatView | None = None
        self._renderer_name = "widgets"
        self._renderer_backend = "Software"

        self._build_shell()
        self._select_renderer()

    @property
    def renderer_name(self) -> str:
        return self._renderer_name

    @property
    def renderer_backend(self) -> str:
        return self._renderer_backend

    def _build_shell(self) -> None:
        layout = QVBoxLayout(self)
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
        title_layout.addWidget(self.title_label, 1)
        layout.addWidget(title_row)

        self._content_stack = QStackedLayout()
        self._content_host = QWidget()
        self._content_host.setLayout(self._content_stack)
        layout.addWidget(self._content_host, 1)

        self._placeholder = QLabel()
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet(
            "color: rgba(255,255,255,0.35); font-size: 14px; padding: 40px;"
        )
        self._content_stack.addWidget(self._placeholder)

    def _select_renderer(self) -> None:
        requested = os.environ.get("DMSHOOT_CHAT_RENDERER", "auto").lower().strip()
        if requested not in {"auto", "quick", "widgets"}:
            requested = "auto"
        if requested == "widgets" or os.environ.get("DMSHOOT_SOFTWARE_RENDER") == "1":
            self._use_legacy("环境变量要求使用 QWidget 渲染")
            return
        try:
            self._create_quick()
        except Exception as exc:
            self._use_legacy(f"Qt Quick 初始化失败: {exc}")
            if requested == "quick":
                # quick 是诊断强制项，但仍不阻止程序进入聊天页。
                self._renderer_backend = "Software"

    def _create_quick(self) -> None:
        from dmshoot.utils.console_log import get_logger

        logger = get_logger(__name__)
        self._model = ChatMessageModel(self)
        self._model.set_font_families(self._content_family, self._meta_family)
        quick = QQuickWidget()
        quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        quick.setClearColor(Qt.transparent)
        quick.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        quick.rootContext().setContextProperty("chatModel", self._model)
        quick.statusChanged.connect(self._on_quick_status)
        qml_path = Path(__file__).resolve().parent / "qml" / "ChatView.qml"
        if not qml_path.exists():
            raise FileNotFoundError(qml_path)
        quick.setSource(QUrl.fromLocalFile(str(qml_path)))
        if quick.status() == QQuickWidget.Status.Error:
            errors = "; ".join(error.toString() for error in quick.errors())
            raise RuntimeError(errors or "QML 加载失败")
        self._quick = quick
        self._content_stack.addWidget(quick)
        self._content_stack.setCurrentWidget(quick)
        self._renderer_name = "quick"
        self._wire_quick_root()
        self._update_renderer_backend()
        logger.info(f"聊天渲染器: Qt Quick ({self._renderer_backend})")

    def _on_quick_status(self, status: QQuickWidget.Status) -> None:
        if status != QQuickWidget.Status.Error or self._renderer_name == "widgets":
            if status == QQuickWidget.Status.Ready:
                self._wire_quick_root()
                self._update_renderer_backend()
            return
        errors = "; ".join(error.toString() for error in self._quick.errors()) if self._quick else ""
        self._use_legacy(f"QML 加载失败: {errors}")

    def _wire_quick_root(self) -> None:
        if self._quick is None:
            return
        root = self._quick.rootObject()
        if root is None or root is self._root:
            return
        self._root = root
        root.historyRequested.connect(lambda: self.history_requested.emit(self._conversation_id))
        root.bottomStateChanged.connect(self._on_bottom_state_changed)
        root.linkActivated.connect(self._open_url)
        root.setFonts(self._content_family, self._meta_family)
        if self._messages:
            self._model.set_messages(self._messages, self._peer_avatar_url)
            root.loadMessages()

    def _update_renderer_backend(self) -> None:
        if self._quick is None or self._quick.quickWindow() is None:
            return
        try:
            api = self._quick.quickWindow().rendererInterface().graphicsApi()
            self._renderer_backend = str(api).split(".")[-1]
        except Exception:
            self._renderer_backend = "Unknown"

    def _use_legacy(self, reason: str) -> None:
        from dmshoot.utils.console_log import get_logger

        logger = get_logger(__name__)
        logger.warning(reason)
        if self._legacy is None:
            self._legacy = LegacyChatView(font_manager=self._font_manager)
            legacy_title = self._legacy.layout().itemAt(0).widget()
            if legacy_title is not None:
                legacy_title.hide()
            self._content_stack.addWidget(self._legacy)
        if self._quick is not None:
            self._content_stack.removeWidget(self._quick)
            self._quick.deleteLater()
            self._quick = None
        self._root = None
        self._renderer_name = "widgets"
        self._renderer_backend = "Software"
        self._content_stack.setCurrentWidget(self._legacy)
        self._legacy.set_conversation(self._conversation_id, self._peer_avatar_url)
        self._legacy.set_font_mode(self._font_mode)
        if self._messages:
            self._legacy.load_messages(
                self.title_label.text(), self._messages, self._peer_avatar_url
            )

    def _set_quick_visible(self) -> bool:
        if self._renderer_name != "quick" or self._quick is None:
            return False
        self._content_stack.setCurrentWidget(self._quick)
        return self._root is not None

    def _on_bottom_state_changed(self, at_bottom: bool) -> None:
        self._at_bottom = bool(at_bottom)

    @Slot(str)
    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def set_conversation(self, conversation_id: str, peer_avatar_url: str = ""):
        self._conversation_id = conversation_id or ""
        self._peer_avatar_url = peer_avatar_url or ""
        if self._legacy is not None:
            self._legacy.set_conversation(self._conversation_id, self._peer_avatar_url)

    def set_history_available(self, available: bool) -> None:
        self._history_available = bool(available)
        if self._root is not None:
            self._root.setHistoryAvailable(self._history_available)

    def set_font_mode(self, mode: str):
        self._font_mode = mode
        if self._font_manager is not None:
            self._content_family, self._meta_family = self._font_manager.chat_families(mode)
        if self._renderer_name == "quick":
            self._model.set_font_families(self._content_family, self._meta_family)
            if self._root is not None:
                self._root.setFonts(self._content_family, self._meta_family)
        elif self._legacy is not None:
            self._legacy.set_font_mode(mode)

    def show_placeholder(self, text: str):
        self.title_icon.hide()
        self.title_label.setText("")
        if self._legacy is not None:
            self._content_stack.setCurrentWidget(self._legacy)
            self._legacy.show_placeholder(text)
            return
        self._placeholder.setText(text)
        self._content_stack.setCurrentWidget(self._placeholder)

    def show_markdown(self, md_path: str, title: str = ""):
        self.title_label.setText(title)
        icon_path = Path(__file__).resolve().parents[2] / "resources" / "大咸鱼.jpeg"
        if icon_path.is_file():
            from PySide6.QtGui import QPixmap

            self.title_icon.setPixmap(QPixmap(str(icon_path)))
            self.title_icon.show()
        else:
            self.title_icon.hide()
        if self._legacy is not None:
            self._content_stack.setCurrentWidget(self._legacy)
            self._legacy.show_markdown(md_path, title)
            return
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QTextBrowser.NoFrame)
        browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,0.12); border-radius: 4px; min-height: 40px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        try:
            import markdown

            content = Path(md_path).read_text(encoding="utf-8")
            body = markdown.markdown(content, extensions=["tables", "fenced_code", "codehilite", "nl2br"])
            safe_family = self._content_family.replace('"', "")
            css = LegacyChatView._MD_CSS.replace("CHAT_FONT_FAMILY", safe_family)
            browser.setHtml(f"<html><head><style>{css}</style></head><body>{body}</body></html>")
        except Exception as exc:
            browser.setPlainText(f"无法加载日志：{exc}")
        self._markdown_browser = browser
        self._content_stack.addWidget(browser)
        self._content_stack.setCurrentWidget(browser)

    def clear_markdown(self):
        self.title_icon.hide()
        self.title_label.setText("选择会话")
        self._messages = []
        if self._legacy is not None:
            self._legacy.clear_markdown()
            return
        self._model.set_messages([])
        if self._root is not None:
            self._root.clearMessages()
        self._content_stack.setCurrentWidget(self._quick)

    def load_messages(self, title: str, messages: list[ChatMessage], peer_avatar_url: str = ""):
        self.title_icon.hide()
        self.title_label.setText(title)
        self._messages = list(messages)
        if peer_avatar_url:
            self._peer_avatar_url = peer_avatar_url
        if self._legacy is not None:
            self._legacy.load_messages(title, self._messages, self._peer_avatar_url)
            return
        self._model.set_messages(self._messages, self._peer_avatar_url)
        self._set_quick_visible()
        if self._root is not None:
            self._root.setHistoryAvailable(self._history_available)
            self._root.loadMessages()

    def prepend_messages(self, messages: list[ChatMessage]):
        if not messages:
            return
        if self._legacy is not None:
            self._messages = list(messages) + self._messages
            self._legacy.load_messages(self.title_label.text(), self._messages, self._peer_avatar_url)
            return
        anchor = _message_key(self._messages[0]) if self._messages else ""
        if self._root is not None and anchor:
            self._root.preparePrepend(anchor)
        self._messages = list(messages) + self._messages
        self._model.prepend_messages(messages)
        if self._root is not None:
            self._root.restorePrepend()

    def history_load_finished(self):
        if self._root is not None:
            self._root.finishHistoryLoad()

    def append_message(self, message: ChatMessage):
        was_at_bottom = self._at_bottom
        self._messages.append(message)
        if self._legacy is not None:
            self._legacy.append_message(message)
            return
        self._model.append_message(message)
        if self._root is not None:
            self._root.notifyAppended(was_at_bottom)

    def _is_near_bottom(self) -> bool:
        if self._legacy is not None:
            return self._legacy._is_near_bottom()
        return self._at_bottom

    def _jump_to_latest(self):
        if self._legacy is not None:
            self._legacy._jump_to_latest()
            return
        if self._root is not None:
            self._root.jumpToLatest()
