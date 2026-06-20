"""提示词页面 — 左窄面板 + 右预览"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QTextEdit, QLabel, QSplitter
)
from PySide6.QtCore import Signal, Qt


class PromptPage(QWidget):
    prompt_changed = Signal(str)           # 角色提示词变化
    behavior_changed = Signal(str)         # 行为提示词变化

    def __init__(self):
        super().__init__()
        main = QHBoxLayout()
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(10)

        # === 左列：选择器 ===
        left = QWidget()
        left.setFixedWidth(220)
        ll = QVBoxLayout()
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        gb = QGroupBox("角色提示词")
        gl = QVBoxLayout()
        gl.setSpacing(4)
        self.char_list = QListWidget()
        self.char_list.currentTextChanged.connect(self._on_char_select)
        gl.addWidget(self.char_list)
        gb.setLayout(gl)
        ll.addWidget(gb)

        gb2 = QGroupBox("行为提示词")
        gl2 = QVBoxLayout()
        gl2.setSpacing(4)
        self.behavior_list = QListWidget()
        self.behavior_list.currentTextChanged.connect(self._on_behavior_select)
        gl2.addWidget(self.behavior_list)
        gb2.setLayout(gl2)
        ll.addWidget(gb2)

        left.setLayout(ll)
        main.addWidget(left)

        # === 右列：预览 ===
        right = QGroupBox("预览")
        rl = QVBoxLayout()
        rl.setSpacing(6)
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("选中左侧列表查看内容...")
        rl.addWidget(self.editor)
        right.setLayout(rl)
        main.addWidget(right, stretch=1)

        self.setLayout(main)
        self._char_prompts = {}
        self._behavior_prompts = {}

    def load_chars(self, items: dict[str, str], select: str = ""):
        self._char_prompts = items
        self.char_list.clear()
        self.char_list.addItems(list(items.keys()))
        if select and select in items:
            self.char_list.setCurrentRow(list(items.keys()).index(select))
        elif self.char_list.count() > 0:
            self.char_list.setCurrentRow(0)

    def load_behaviors(self, items: dict[str, str], select: str = ""):
        self._behavior_prompts = items
        self.behavior_list.blockSignals(True)
        self.behavior_list.clear()
        self.behavior_list.addItems(list(items.keys()))
        if select and select in items:
            self.behavior_list.setCurrentRow(list(items.keys()).index(select))
        elif self.behavior_list.count() > 0:
            self.behavior_list.setCurrentRow(0)
        self.behavior_list.blockSignals(False)

    def _on_char_select(self, name: str):
        if name and name in self._char_prompts:
            self.editor.setPlainText(self._char_prompts[name])
        if name:
            self.prompt_changed.emit(name)

    def _on_behavior_select(self, name: str):
        if name and name in self._behavior_prompts:
            self.editor.setPlainText(self._behavior_prompts[name])
        if name:
            self.behavior_changed.emit(name)

    def set_content(self, text: str):
        self.editor.setPlainText(text)

    def current_char(self) -> str:
        item = self.char_list.currentItem()
        return item.text() if item else ""

    def current_behavior(self) -> str:
        item = self.behavior_list.currentItem()
        return item.text() if item else ""
