"""Qt Quick 聊天模型、虚拟列表和历史分页回归测试。"""

from datetime import datetime
import time

import pytest


def _messages(count: int, session: str = "quick:test"):
    from dmshoot.storage.models import ChatMessage

    base = datetime(2026, 8, 30, 10, 0).timestamp()
    return [
        ChatMessage(
            session_id=session,
            sender_name="Alice" if i % 2 == 0 else "AI",
            sender_id="alice" if i % 2 == 0 else "ai",
            content=f"第{i}条消息 " + "内容 " * (i % 5 + 1),
            is_self=i % 2 == 1,
            is_auto=i % 2 == 1,
            timestamp=base + i,
            id=i + 1,
        )
        for i in range(count)
    ]


def test_quick_model_keeps_5000_messages_without_widgets(qapp):
    from dmshoot.gui.quick_chat_view import ChatMessageModel

    model = ChatMessageModel()
    messages = _messages(5000)
    model.set_messages(messages)

    assert len(model.messages) == 5000
    assert model.rowCount() == 5000
    assert model.index(4999, 0).isValid()


def test_consecutive_messages_share_one_tg_avatar_group(qapp):
    from dmshoot.gui.quick_chat_view import ChatMessageModel
    from dmshoot.storage.models import ChatMessage

    base = datetime(2026, 8, 30, 10, 0).timestamp()
    group = [
        ChatMessage(
            session_id="quick:group",
            sender_name="Alice",
            sender_id="alice",
            content=f"连续消息 {index}",
            timestamp=base + index * 30,
        )
        for index in range(3)
    ]
    separate = ChatMessage(
        session_id="quick:group",
        sender_name="Alice",
        sender_id="alice",
        content="超过时间窗口",
        timestamp=base + 400,
    )
    model = ChatMessageModel()
    model.set_messages(group + [separate])

    assert model.rowCount() == 2
    assert [row["position"] for row in model._items[0]["messages"]] == [
        "first", "middle", "last",
    ]
    assert model._items[0]["avatarText"] == "Alice"


def test_ai_and_platform_echo_share_one_outgoing_group(qapp):
    """AI 本地回复和平台回显使用不同 sender_id 时仍只有一个我方组。"""
    from dmshoot.gui.quick_chat_view import ChatMessageModel
    from dmshoot.storage.models import ChatMessage

    base = datetime(2026, 8, 30, 10, 0).timestamp()
    model = ChatMessageModel()
    model.set_messages([
        ChatMessage(
            session_id="quick:echo", sender_name="AI", sender_id="ai",
            content="第一段", is_auto=True, timestamp=base,
        ),
        ChatMessage(
            session_id="quick:echo", sender_name="我", sender_id="platform-id",
            content="第二段", is_self=True, timestamp=base + 20,
            message_key="bilibili:echo:2",
        ),
    ])

    assert model.rowCount() == 1
    assert [row["position"] for row in model._items[0]["messages"]] == ["first", "last"]


@pytest.mark.gui
def test_explicit_quick_chat_uses_virtual_list_and_preserves_tg_roles(qapp, qtbot, monkeypatch):
    from PySide6.QtQuick import QQuickItem
    from dmshoot.gui.quick_chat_view import ChatView

    monkeypatch.setenv("DMSHOOT_CHAT_RENDERER", "quick")

    def visual_item_count(item: QQuickItem) -> int:
        return 1 + sum(visual_item_count(child) for child in item.childItems())

    def named_item_count(item: QQuickItem, object_name: str) -> int:
        own = int(item.objectName() == object_name)
        return own + sum(named_item_count(child, object_name) for child in item.childItems())

    view = ChatView()
    qtbot.addWidget(view)
    view.resize(760, 520)
    view.show()
    view.load_messages("Alice", _messages(5000))
    qtbot.wait(120)

    assert view.renderer_name == "quick"
    assert view.renderer_backend in {"Direct3D11", "OpenGL", "Software", "Unknown"}
    assert len(view._model.messages) == 5000
    assert view._model.rowCount() == 5000
    assert view._root is not None
    assert view._quick is not None
    root = view._quick.rootObject()
    message_list = root.findChild(QQuickItem, "messageList")
    assert message_list is not None
    assert message_list.property("contentHeight") > message_list.height()
    assert named_item_count(root, "bubbleRow") > 0
    # The model keeps all history, while the scene graph only materializes the viewport/cache.
    assert visual_item_count(root) < 650


