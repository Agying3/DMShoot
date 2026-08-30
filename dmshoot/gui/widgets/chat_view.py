"""对话气泡视图 — 支持增量复用避免全量重建"""

from datetime import datetime
from pathlib import Path

import markdown

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QTextBrowser, QPushButton,
)
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QTextOption
from dmshoot.storage.models import ChatMessage


class BubbleWidget(QWidget):
    """单条消息气泡 — 支持 rebind() 复用"""

    def __init__(self, message: ChatMessage = None, parent=None):
        super().__init__(parent)
        self._name_label = None
        self._bubble_label = None
        self._time_label = None
        self._built = False
        self._is_self = None
        if message:
            self.rebind(message)

    def rebind(self, message: ChatMessage):
        """复用时只更新文字+调色板，不触发 QSS 重解析"""
        if not self._built:
            self._init_ui()
        is_self = message.is_self or message.is_auto

        name_text = message.sender_name or ("AI" if message.is_auto else "")
        show_name = bool(name_text and not is_self)
        self._name_label.setText(name_text if show_name else "")
        self._name_label.setVisible(show_name)

        self._bubble_label.setText(message.content)

        # 复用同方向气泡时无需重新解析样式和重建横向布局。
        if is_self != self._is_self:
            if is_self:
                self._bubble_label.setStyleSheet(
                    "QLabel#bubble {"
                    "  background: rgba(255,150,50,0.18);"
                    "  border: 1px solid rgba(255,150,50,0.15);"
                    "  border-radius: 18px;"
                    "  padding: 12px 16px;"
                    "  font-size: 13px;"
                    "  color: #FFE0A0;"
                    "}"
                )
            else:
                self._bubble_label.setStyleSheet(
                    "QLabel#bubble {"
                    "  background: rgba(255,255,255,0.07);"
                    "  border: 1px solid rgba(255,255,255,0.10);"
                    "  border-radius: 18px;"
                    "  padding: 12px 16px;"
                    "  font-size: 13px;"
                    "  color: #E2E2ED;"
                    "}"
                )

            while self._row.count():
                self._row.takeAt(0)
            if is_self:
                self._row.addStretch(1)
                self._row.addWidget(self._bubble_label)
            else:
                self._row.addWidget(self._bubble_label)
                self._row.addStretch(1)
            self._is_self = is_self

        # 根据实际字体计算宽度（QSS 已生效）
        fm = self._bubble_label.fontMetrics()
        lines = message.content.split('\n')
        max_chars = max((len(line) for line in lines), default=0)
        char_w = fm.horizontalAdvance("中")
        box_w = 34 + max_chars * char_w + 8  # padding + 文字 + 余量
        target_w = int(min(max(box_w, 64), 600))
        self._bubble_label.setFixedWidth(target_w)

        ts = message.timestamp if message.timestamp is not None else 0.0
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts > 0 else ""
        self._time_label.setText(t)
        # 自写消息时间戳右对齐
        self._time_label.setAlignment(Qt.AlignRight if is_self else Qt.AlignLeft)

    def _init_ui(self):
        """首次创建 widget 树（只执行一次）"""
        self._built = True
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(2)

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            "color: #4ADE80; font-size: 11px; padding-left: 14px; font-weight: 600;"
        )
        self._name_label.hide()
        outer.addWidget(self._name_label)

        self._row = QHBoxLayout()
        self._row.setContentsMargins(12, 0, 12, 0)
        self._bubble_label = QLabel()
        self._bubble_label.setObjectName("bubble")
        self._bubble_label.setWordWrap(True)
        self._bubble_label.setMaximumWidth(600)
        self._bubble_label.setMinimumWidth(60)
        self._bubble_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._row.addWidget(self._bubble_label)  # 初始占位，rebind 时重新排列
        outer.addLayout(self._row)

        self._time_label = QLabel()
        self._time_label.setStyleSheet("color: rgba(255,255,255,0.50); font-size: 10px;")
        self._time_label.setContentsMargins(14, 0, 14, 0)
        outer.addWidget(self._time_label)

        self.setLayout(outer)

