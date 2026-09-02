"""DMShoot 应用图标和打包资源路径。"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def resource_root() -> Path:
    """返回开发版仓库根目录或 PyInstaller 解包目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def application_icon_path() -> Path:
    """返回应用运行时使用的原始图片图标路径。"""
    return resource_root() / "resources" / "大咸鱼.jpeg"


def application_icon() -> QIcon:
    """加载应用图标；资源缺失时返回空图标，避免阻塞启动。"""
    path = application_icon_path()
    return QIcon(str(path)) if path.is_file() else QIcon()
