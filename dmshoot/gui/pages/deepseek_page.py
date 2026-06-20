"""DeepSeek 连接页面 — 左窄输入 + 右工作面板"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QHBoxLayout, QFrame
)
from PySide6.QtCore import Signal, Qt, QPoint, QRect, QSize
from PySide6.QtGui import QRegion, QPainterPath

MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]


class _ModelItem(QPushButton):
    """弹窗里的选项按钮"""
    clicked_sig = Signal(str)

    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("modelItem")
        self.setFixedHeight(40)
        self.setStyleSheet(
            "QPushButton#modelItem {"
            "  background: transparent;"
            "  border: none;"
            "  border-radius: 14px;"
            "  color: rgba(255,255,255,0.95);"
            "  font-size: 14px;"
            "  padding: 8px 20px;"
            "  text-align: left; }"
            "QPushButton#modelItem:hover {"
            "  background: rgba(240,192,96,0.18);"
            "  color: #FFD580; }"
        )
        self.clicked.connect(lambda: self.clicked_sig.emit(text))


class DeepSeekPage(QWidget):
    save_clicked = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self._current_model = MODELS[0]
        self._popup: QFrame | None = None
        main = QHBoxLayout()
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(10)

        # === 左列 ===
        left = QWidget()
        left.setFixedWidth(260)
        ll = QVBoxLayout()
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        gb = QGroupBox("DeepSeek")
        gl = QVBoxLayout()
        gl.setSpacing(6)

        gl.addWidget(QLabel("API Key"))
        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("sk-...")
        self.api_key.setEchoMode(QLineEdit.Password)
        gl.addWidget(self.api_key)

        gl.addWidget(QLabel("Base URL"))
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://api.deepseek.com")
        gl.addWidget(self.base_url)

        gl.addWidget(QLabel("Model"))

        # 自定义下拉按钮
        self.model_btn = QPushButton(MODELS[0] + "  ▾")
        self.model_btn.setObjectName("modelCombo")
        self.model_btn.clicked.connect(self._toggle_popup)
        gl.addWidget(self.model_btn)

        self._connect_btn = QPushButton("连接")
        self._connect_btn.setObjectName("primaryBtn")
        self._connect_btn.clicked.connect(self._on_save)
        gl.addWidget(self._connect_btn)

        gb.setLayout(gl)
        ll.addWidget(gb)
        ll.addStretch()
        left.setLayout(ll)

        # === 右列 ===
        right = QWidget()
        right.setObjectName("ConfigPanel")
        rl = QVBoxLayout()
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setSpacing(8)

        title = QLabel("状态")
        title.setObjectName("sectionTitle")
        rl.addWidget(title)

        self.status = QLabel("未连接")
        self.status.setObjectName("infoLabel")
        self.status.setWordWrap(True)
        rl.addWidget(self.status)

        hint = QLabel(
            "DeepSeek 官方 API\n"
            "注册: https://platform.deepseek.com\n"
            f"模型: {', '.join(MODELS)}"
        )
        hint.setObjectName("infoLabel")
        hint.setWordWrap(True)
        rl.addWidget(hint)

        rl.addStretch()
        right.setLayout(rl)

        main.addWidget(left)
        main.addWidget(right, stretch=1)
        self.setLayout(main)

    # === 自定义弹窗 ===

    def _toggle_popup(self):
        if self._popup and self._popup.isVisible():
            self._popup.hide()
            self._popup.deleteLater()
            self._popup = None
            return
        self._show_popup()

    def _show_popup(self):
        self._popup = QFrame()
        self._popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setAttribute(Qt.WA_TranslucentBackground)
        self._popup.setStyleSheet(
            "QFrame {"
            "  background: rgba(12,14,20,0.72);"
            "  border: 1.5px solid rgba(240,192,96,0.40);"
            "  border-radius: 18px; }"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        for name in MODELS:
            item = _ModelItem(name)
            if name == self._current_model:
                item.setStyleSheet(
                    "QPushButton#modelItem {"
                    "  background: transparent;"
                    "  border: none;"
                    "  border-radius: 14px;"
                    "  color: #FFD580;"
                    "  font-weight: 600;"
                    "  font-size: 14px;"
                    "  padding: 8px 20px;"
                    "  text-align: left; }"
                    "QPushButton#modelItem:hover {"
                    "  background: rgba(240,192,96,0.25);"
                    "  color: #FFD580; }"
                )
            item.clicked_sig.connect(self._on_model_selected)
            layout.addWidget(item)

        self._popup.setLayout(layout)
        self._popup.adjustSize()

        # 圆角遮罩——真正裁剪四角
        path = QPainterPath()
        path.addRoundedRect(QRect(QPoint(0, 0), self._popup.size()), 18, 18)
        self._popup.setMask(QRegion(path.toFillPolygon().toPolygon()))

        # 定位在按钮正下方
        pos = self.model_btn.mapToGlobal(QPoint(0, self.model_btn.height() + 4))
        self._popup.move(pos)
        self._popup.show()

    def _on_model_selected(self, name: str):
        self._current_model = name
        self.model_btn.setText(name + "  ▾")
        if self._popup:
            self._popup.hide()
            self._popup.deleteLater()
            self._popup = None

    # === 保存 ===

    def _on_save(self):
        self.save_clicked.emit(
            self.api_key.text().strip(),
            self.base_url.text().strip(),
            self._current_model,
        )

    def set_values(self, api_key: str, base_url: str, model: str):
        self.api_key.setText(api_key)
        self.base_url.setText(base_url)
        if model in MODELS:
            self._current_model = model
            self.model_btn.setText(model + "  ▾")

    def set_status(self, text: str):
        self.status.setText(text)
        if text.startswith("已连接"):
            self.status.setStyleSheet("color: #4ADE80; font-size: 12px; background: transparent;")
            self._connect_btn.setText("重新连接")
        else:
            self.status.setStyleSheet("color: rgba(255,255,255,0.70); font-size: 12px; background: transparent;")
            self._connect_btn.setText("连接")
