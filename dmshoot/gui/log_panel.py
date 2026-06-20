"""日志面板 — 底部半透明"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel
from PySide6.QtCore import Qt


class LogPanel(QWidget):
    """底部日志面板"""

    def __init__(self):
        super().__init__()
        self.setObjectName("LogPanel")
        self.setMaximumHeight(130)
        self.setStyleSheet(
            "background: rgba(8,12,18,0.50); border: none; "
            "border-top: 0.5px solid rgba(255,255,255,0.04); border-radius: 10px;"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)

        header = QLabel("日志")
        header.setStyleSheet(
            "font-size: 10px; color: rgba(255,255,255,0.35); background:transparent; padding: 2px;"
        )
        layout.addWidget(header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(100)
        self.log_view.setStyleSheet(
            "QTextEdit { background: rgba(0,0,0,0.20); color: rgba(255,255,255,0.55); "
            "border: none; border-radius: 8px; font-size: 11px; padding: 6px; }"
        )
        layout.addWidget(self.log_view)
        self.setLayout(layout)

    def append(self, level: str, platform: str, message: str):
        color = {
            "INFO": "rgba(255,255,255,0.55)",
            "WARN": "#f0a000",
            "ERROR": "#ff4757",
            "SUCCESS": "#2ed573",
        }.get(level, "rgba(255,255,255,0.55)")

        self.log_view.append(
            f'<span style="color:{color}">[{platform}]</span> '
            f'<span style="color:rgba(255,255,255,0.40)">{message}</span>'
        )
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_log(self):
        self.log_view.clear()
