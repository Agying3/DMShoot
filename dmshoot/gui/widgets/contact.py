"""通讯录——粉丝会话列表（头像懒加载 + 进度条）

线程安全: QPixmap 只在主线程创建（_Loader 传 bytes，_on_loader_done 转 QPixmap）
性能: _widget_map O(1) 查找，_Loader 提到模块级避免重复定义信号类
"""

import httpx
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QHBoxLayout, QFrame
)
from PySide6.QtCore import Signal, Qt, QThread
from PySide6.QtGui import QPixmap, QPainter, QPainterPath

import hashlib
import time as _time_ms

from dmshoot.storage.models import SessionRecord
from dmshoot.gui.widgets.glow_progress_bar import GlowProgressBar


def _update_item_text(w: QFrame, last_text: str = "", peer_name: str = "", peer_id: str = ""):
    """更新 ContactItem 的名字和最后消息文字（复用布局遍历逻辑）"""
    lyt = w.layout()
    if not lyt or lyt.count() < 2:
        return
    info_lyt = lyt.itemAt(1)
    if not info_lyt or info_lyt.count() < 2:
        return
    nl = info_lyt.itemAt(0).widget()
    ll = info_lyt.itemAt(1).widget()
    if isinstance(nl, QLabel) and peer_name:
        nl.setText(peer_name or f"用户{peer_id}")
    if isinstance(ll, QLabel) and last_text:
        ll.setText(last_text[:30])

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
AVATAR_DIR = _PROJECT_ROOT / "dmshoot" / "data" / "avatars"


def _round_pixmap(pix: QPixmap, size: int) -> QPixmap:
    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)
    p = QPainter(rounded)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pix)
    p.end()
    return rounded


class ContactItem(QFrame):
    clicked = Signal(str)

    def __init__(self, session: SessionRecord):
        super().__init__()
        self.session_id = session.session_id
        self.setObjectName("contactItem")
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        self._avatar_url = session.avatar_url
        self._avatar_loaded = False

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)

        self.avatar = QLabel(session.peer_name[0] if session.peer_name else "?")
        self.avatar.setObjectName("contactAvatar")
        self.avatar.setFixedSize(44, 44)
        self.avatar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.avatar)

        info = QVBoxLayout()
        info.setSpacing(3)
        name = QLabel(session.peer_name or f"用户{session.peer_id}")
        name.setObjectName("contactName")
        last = QLabel(session.last_message[:30] if session.last_message else "")
        last.setObjectName("contactLast")
        info.addWidget(name)
        info.addWidget(last)
        layout.addLayout(info, stretch=1)

        if session.unread_count > 0:
            badge = QLabel(str(session.unread_count))
            badge.setObjectName("contactBadge")
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignCenter)
            layout.addWidget(badge)

        self.setLayout(layout)

    def _update_badge(self, unread_count: int):
        """更新或创建/移除未读徽标"""
        layout = self.layout()
        if not layout:
            return
        # 查找已有的 badge (objectName = "contactBadge")
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w and w.objectName() == "contactBadge":
                if unread_count <= 0:
                    w.deleteLater()
                else:
                    w.setText(str(unread_count))
                return
        # 没有 badge，新建
        if unread_count > 0:
            badge = QLabel(str(unread_count))
            badge.setObjectName("contactBadge")
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignCenter)
            layout.addWidget(badge)

    def mousePressEvent(self, event):
        self.clicked.emit(self.session_id)


class _AvatarLoader(QThread):
    """头像下载线程 — 只传 bytes，不创建 QPixmap（Qt 禁止跨线程创建图形对象）"""
    done = Signal(object)

    def __init__(self, urls: list, parent=None):
        super().__init__(parent)
        self._urls = urls

    def run(self):
        total = len(self._urls)
        results = []
        for i, (sid, url) in enumerate(self._urls):
            pct = int((i + 1) / total * 100)
            try:
                AVATAR_DIR.mkdir(parents=True, exist_ok=True)
                cache_key = hashlib.md5(url.encode()).hexdigest()[:16]  # URL hash，换头像自动更新
                cp = AVATAR_DIR / f"{cache_key}.png"
                fail_flag = AVATAR_DIR / f"{cache_key}.fail"
                # negative cache：24h 内失败过不再重试
                if fail_flag.exists():
                    if _time_ms.time() - fail_flag.stat().st_mtime < 86400:
                        self.done.emit(("progress", pct))
                        continue
                    fail_flag.unlink(missing_ok=True)
                if cp.exists() and cp.stat().st_size > 4096:
                    data = cp.read_bytes()
                else:
                    # Referer 自适应平台（B站 CDN 拒绝非 bilibili 来源）
                    referer = ""
                    if "hdslb.com" in url:
                        referer = "https://www.bilibili.com/"
                    elif "douyin.com" in url or "douyinvod.com" in url:
                        referer = "https://www.douyin.com/"
                    elif "xhscdn.com" in url:
                        referer = "https://www.xiaohongshu.com/"
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    }
                    if referer:
                        headers["Referer"] = referer
                    r = httpx.get(url, timeout=10, follow_redirects=True, headers=headers)
                    if r.status_code != 200 or len(r.content) < 4096:
                        fail_flag.write_text("1")
                        self.done.emit(("progress", pct))
                        continue
                    cp.write_bytes(r.content)
                    data = r.content
                results.append((sid, data))
                self.done.emit(("progress", pct))
            except Exception:
                self.done.emit(("progress", pct))
        if results:
            self.done.emit(("avatars", results))


