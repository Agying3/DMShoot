"""平台刻度尺——从插件注册表动态生成"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Signal


class PlatformRuler(QWidget):
    switched = Signal(str)  # platform id

    def __init__(self, platforms: list[tuple[str, str]]):
        super().__init__()
        self.setFixedHeight(52)
        self._btns: dict[str, QPushButton] = {}
        self._platforms = platforms

        layout = QHBoxLayout()
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(0)
        layout.addStretch()

        for pid, name in platforms:
            btn = QPushButton(name)
            btn.setObjectName("rulerBtn")
            btn.setCheckable(True)
            btn.setFixedSize(80, 36)
            btn.clicked.connect(lambda checked, p=pid: self._select(p))
            layout.addWidget(btn)
            self._btns[pid] = btn

        layout.addStretch()
        self.setLayout(layout)
        if platforms:
            self._select(platforms[0][0])

    def _select(self, platform: str):
        for pid, btn in self._btns.items():
            btn.setChecked(pid == platform)
        self.switched.emit(platform)

    def set_active(self, platform: str):
        # 如果已经是当前平台，跳过
        current = next((pid for pid, btn in self._btns.items() if btn.isChecked()), None)
        if platform != current:
            self._select(platform)
