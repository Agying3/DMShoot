# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DMShoot single-exe build."""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os
import sys

_block_cipher = None

# ── 动态导入的模块 ──
hiddenimports = [
    # PySide6
    "PySide6.QtPrintSupport",
    "PySide6.QtSql",
    # dmshoot plugins (动态加载)
    "dmshoot.plugins.douyin.adapter",
    "dmshoot.plugins.bilibili.adapter",
    "dmshoot.plugins.kuaishou.adapter",
    "dmshoot.plugins.xiaohongshu.adapter",
    # 隐式依赖
    "qrcode",
    "websocket",
    "markdown_it",
    "rich",
    "rich.console",
    "rich.theme",
    "rich.logging",
    "rich.panel",
    "httpx",
    "playwright",
    "cryptography",
    "yaml",
    "bs4",
]

# ── 数据文件 ──
datas = [
    # GUI 样式
    ("dmshoot/gui/styles.qss", "dmshoot/gui"),
    # prompts
    ("prompts/", "prompts"),
    # 平台 icon
    ("resources/", "resources"),
    # DouYin_Spider SDK (签名 JS)
    ("external/DouYin_Spider/", "external/DouYin_Spider"),
]

# ── 二进制文件（直接打进 exe） ──
import glob as _glob
_node_dir = r"C:\Users\Administrator\.workbuddy\binaries\node\versions"
_node_dirs = sorted(_glob.glob(f"{_node_dir}/*"), reverse=True)
_node_exe = None
for _d in _node_dirs:
    _exe = os.path.join(_d, "node.exe")
    if os.path.isfile(_exe):
        _node_exe = _exe
        break
if not _node_exe:
    for _d in [r"C:\Program Files\nodejs", r"C:\Program Files (x86)\nodejs"]:
        _exe = os.path.join(_d, "node.exe")
        if os.path.isfile(_exe):
            _node_exe = _exe
            break

binaries = [(_node_exe, ".")] if _node_exe else []

# ── 排除臃肿模块 ──
excludes = [
    "tkinter", "matplotlib", "numpy", "scipy",
    "pandas", "PIL", "cv2", "jedi", "notebook",
    "tornado", "pygments.lexers",  # pygments 会通胀 30MB+
]

# 优化级别
optimize = 2   # -OO: 去除 assert + docstring

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=optimize,
)
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=_block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DMShoot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # 临时开启看报错，发布时改False
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="resources/tujue.ico",
)
