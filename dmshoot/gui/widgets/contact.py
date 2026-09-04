"""通讯录——粉丝会话列表（头像懒加载 + 进度条）

线程安全: QPixmap 只在主线程创建（_Loader 传 bytes，_on_loader_done 转 QPixmap）
性能: _widget_map O(1) 查找，_Loader 提到模块级避免重复定义信号类
"""

import httpx
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QHBoxLayout, QFrame, QPushButton, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QThread, QTimer, QPoint, QEvent
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor

import hashlib
import time as _time_ms

from dmshoot.storage.models import SessionRecord
from dmshoot.gui.widgets.glow_progress_bar import GlowProgressBar


def _update_item_text(w: QFrame, last_text: str = "", peer_name: str = "", peer_id: str = ""):
    """更新 ContactItem 的名字和最后消息文字"""
    lyt = w.layout()
    if not lyt:
        return
    # 找到 info layout（QVBoxLayout），跳过 avatar、AI按钮等 widget
    info_lyt = None
    for i in range(lyt.count()):
        item = lyt.itemAt(i)
        if item and hasattr(item, 'count'):
            info_lyt = item
            break
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
    active_message_requested = Signal(str)  # session_id — 右键请求AI主动发消息

    def __init__(self, session: SessionRecord):
        super().__init__()
        self.session_id = session.session_id
        self.setObjectName("contactItem")
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        self._avatar_url = session.avatar_url
        self._avatar_loaded = False

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 8, 6, 8)
        layout.setSpacing(4)

        self.avatar = QLabel(session.peer_name[0] if session.peer_name else "?")
        self.avatar.setObjectName("contactAvatar")
        self.avatar.setFixedSize(44, 44)
        self.avatar.setAlignment(Qt.AlignCenter)
        # 头像属于联系人点击区域；让事件落到 ContactItem，避免点头像时不打开会话。
        self.avatar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.avatar)

        # AI 按钮
        ai_btn = QPushButton("AI")
        ai_btn.setObjectName("activeMsgBtn")
        ai_btn.setFixedSize(28, 22)
        ai_btn.setCursor(Qt.PointingHandCursor)
        ai_btn.setMouseTracking(True)
        ai_btn.setAttribute(Qt.WA_Hover, True)
        ai_btn.clicked.connect(lambda: self.active_message_requested.emit(self.session_id))
        layout.addWidget(ai_btn)

        # 自定义毛玻璃 tooltip
        self._tooltip = _GlassTooltip(self)
        ai_btn.installEventFilter(self)

        info = QVBoxLayout()
        info.setSpacing(3)
        name = QLabel(session.peer_name or f"用户{session.peer_id}")
        name.setObjectName("contactName")
        name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        last = QLabel(session.last_message[:30] if session.last_message else "")
        last.setObjectName("contactLast")
        last.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        event.accept()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Enter:
            pos = obj.mapToGlobal(QPoint(0, -self._tooltip.height() - 4))
            self._tooltip.move(pos)
            self._tooltip.show()
        elif event.type() == QEvent.Type.Leave:
            self._tooltip.hide()
        return super().eventFilter(obj, event)


class _GlassTooltip(QFrame):
    """毛玻璃 tooltip — QWidget 模拟，支持真正的 rgba 半透明"""

    def __init__(self, parent):
        super().__init__(None)  # 无父级 = 顶层窗口
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        label = QLabel("基于上下文主动发一句")
        label.setStyleSheet(
            "color: rgba(255,255,255,0.85); font-size: 11px; padding: 4px 10px;"
        )
        lyt = QHBoxLayout()
        lyt.setContentsMargins(0, 0, 0, 0)
        lyt.addWidget(label)
        self.setLayout(lyt)
        self.adjustSize()
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(24, 26, 36, 200))  # rgba ≈ 0.78 不透明度
        p.setPen(QColor(255, 255, 255, 12))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        super().paintEvent(event)


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
    active_message_requested = Signal(str)  # session_id — AI主动发消息

    def __init__(self):
        super().__init__()
        self._widget_map: dict[str, ContactItem] = {}  # O(1) 查找
        self._loader: _AvatarLoader | None = None
        self._ensure_timer = QTimer(self)
        self._ensure_timer.setSingleShot(True)
        self._ensure_timer.setInterval(100)
        self._ensure_timer.timeout.connect(self._ensure_all_ai_buttons)

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
        # ContactItem 自己负责发出点击信号，避免一次点击触发两次会话加载。
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
                widget.active_message_requested.connect(self.active_message_requested)
                item.setSizeHint(widget.sizeHint())
                self.list.addItem(item)
                self.list.setItemWidget(item, widget)
                self._widget_map[sid] = widget
                if s.avatar_url:
                    added.append((sid, s.avatar_url))

        # 确保所有widget都有AI按钮（延迟检查，等布局渲染完）
        if not self._ensure_timer.isActive():
            self._ensure_timer.start()

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

    def _ensure_all_ai_buttons(self):
        """确保所有已存在的 widget 都有可见的 AI 按钮"""
        for sid, w in self._widget_map.items():
            btn = w.findChild(QPushButton, "activeMsgBtn")
            if btn is None:
                btn = QPushButton("AI")
                btn.setObjectName("activeMsgBtn")
                btn.setFixedSize(28, 22)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip("基于上下文主动发一句")
                btn.clicked.connect(lambda _, sid=sid: self.active_message_requested.emit(sid))
                w.layout().insertWidget(1, btn)
                btn.show()
            # 强制可见（解决渲染/布局导致的隐藏）
            btn.setVisible(True)
            btn.show()
            btn.raise_()
            btn.repaint()

    def update_one_session(self, session_id: str, last_message: str = "", last_time: float = 0, unread_count: int = -1):
        """O(1) 增量更新一个会话的最近消息文字和未读徽标，不查 DB"""
        w = self._widget_map.get(session_id)
        if not w:
            return False
        _update_item_text(w, last_message[:30])
        if unread_count >= 0:
            w._update_badge(unread_count)
        return True

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
