"""Qt Quick 聊天模型、虚拟列表和历史分页回归测试。"""

from datetime import datetime

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


@pytest.mark.gui
def test_quick_chat_uses_virtual_list_and_preserves_tg_roles(qapp, qtbot):
    from PySide6.QtQuick import QQuickItem
    from dmshoot.gui.quick_chat_view import ChatView

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
    assert visual_item_count(root) < 500


@pytest.mark.gui
def test_quick_chat_append_and_history_signal(qapp, qtbot):
    from dmshoot.gui.quick_chat_view import ChatView

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