class ContactList(QWidget):
    session_selected = Signal(str, str)  # session_id, peer_name

    def __init__(self):
        super().__init__()
        self._widget_map: dict[str, ContactItem] = {}  # O(1) 查找
        self._loader: _AvatarLoader | None = None

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("通讯录")
        title.setObjectName("sectionTitle")
        title.setStyleSheet("padding: 8px 12px;")
        layout.addWidget(title)

        self.progress = GlowProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.list = QListWidget()
        self.list.setObjectName("contactList")
        self.list.itemClicked.connect(self._on_click)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list.setStyleSheet(
            "QListWidget { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical {"
            "  background: rgba(255,255,255,0.08); border-radius: 2px; min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.14); }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        layout.addWidget(self.list)

        self.setLayout(layout)
        self.setFixedWidth(220)

    def closeEvent(self, event):
        if self._loader and self._loader.isRunning():
            self._loader.quit()
            self._loader.wait(2000)
        super().closeEvent(event)

    def set_sessions(self, sessions: list[SessionRecord]):
        new_ids = {s.session_id for s in sessions}
        old_ids = set(self._widget_map.keys())

        # 删除不在新列表中的
        for sid in old_ids - new_ids:
            w = self._widget_map.pop(sid, None)
            if w:
                idx = self.list.row(w) if hasattr(w, '__index_hint') else -1
                if idx < 0:
                    for i in range(self.list.count()):
                        if self.list.itemWidget(self.list.item(i)) is w:
                            idx = i
                            break
                if idx >= 0:
                    self.list.takeItem(idx)

        # 新增/更新
        added = []
        for s in sessions:
            sid = s.session_id
            if sid in self._widget_map:
                w = self._widget_map[sid]
                _update_item_text(w, s.last_message, s.peer_name, s.peer_id)
                if s.avatar_url and s.avatar_url != w._avatar_url:
                    w._avatar_url = s.avatar_url
                    w._avatar_loaded = False
                    added.append((sid, s.avatar_url))
            else:
                item = QListWidgetItem()
                widget = ContactItem(s)
                widget.clicked.connect(lambda sid=s.session_id, n=s.peer_name: self.session_selected.emit(sid, n))
                item.setSizeHint(widget.sizeHint())
                self.list.addItem(item)
                self.list.setItemWidget(item, widget)
                self._widget_map[sid] = widget
                if s.avatar_url:
                    added.append((sid, s.avatar_url))

        if added:
            # 去重
            seen = set()
            unique = []
            for sid, url in added:
                if sid not in seen:
                    seen.add(sid)
                    unique.append((sid, url))
            from PySide6.QtCore import QTimer
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda urls=unique: self._load_avatars(urls))
            timer.start(300)

    def update_one_session(self, session_id: str, last_message: str = "", last_time: float = 0, unread_count: int = -1):
        """O(1) 增量更新一个会话的最近消息文字和未读徽标，不查 DB"""
        w = self._widget_map.get(session_id)
        if not w:
            return
        _update_item_text(w, last_message[:30])
        if unread_count >= 0:
            w._update_badge(unread_count)

    def _on_click(self, item):
        w = self.list.itemWidget(item)
        if w:
            # 从 ContactItem 提取名字
            name = ""
            lyt = w.layout()
            if lyt and lyt.count() >= 2:
                info_lyt = lyt.itemAt(1)
                if info_lyt and info_lyt.count() >= 1:
                    nl = info_lyt.itemAt(0).widget()
                    if isinstance(nl, QLabel):
                        name = nl.text()
            self.session_selected.emit(w.session_id, name)

    def _load_avatars(self, urls: list):
        if not urls:
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)

        if self._loader and self._loader.isRunning():
            self._loader.quit()
            self._loader.wait(1000)
        self._loader = _AvatarLoader(urls, self)
        self._loader.done.connect(self._on_loader_done)
        self._loader.start()

    def _on_loader_done(self, data):
        kind, payload = data
        if kind == "progress":
            self.progress.setValue(payload)
        else:
            self.progress.setVisible(False)
            for sid, img_bytes in payload:
                pix = QPixmap()
                pix.loadFromData(img_bytes)
                if not pix.isNull():
                    pix = pix.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    pix = _round_pixmap(pix, 44)
                    w = self._widget_map.get(sid)
                    if w:
                        w.avatar.setPixmap(pix)
                        w.avatar.setText("")
                        w._avatar_loaded = True