class ChatView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("选择会话")
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setStyleSheet("padding: 12px 16px; font-size: 15px;")
        layout.addWidget(self.title_label)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("chatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.bubble_container = QWidget()
        self.bubble_layout = QVBoxLayout()
        self.bubble_layout.setContentsMargins(8, 8, 8, 8)
        self.bubble_layout.setSpacing(2)
        self.bubble_layout.addStretch()
        self.bubble_container.setLayout(self.bubble_layout)

        self.scroll.setWidget(self.bubble_container)
        layout.addWidget(self.scroll, stretch=1)
        self.setLayout(layout)

        self._new_message_count = 0
        self._new_message_button = QPushButton(self.scroll.viewport())
        self._new_message_button.setObjectName("newMessagesButton")
        self._new_message_button.setFixedSize(132, 32)
        self._new_message_button.setFocusPolicy(Qt.NoFocus)
        self._new_message_button.setCursor(Qt.PointingHandCursor)
        self._new_message_button.clicked.connect(self._jump_to_latest)
        self._new_message_button.hide()
        self.scroll.viewport().installEventFilter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        # 消息批量到达时只保留一个滚动请求。
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._smart_scroll)
        self._scroll_force = False
        self._history_pending: list[ChatMessage] = []
        self._history_timer = QTimer(self)
        self._history_timer.setInterval(30)
        self._history_timer.timeout.connect(self._load_history_chunk)

    def show_placeholder(self, text: str):
        """显示空状态引导文字"""
        self.title_label.setText("")
        self._clear_content()
        self._placeholder = QLabel(text)
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet(
            "color: rgba(255,255,255,0.35); font-size: 14px; padding: 40px;"
        )
        self.bubble_layout.insertWidget(
            self.bubble_layout.count() - 1, self._placeholder
        )

    def _clear_content(self):
        """清除所有气泡 / Markdown 浏览器 / 占位文字"""
        self._reset_new_message_notice()
        self._history_timer.stop()
        self._history_pending.clear()
        while self.bubble_layout.count():
            item = self.bubble_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._placeholder = None
        self._md_browser = None
        self.bubble_layout.addStretch()

    _MD_CSS = """
        body {
            font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
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
        """渲染 Markdown 格式的逆向日志全文，替代空白聊天区域"""
        self.title_label.setText(title)
        self._clear_content()
        # 移除末尾 stretch，让浏览器独占空间。
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
            full_html = (
                f"<html><head><style>{self._MD_CSS}</style></head>"
                f"<body>{html_body}</body></html>"
            )
            self._md_browser.setHtml(full_html)
        except Exception as e:
            self._md_browser.setPlainText(f"无法加载日志：{e}")
        self.bubble_layout.addWidget(self._md_browser, stretch=1)

    def clear_markdown(self):
        """清除 Markdown 视图，恢复通讯录/气泡模式"""
        if hasattr(self, '_md_browser') and self._md_browser:
            self._md_browser.deleteLater()
            self._md_browser = None
        self.title_label.setText("选择会话")
        self._clear_content()

    MAX_VISIBLE = 50  # 最多显示条数，防止长会话内存膨胀
    MAX_READING_BUFFER = 20
    INITIAL_VISIBLE = 12
    HISTORY_CHUNK = 4

    def load_messages(self, title: str, messages: list[ChatMessage]):
        """增量加载 — 复用已有气泡，只更新内容"""
        self._reset_new_message_notice()
        self.title_label.setText(title)
        # 清除 Markdown 视图和占位文字
        if ((hasattr(self, '_md_browser') and self._md_browser) or
                (hasattr(self, '_placeholder') and self._placeholder)):
            self._clear_content()
        self._history_timer.stop()
        self._history_pending.clear()
        messages = messages[-self.MAX_VISIBLE:]
        initial = messages[-self.INITIAL_VISIBLE:]
        self._history_pending = list(messages[:-self.INITIAL_VISIBLE])
        # 收集已有气泡
        existing = []
        for i in range(self.bubble_layout.count() - 1):  # skip stretch
            w = self.bubble_layout.itemAt(i).widget()
            if isinstance(w, BubbleWidget):
                existing.append(w)

        # 更新/新增
        for i, msg in enumerate(initial):
            if i < len(existing):
                existing[i].rebind(msg)
            else:
                self.bubble_layout.insertWidget(i, BubbleWidget(msg))

        # 删除多余的
        for w in existing[len(initial):]:
            self.bubble_layout.removeWidget(w)
            w.deleteLater()

        self._schedule_scroll(120, force=True)
        if self._history_pending:
            self._history_timer.start()

    def _load_history_chunk(self):
        if not self._history_pending:
            self._history_timer.stop()
            return
        sb = self.scroll.verticalScrollBar()
        was_at_bottom = sb.value() >= sb.maximum() - 60
        chunk = self._history_pending[-self.HISTORY_CHUNK:]
        del self._history_pending[-len(chunk):]
        for msg in reversed(chunk):
            self.bubble_layout.insertWidget(0, BubbleWidget(msg))
        self._schedule_scroll(30, force=was_at_bottom)

    def append_message(self, message: ChatMessage):
        sb = self.scroll.verticalScrollBar()
        was_at_bottom = self._is_near_bottom()
        # 保持上限：超出时删除最旧的气泡
        bubble_count = self._bubble_count()
        if self._history_pending:
            self._history_pending.pop(0)
        elif ((was_at_bottom and bubble_count >= self.MAX_VISIBLE)
              or bubble_count >= self.MAX_VISIBLE + self.MAX_READING_BUFFER):
            self._remove_oldest_bubble()
        bubble = BubbleWidget(message)
        self.bubble_layout.insertWidget(
            self.bubble_layout.count() - 1, bubble
        )
        if was_at_bottom:
            self._schedule_scroll(60, force=True)
        else:
            self._new_message_count += 1
            self._update_new_message_notice()

    def _bubble_count(self):
        return sum(
            1 for i in range(self.bubble_layout.count() - 1)
            if isinstance(self.bubble_layout.itemAt(i).widget(), BubbleWidget)
        )

    def _remove_oldest_bubble(self):
        for i in range(self.bubble_layout.count() - 1):
            widget = self.bubble_layout.itemAt(i).widget()
            if isinstance(widget, BubbleWidget):
                self.bubble_layout.removeWidget(widget)
                widget.deleteLater()
                return True
        return False

    def _trim_bubbles(self):
        while self._bubble_count() > self.MAX_VISIBLE:
            if not self._remove_oldest_bubble():
                break

    def _is_near_bottom(self):
        sb = self.scroll.verticalScrollBar()
        return sb.value() >= sb.maximum() - 60

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
        if self._new_message_count and self._is_near_bottom():
            self._trim_bubbles()
            self._reset_new_message_notice()
            self._schedule_scroll(0, force=True)

    def _position_new_message_button(self):
        viewport = self.scroll.viewport()
        self._new_message_button.move(
            max(8, (viewport.width() - self._new_message_button.width()) // 2),
            max(8, viewport.height() - self._new_message_button.height() - 16),
        )

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            self._position_new_message_button()
        return super().eventFilter(watched, event)

    def _schedule_scroll(self, delay: int = 60, force: bool = False):
        """合并短时间内的滚动请求，消息洪峰时只重排一次。"""
        self._scroll_force = self._scroll_force or force
        if not self._scroll_timer.isActive():
            self._scroll_timer.start(delay)

    def _smart_scroll(self):
        sb = self.scroll.verticalScrollBar()
        if self._scroll_force or sb.value() >= sb.maximum() - 60:
            sb.setValue(sb.maximum())
            self._reset_new_message_notice()
        self._scroll_force = False
