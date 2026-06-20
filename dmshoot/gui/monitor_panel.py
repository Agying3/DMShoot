"""回复日志流 — 显示AI自动回复记录，纯监控"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame, QHBoxLayout
)
from PySide6.QtCore import Qt

from dmshoot.storage.models import ChatMessage


class ReplyLogEntry(QFrame):
    """一条回复日志"""

    def __init__(self, msg: ChatMessage, ai_reply: str = ""):
        super().__init__()
        self.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.02); border: 0.5px solid rgba(255,255,255,0.05); "
            "border-radius: 10px; margin: 2px 0; }"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)

        # 时间 + 平台 + 发送者
        from datetime import datetime
        time_str = datetime.fromtimestamp(msg.timestamp).strftime("%H:%M:%S")
        platform_id = msg.session_id.split(":")[0] if ":" in msg.session_id else ""
        platform_names = {"douyin": "DY", "bilibili": "BL"}  # xiaohongshu 已废弃
        platform_label_text = platform_names.get(platform_id, platform_id)
        platform_color = {"douyin": "#ff2d55", "bilibili": "#00a1d6"}.get(  # xiaohongshu 已废弃
            platform_id, "#aaa"
        )

        header = QHBoxLayout()
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet("font-size: 10px; color: rgba(255,255,255,0.35); background:transparent;")

        platform_tag = QLabel(f" {platform_label_text} ")
        platform_tag.setStyleSheet(
            f"font-size: 9px; font-weight: 600; color: {platform_color}; "
            f"background: rgba(255,255,255,0.05); border-radius: 4px; padding: 1px 4px;"
        )

        sender_lbl = QLabel(msg.sender_name)
        sender_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.85); background:transparent;"
        )

        header.addWidget(time_lbl)
        header.addWidget(platform_tag)
        header.addWidget(sender_lbl)
        header.addStretch()

        # 收到的消息
        incoming = QLabel(f"「{msg.content[:100]}」")
        incoming.setWordWrap(True)
        incoming.setStyleSheet(
            "font-size: 12px; color: rgba(255,255,255,0.55); background:transparent; "
            "padding: 2px 0;"
        )

        # AI回复
        if ai_reply:
            reply = QLabel(f"→ {ai_reply[:200]}")
            reply.setWordWrap(True)
            reply.setStyleSheet(
                "font-size: 12px; color: #FFD580; background:transparent; "
                "padding: 2px 0; font-weight: 500;"
            )
            layout.addLayout(header)
            layout.addWidget(incoming)
            layout.addWidget(reply)
        else:
            layout.addLayout(header)
            layout.addWidget(incoming)

        self.setLayout(layout)


class MonitorPanel(QWidget):
    """AI回复监控面板 — 纯只读日志流"""

    def __init__(self):
        super().__init__()
        self.setObjectName("MonitorPanel")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title = QLabel("回复日志")
        title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #FFD580; "
            "background:transparent; padding: 8px 4px 4px 4px;"
        )
        layout.addWidget(title)

        # 滚动日志区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.log_container = QWidget()
        self.log_layout = QVBoxLayout()
        self.log_layout.setAlignment(Qt.AlignTop)
        self.log_layout.setSpacing(4)
        self.log_layout.addStretch()
        self.log_container.setLayout(self.log_layout)
        self.scroll.setWidget(self.log_container)
        layout.addWidget(self.scroll, stretch=1)

        # 空状态
        self._empty = QLabel("等待私信...")
        self._empty.setStyleSheet(
            "font-size: 20px; color: rgba(255,255,255,0.10); background:transparent;"
        )
        self._empty.setAlignment(Qt.AlignCenter)
        self.log_layout.insertWidget(0, self._empty)

        self.setLayout(layout)
        self._entry_count = 0  # O(1) 条目计数

    MAX_LOG_ENTRIES = 200

    def add_reply_log(self, msg: "ChatMessage | str", ai_reply: str = ""):
        """添加回复记录 — 接受 ChatMessage 或纯文本"""
        if self._empty and self._empty.isVisible():
            self._empty.hide()
            self._empty.deleteLater()
            self._empty = None

        # 超限删最旧（O(1)：直接找第一个非 stretch widget）
        while self._entry_count >= self.MAX_LOG_ENTRIES:
            for i in range(self.log_layout.count()):
                w = self.log_layout.itemAt(i).widget()
                if w:
                    w.deleteLater()
                    self._entry_count -= 1
                    break

        if self.log_layout.count() > 0:
            last = self.log_layout.itemAt(self.log_layout.count() - 1)
            if last.spacerItem():
                self.log_layout.removeItem(last)

        if isinstance(msg, str):
            from datetime import datetime
            from PySide6.QtWidgets import QFrame
            entry = QFrame()
            entry.setStyleSheet(
                "QFrame { background: rgba(255,255,255,0.02);"
                "border: 0.5px solid rgba(255,255,255,0.05);"
                "border-radius: 10px; margin: 2px 0; }")
            ly = QVBoxLayout(entry); ly.setContentsMargins(10, 6, 10, 6); ly.setSpacing(3)
            hdr = QHBoxLayout()
            t = QLabel(datetime.now().strftime("%H:%M:%S"))
            t.setStyleSheet("font-size:10px;color:rgba(255,255,255,0.35);")
            hdr.addWidget(t); hdr.addStretch()
            ly.addLayout(hdr)
            qt = QLabel(msg[:200])
            qt.setStyleSheet("color:rgba(255,255,255,0.5);font-size:11px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);")
            qt.setWordWrap(True); ly.addWidget(qt)
            ar = QLabel(ai_reply[:200])
            ar.setStyleSheet("color:#a6e3a1;font-size:11px;"); ar.setWordWrap(True)
            ly.addWidget(ar)
        else:
            entry = ReplyLogEntry(msg, ai_reply)
        self.log_layout.addWidget(entry)
        self.log_layout.addStretch()
        self._entry_count += 1

        # 滚动到底（用 rangeChanged 替代 QTimer.singleShot）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))

    def clear(self):
        while self.log_layout.count():
            item = self.log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._entry_count = 0