@pytest.mark.gui
def test_auto_renderer_uses_quick_by_default(qapp, qtbot, monkeypatch):
    monkeypatch.delenv("DMSHOOT_CHAT_RENDERER", raising=False)
    monkeypatch.delenv("DMSHOOT_SOFTWARE_RENDER", raising=False)
    from dmshoot.gui.quick_chat_view import ChatView

    view = ChatView()
    qtbot.addWidget(view)
    view.resize(760, 520)
    view.show()
    qtbot.wait(80)

    assert view.renderer_name == "quick"
    assert view._quick is not None
    assert view._legacy is None


@pytest.mark.gui
def test_quick_transparent_overlay_preserves_parent_wallpaper(qapp, qtbot, monkeypatch):
    """Quick 空白区和气泡区都必须透出 QWidget 父级壁纸。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QWidget
    from dmshoot.gui.quick_chat_view import ChatView

    monkeypatch.setenv("DMSHOOT_CHAT_RENDERER", "quick")

    class Wallpaper(QWidget):
        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#27a7d8"))

    wallpaper = Wallpaper()
    wallpaper.resize(800, 560)
    wallpaper.show()
    view = ChatView(parent=wallpaper)
    view.setGeometry(20, 20, 760, 520)
    view.show()
    qtbot.wait(120)

    def pixel_at(x, y):
        # 抓父级最终合成图，而不是只抓 Quick 自身的透明 FBO。
        return wallpaper.grab().toImage().pixelColor(view.x() + x, view.y() + y)

    empty = pixel_at(20, 180)
    assert empty.blue() > 150 and empty.green() > 90

    from dmshoot.storage.models import ChatMessage
    view.load_messages("Alice", [ChatMessage(
        session_id="quick:transparent", sender_name="Alice", sender_id="alice",
        content="覆盖层仍然透明", timestamp=1770000000,
    )])
    qtbot.wait(160)
    overlay = pixel_at(20, 180)
    assert overlay.blue() > 150 and overlay.green() > 90
    assert view._quick is not None
    assert not view.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not view._content_host.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not view._content_stack.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    # Windows 的 QQuickWidget 透明 FBO 需要保持在父级 QWidget 合成层之上，
    # 否则透明像素会穿透到 DMShoot 窗口外，而不是透出 WallpaperBody。
    assert view._quick.testAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
    assert view._quick.autoFillBackground() is False


@pytest.mark.gui
def test_quick_chat_append_and_history_signal(qapp, qtbot, monkeypatch):
    from dmshoot.gui.quick_chat_view import ChatView

    monkeypatch.setenv("DMSHOOT_CHAT_RENDERER", "quick")
    view = ChatView()
    qtbot.addWidget(view)
    view.resize(760, 520)
    view.show()
    messages = _messages(120)
    view.load_messages("Alice", messages[-100:])
    qtbot.wait(80)

    requested = []
    view.history_requested.connect(requested.append)
    view._root.historyRequested.emit()
    assert requested == [""]

    from dmshoot.storage.models import ChatMessage

    view.append_message(
        ChatMessage(
            session_id="quick:test",
            sender_name="Alice",
            sender_id="alice",
            content="新消息",
            timestamp=1770000000,
        )
    )
    assert len(view._model.messages) == 101


def test_database_get_messages_before_orders_equal_timestamps(temp_db):
    from dmshoot.storage import database
    from dmshoot.storage.models import ChatMessage

    messages = [
        ChatMessage(
            session_id="page:1",
            sender_name="u",
            sender_id="u",
            content=str(i),
            timestamp=100.0,
        )
        for i in range(5)
    ]
    for message in messages:
        database.save_message(message)
    latest = database.get_messages("page:1", limit=2)
    assert [item.content for item in latest] == ["3", "4"]
    older = database.get_messages_before(
        "page:1", latest[0].timestamp, before_id=latest[0].id, limit=2
    )
    assert [item.content for item in older] == ["1", "2"]


@pytest.mark.gui
def test_forced_widgets_renderer_is_available(qapp, qtbot, monkeypatch):
    monkeypatch.setenv("DMSHOOT_CHAT_RENDERER", "widgets")
    from dmshoot.gui.quick_chat_view import ChatView

    view = ChatView()
    qtbot.addWidget(view)
    assert view.renderer_name == "widgets"
    assert view.renderer_backend == "Software"
    assert view._legacy is not None


@pytest.mark.gui
def test_contact_avatar_click_opens_session(qapp, qtbot):
    from PySide6.QtCore import Qt
    from dmshoot.gui.widgets.contact import ContactItem
    from dmshoot.storage.models import SessionRecord

    session = SessionRecord(
        session_id="bilibili:contact:1",
        platform="bilibili",
        peer_id="1",
        peer_name="Alice",
    )
    item = ContactItem(session)
    qtbot.addWidget(item)
    clicked = []
    item.clicked.connect(clicked.append)
    item.show()

    qtbot.mouseClick(item.avatar, Qt.LeftButton)

    assert clicked == [session.session_id]


@pytest.mark.gui
def test_markdown_switch_discards_stale_background_result(qapp, qtbot, tmp_path, monkeypatch):
    from dmshoot.gui.quick_chat_view import ChatView

    old_document = tmp_path / "old.md"
    new_document = tmp_path / "new.md"
    old_document.write_text("# OLD", encoding="utf-8")
    new_document.write_text("# NEW", encoding="utf-8")

    original_read_text = type(old_document).read_text

    def delayed_read_text(path, *args, **kwargs):
        if path == old_document:
            time.sleep(0.12)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(old_document), "read_text", delayed_read_text)
    view = ChatView()
    qtbot.addWidget(view)
    view.resize(760, 520)
    view.show()

    view.show_markdown(str(old_document), "旧文档")
    view.show_markdown(str(new_document), "新文档")

    qtbot.waitUntil(lambda: "NEW" in view._markdown_browser.toPlainText(), timeout=3000)
    qtbot.wait(180)
    assert "NEW" in view._markdown_browser.toPlainText()
    assert "OLD" not in view._markdown_browser.toPlainText()


@pytest.mark.gui
def test_quick_avatar_is_circular_and_sticks_while_group_scrolls(qapp, qtbot, tmp_path, monkeypatch):
    """真实渲染断言：头像有图、四角不泄漏，并在长消息组中吸附到底部。"""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtQuick import QQuickItem
    from dmshoot.gui.quick_chat_view import ChatView
    from dmshoot.storage.models import ChatMessage

    monkeypatch.setenv("DMSHOOT_CHAT_RENDERER", "quick")
    avatar_path = tmp_path / "avatar.png"
    avatar_image = QImage(48, 48, QImage.Format.Format_ARGB32)
    avatar_image.fill(QColor("#ef4444"))
    assert avatar_image.save(str(avatar_path))

    base = datetime(2026, 8, 30, 10, 0).timestamp()
    messages = [
        ChatMessage(
            session_id="quick:avatar",
            sender_name="Alice",
            sender_id="alice",
            content=f"第 {index} 条连续消息，保证组高度超过视口。",
            timestamp=base + index * 20,
        )
        for index in range(12)
    ]
    messages.extend(
        ChatMessage(
            session_id="quick:avatar",
            sender_name="Bob",
            sender_id="bob",
            content=f"后续消息 {index}",
            timestamp=base + 300 + index * 20,
        )
        for index in range(8)
    )
    view = ChatView()
    qtbot.addWidget(view)
    view.resize(520, 250)
    view.show()
    view.load_messages("Alice", messages, str(avatar_path))
    qtbot.waitUntil(
        lambda: bool(view._model._items and view._model._items[0]["avatarSource"]),
        timeout=3000,
    )
    qtbot.wait(120)

    root = view._quick.rootObject()
    message_list = root.findChild(QQuickItem, "messageList")
    def named_items(item, object_name):
        matches = [item] if item.objectName() == object_name else []
        for child in item.childItems():
            matches.extend(named_items(child, object_name))
        return matches

    avatars = named_items(root, "groupAvatar")
    assert message_list is not None
    assert avatars
    avatar = avatars[0]
    group = avatar.parentItem().parentItem()

    def avatar_scene_y():
        return avatar.mapToItem(root, QPointF(0, 0)).y()

    message_list.setProperty("contentY", 0)
    qtbot.wait(80)
    frame = view._quick.grab().toImage()
    point = avatar.mapToItem(root, QPointF(18, 18))
    center = frame.pixelColor(round(point.x()), round(point.y()))
    corner = frame.pixelColor(
        round(avatar.mapToItem(root, QPointF(1, 1)).x()),
        round(avatar.mapToItem(root, QPointF(1, 1)).y()),
    )
    assert center.red() > 180 and center.green() < 100
    assert corner.red() < 40 and corner.green() < 40 and corner.blue() < 45

    start_y = avatar_scene_y()
    message_list.setProperty("contentY", min(90, message_list.property("contentHeight") - message_list.height()))
    qtbot.wait(80)
    # 在组还没有露出最后一条时，头像固定于视口底部，不会被滚走。
    assert abs(avatar_scene_y() - start_y) <= 2

    message_list.setProperty("contentY", min(
        group.height() + 12,
        message_list.property("contentHeight") - message_list.height(),
    ))
    qtbot.wait(80)
    # 到达组尾后，头像回到组底，随消息一起离开视口。
    assert avatar_scene_y() < start_y - 4, (
        f"start={start_y}, end={avatar_scene_y()}, contentY={message_list.property('contentY')}, "
        f"contentHeight={message_list.property('contentHeight')}, listHeight={message_list.height()}, "
        f"groupY={group.y()}, groupHeight={group.height()}"
    )


@pytest.mark.gui
def test_default_widget_avatar_is_at_group_tail_and_gets_pushed_up(qapp, qtbot, monkeypatch):
    """默认 QWidget 路径也必须执行 TG 头像的组尾吸附和上顶。"""
    monkeypatch.setenv("DMSHOOT_CHAT_RENDERER", "widgets")
    from PySide6.QtCore import QPoint
    from dmshoot.gui.quick_chat_view import ChatView
    from dmshoot.gui.widgets.chat_view import MessageGroupWidget
    from dmshoot.storage.models import ChatMessage

    base = datetime(2026, 8, 30, 10, 0).timestamp()
    messages = [
        ChatMessage(
            session_id="widgets:avatar", sender_name="Alice", sender_id="alice",
            content=f"连续消息 {index}，用于验证头像组尾定位。",
            timestamp=base + index * 20,
        )
        for index in range(20)
    ]
    messages.append(ChatMessage(
        session_id="widgets:avatar", sender_name="Bob", sender_id="bob",
        content="后续打断消息", timestamp=base + 1000,
    ))

    view = ChatView()
    qtbot.addWidget(view)
    view.resize(520, 250)
    view.show()
    view.load_messages("Alice", messages)
    qtbot.wait(150)

    legacy = view._legacy
    assert legacy is not None
    groups = [item for item in legacy._content_items if isinstance(item, MessageGroupWidget)]
    assert len(groups) == 2
    first = groups[0]
    viewport = legacy.scroll.viewport()
    scrollbar = legacy.scroll.verticalScrollBar()

    scrollbar.setValue(0)
    qtbot.wait(80)

    def avatar_scene_y():
        return first.avatar.mapTo(viewport, QPoint(0, 0)).y()

    group_scene_y = first.mapTo(viewport, QPoint(0, 0)).y()
    expected_bottom = min(group_scene_y + first.height(), viewport.height() - 4)
    assert abs(avatar_scene_y() + first.avatar.height() - expected_bottom) <= 2
    start_y = avatar_scene_y()

    stick_bottom = viewport.height() - first.avatar.height() - 4
    push_scroll = first.y() + first.height() - stick_bottom + 20
    scrollbar.setValue(min(scrollbar.maximum(), max(0, push_scroll)))
    qtbot.wait(80)
    assert avatar_scene_y() < start_y - 4, (
        f"start={start_y}, end={avatar_scene_y()}, scroll={scrollbar.value()}, "
        f"maximum={scrollbar.maximum()}, groupY={first.y()}, groupHeight={first.height()}"
    )


@pytest.mark.gui
def test_homepage_avatar_click_opens_wallpaper_safe_chat(temp_db, qapp, qtbot):
    """联系人头像点击必须打开与主窗口壁纸共享合成链路的聊天区。"""
    from PySide6.QtCore import Qt
    from dmshoot.gui.monitor_panel import MonitorPanel
    from dmshoot.gui.pages.home_page import HomePage
    from dmshoot.storage import database
    from dmshoot.storage.models import ChatMessage, SessionRecord

    session = SessionRecord(
        session_id="bilibili:alice",
        platform="bilibili",
        peer_id="alice",
        peer_name="Alice",
        last_message="可见消息",
        last_time=1770000000,
    )
    database.upsert_session(session)
    database.save_message(ChatMessage(
        session_id=session.session_id,
        sender_name="Alice",
        sender_id="alice",
        content="可见消息",
        timestamp=1770000000,
    ))

    page = HomePage(MonitorPanel(), [("bilibili", "B站")])
    qtbot.addWidget(page)
    page.resize(900, 640)
    page.show()
    qtbot.waitUntil(lambda: session.session_id in page.contacts._widget_map, timeout=2500)

    contact = page.contacts._widget_map[session.session_id]
    qtbot.mouseClick(contact.avatar, Qt.LeftButton)
    qtbot.waitUntil(lambda: page.chat.title_label.text() == "Alice", timeout=2500)
    assert page.chat.renderer_name == "quick"
    assert page.chat._content_stack.currentWidget() is page.chat._quick
    assert page.chat._quick.width() > 100 and page.chat._quick.height() > 100
    assert len(page.chat._model.messages) == 1
