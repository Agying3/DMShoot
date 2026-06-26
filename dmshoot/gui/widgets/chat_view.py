"""对话气泡视图 — 支持增量复用避免全量重建"""

from datetime import datetime
from pathlib import Path

import markdown

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QTextBrowser,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from dmshoot.storage.models import ChatMessage


class BubbleWidget(QWidget):
    """单条消息气泡 — 支持 rebind() 复用"""

    def __init__(self, message: ChatMessage = None):
        super().__init__()
        self._name_label = None
        self._bubble_label = None
        self._time_label = None
        self._built = False
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
        if show_name:
            self._name_label.setStyleSheet(
                "color: #4ADE80; font-size: 11px; padding-left: 14px; font-weight: 600;"
            )

        self._bubble_label.setText(message.content)

        # 先应用 QSS（设置字体），再计算宽度（否则 fontMetrics 可能是旧字体）
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

        # 根据实际字体计算宽度（QSS 已生效）
        fm = self._bubble_label.fontMetrics()
        lines = message.content.split('\n')
        max_chars = max((len(line) for line in lines), default=0)
        char_w = fm.horizontalAdvance("中")
        box_w = 34 + max_chars * char_w + 8  # padding + 文字 + 余量
        target_w = int(min(max(box_w, 64), 600))
        self._bubble_label.setFixedWidth(target_w)

        # 气泡对齐：stretch 填充左右空白
        while self._row.count():
            self._row.takeAt(0)
        if is_self:
            self._row.addStretch(1)
            self._row.addWidget(self._bubble_label)
        else:
            self._row.addWidget(self._bubble_label)
            self._row.addStretch(1)

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
        self._name_label.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px; padding-left: 14px;")
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
        self.bubble_layout.addWidget(self._placeholder)
        self.bubble_layout.addStretch()

    def _clear_content(self):
        """清除所有气泡 / Markdown 浏览器 / 占位文字"""
        for i in range(self.bubble_layout.count() - 1, -1, -1):
            w = self.bubble_layout.itemAt(i).widget()
            if w and isinstance(w, (BubbleWidget, QTextBrowser)):
                w.deleteLater()
        if hasattr(self, '_placeholder') and self._placeholder:
            self._placeholder.deleteLater()
            self._placeholder = None
        if hasattr(self, '_md_browser') and self._md_browser:
            self._md_browser.deleteLater()
            self._md_browser = None

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
        # 移除 stretch 让浏览器独占空间
        self.bubble_layout.setStretchFactor(self.bubble_layout, 0)
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

    def load_messages(self, title: str, messages: list[ChatMessage]):
        """增量加载 — 复用已有气泡，只更新内容"""
        self.title_label.setText(title)
        # 清除 Markdown 视图和占位文字
        if hasattr(self, '_md_browser') and self._md_browser:
            self._md_browser.deleteLater()
            self._md_browser = None
        if hasattr(self, '_placeholder') and self._placeholder:
            self._placeholder.deleteLater()
            self._placeholder = None
        # 长会话截断：只保留最近 N 条
        truncated = len(messages) > self.MAX_VISIBLE
        if truncated:
            messages = messages[-self.MAX_VISIBLE:]
        # 收集已有气泡
        existing = []
        for i in range(self.bubble_layout.count() - 1):  # skip stretch
            w = self.bubble_layout.itemAt(i).widget()
            if isinstance(w, BubbleWidget):
                existing.append(w)

        # 更新/新增
        for i, msg in enumerate(messages):
            if i < len(existing):
                existing[i].rebind(msg)
            else:
                self.bubble_layout.insertWidget(i, BubbleWidget(msg))

        # 删除多余的
        for w in existing[len(messages):]:
            w.deleteLater()

        # 双保险滚到底：150ms 等布局，350ms 兜底（布局重新计算后）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))
        QTimer.singleShot(350, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def append_message(self, message: ChatMessage):
        # 保持上限：超出时删除最旧的气泡
        bubble_count = sum(1 for i in range(self.bubble_layout.count() - 1)
                           if isinstance(self.bubble_layout.itemAt(i).widget(), BubbleWidget))
        if bubble_count >= self.MAX_VISIBLE:
            for i in range(self.bubble_layout.count() - 1):
                w = self.bubble_layout.itemAt(i).widget()
                if isinstance(w, BubbleWidget):
                    w.deleteLater()
                    break
        # 分隔线
        if bubble_count > 0:
            sep = QLabel()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background: rgba(255,255,255,0.05); margin: 4px 12px;")
            self.bubble_layout.insertWidget(self.bubble_layout.count() - 1, sep)
        self.bubble_layout.insertWidget(self.bubble_layout.count() - 1, BubbleWidget(message))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(60, self._smart_scroll)

    def _smart_scroll(self):
        sb = self.scroll.verticalScrollBar()
        if sb.value() >= sb.maximum() - 60:
            sb.setValue(sb.maximum())
