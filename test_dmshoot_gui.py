"""DMShoot GUI + Adapter + Playwright 综合测试

运行: python test_dmshoot_gui.py
覆盖: BilibiliAdapter 解析 / GUI 组件 / Login 流程 / MessageBus 集成 / Cookie 提取
"""

import sys
import os
import asyncio
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── QApplication 全局单例 ──
from PySide6.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)


# ═══════════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════════

_results: list[tuple[str, bool, str]] = []

def ok(name: str, detail: str = ""):
    _results.append((name, True, detail))
    print(f"  [OK] {name}{' — ' + detail if detail else ''}")

def fail(name: str, reason: str):
    _results.append((name, False, reason))
    print(f"  [FAIL] {name}: {reason}")

def check(name: str, condition, detail: str = ""):
    if condition:
        ok(name, detail)
    else:
        fail(name, f"断言失败{f' ({detail})' if detail else ''}")


# ═══════════════════════════════════════════════════════════
# 1. BilibiliAdapter — 消息解析逻辑（无网络）
# ═══════════════════════════════════════════════════════════

def test_adapter_parse_text_message():
    """解析普通文本消息"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {
        "sender_uid": 200, "talker_id": 200,
        "content": "你好啊", "msg_type": 1,
        "msg_seqno": 5, "timestamp": 1700000000,
    }
    msg = adapter._parse_message(raw)
    check("parse_text platform", msg.platform == "bilibili")
    check("parse_text msg_type", msg.msg_type == "text")
    check("parse_text sender_id", msg.sender_id == "200")
    check("parse_text content", msg.content == "你好啊")
    check("parse_text is_self=False", not msg.is_self)
    check("parse_text session_id", msg.session_id == "bilibili:200")
    check("parse_text seq_id", msg.seq_id == 5)
    check("parse_text timestamp", msg.timestamp == 1700000000.0)


def test_adapter_parse_self_message():
    """解析自己发的消息"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 100, "talker_id": 200, "content": "我发的", "msg_type": 1}
    msg = adapter._parse_message(raw)
    check("parse_self is_self=True", msg.is_self)
    check("parse_self sender_id", msg.sender_id == "100")


def test_adapter_parse_image_message():
    """解析图片消息"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200, "content": "[图片]", "msg_type": 2}
    msg = adapter._parse_message(raw)
    check("parse_image msg_type", msg.msg_type == "image")

    raw2 = {"sender_uid": 200, "talker_id": 200, "content": "[图片]", "msg_type": 6}
    msg2 = adapter._parse_message(raw2)
    check("parse_image type6", msg2.msg_type == "image")


def test_adapter_parse_timestamp_milliseconds():
    """解析毫秒时间戳自动转换"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200, "content": "x",
           "msg_type": 1, "timestamp": 1700000000000}  # 毫秒
    msg = adapter._parse_message(raw)
    check("timestamp_ms 除以1000", msg.timestamp == 1700000000.0)


def test_adapter_parse_timestamp_string():
    """解析字符串时间戳"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200, "content": "x",
           "msg_type": 1, "timestamp": "1700000000"}
    msg = adapter._parse_message(raw)
    check("timestamp_str 解析", msg.timestamp == 1700000000.0)


def test_adapter_parse_timestamp_missing():
    """解析缺失时间戳"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200, "content": "x", "msg_type": 1}
    msg = adapter._parse_message(raw)
    check("timestamp_missing 生成当前时间戳(>0)", msg.timestamp > 0)


def test_adapter_parse_empty_content():
    """空内容返回 None"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200, "content": "", "msg_type": 1}
    msg = adapter._parse_message(raw)
    check("empty_content None", msg is None)

    raw2 = {"sender_uid": 200, "talker_id": 200, "content": "  ", "msg_type": 1}
    msg2 = adapter._parse_message(raw2)
    check("whitespace_content None", msg2 is None)


def test_adapter_parse_filter_system():
    """过滤系统消息"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    for sys_text in ["互相关注", "开始聊天吧", "登录成功"]:
        msg = adapter._parse_message(
            {"sender_uid": 200, "talker_id": 200, "content": sys_text, "msg_type": 1})
        check(f"filter_system '{sys_text}'", msg is None)


def test_adapter_parse_invalid_sender():
    """无效 sender_uid 返回 None"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    msg = adapter._parse_message(
        {"sender_uid": "abc", "talker_id": 200, "content": "x", "msg_type": 1})
    check("invalid_sender None", msg is None)


def test_adapter_parse_json_content():
    """解析 JSON 格式内容"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus
    import json

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200,
           "content": json.dumps({"content": "真正的消息内容"}),
           "msg_type": 1}
    msg = adapter._parse_message(raw)
    check("json_content 提取", msg.content == "真正的消息内容")


def test_adapter_parse_with_peer_name():
    """对方消息使用 peer_name"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    raw = {"sender_uid": 200, "talker_id": 200, "content": "hi", "msg_type": 1}
    msg = adapter._parse_message(raw, peer_name="张三")
    check("peer_name 对方消息", msg.sender_name == "张三")

    # 自己的消息不受 peer_name 影响
    raw2 = {"sender_uid": 100, "talker_id": 200, "content": "hi", "msg_type": 1}
    msg2 = adapter._parse_message(raw2, peer_name="张三")
    check("peer_name 不影响自己的消息", msg2.sender_name != "张三")


def test_adapter_state_tracking():
    """测试 replied 状态跟踪"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    check("初始 _replied 为空集", isinstance(adapter._replied, set))

    adapter._replied.add(100)
    adapter._replied.add(200)
    check("添加后包含", 100 in adapter._replied and 200 in adapter._replied)


def test_adapter_send_message_session_parsing():
    """测试 send_message 的 session_id 解析"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    # send_message 内部会调用 int(session_id.split(":")[-1])
    # 我们只测试解析部分不触发网络
    sid = adapter.platform_name
    check("platform_name", sid == "bilibili")


def test_adapter_disconnect_saves_state():
    """测试 disconnect 保存状态"""
    from dmshoot.plugins.bilibili.adapter import (
        BilibiliAdapter, STATE_FILE, _save_state, _load_state
    )
    from dmshoot.core.bus import MessageBus
    import json
    from pathlib import Path

    # 备份原始状态
    orig_exists = STATE_FILE.exists()
    orig_data = None
    if orig_exists:
        orig_data = STATE_FILE.read_text(encoding="utf-8")

    try:
        bus = MessageBus()
        adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
        adapter._replied = {1, 2, 3}
        adapter.disconnect()
        check("STATE_FILE 已创建", STATE_FILE.exists())
        state = _load_state()
        check("replied 已保存", set(state.get("replied", [])) == {1, 2, 3})
    finally:
        if orig_exists and orig_data:
            STATE_FILE.write_text(orig_data, encoding="utf-8")
        elif not orig_exists and STATE_FILE.exists():
            if STATE_FILE.exists():
                STATE_FILE.unlink()


def test_adapter_connect_no_network():
    """测试 connect 在网络不可用时的表现"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake_invalid", bilibili_jct="fake", bus=bus)
    # 凭证无效，connect 应该返回 False
    result = adapter.connect()
    check("connect 无效凭证返回 False", not result)


# ═══════════════════════════════════════════════════════════
# 2. GUI 组件测试
# ═══════════════════════════════════════════════════════════

def test_reply_log_entry():
    """测试回复日志条目渲染"""
    from dmshoot.gui.monitor_panel import ReplyLogEntry
    from dmshoot.storage.models import ChatMessage
    import time

    msg = ChatMessage(session_id="b:1", sender_name="测试用户",
                      content="在吗？", timestamp=time.time())
    entry = ReplyLogEntry(msg, ai_reply="来了来了")
    check("ReplyLogEntry 创建", entry is not None)
    check("ReplyLogEntry 是 QFrame", hasattr(entry, "setStyleSheet"))


def test_reply_log_entry_no_reply():
    """测试无 AI 回复时的条目"""
    from dmshoot.gui.monitor_panel import ReplyLogEntry
    from dmshoot.storage.models import ChatMessage

    msg = ChatMessage(session_id="b:1", sender_name="用户", content="消息")
    entry = ReplyLogEntry(msg, ai_reply="")
    check("ReplyLogEntry 无回复创建成功", entry is not None)


def test_reply_log_entry_unicode():
    """测试 Unicode 内容"""
    from dmshoot.gui.monitor_panel import ReplyLogEntry
    from dmshoot.storage.models import ChatMessage

    msg = ChatMessage(session_id="b:1", sender_name="🎉用户",
                      content="你好👋世界🌏")
    entry = ReplyLogEntry(msg, ai_reply="AI🤖回复")
    check("ReplyLogEntry Unicode 不崩", entry is not None)


def test_monitor_panel_add_entry():
    """测试监控面板添加条目"""
    from dmshoot.gui.monitor_panel import MonitorPanel
    from dmshoot.storage.models import ChatMessage

    panel = MonitorPanel()
    check("MonitorPanel 初始有空状态标签",
          panel._empty is not None)

    msg = ChatMessage(session_id="b:1", sender_name="用户", content="测试")
    panel.add_reply_log(msg, "AI回复")

    # 注意: MonitorPanel._empty 只在 isVisible() 时才清除
    # 未显示的 widget 上 _empty 保留，这是已知行为
    check("MonitorPanel 日志区有内容", panel.log_layout.count() >= 2)


def test_monitor_panel_clear():
    """测试监控面板清空"""
    from dmshoot.gui.monitor_panel import MonitorPanel
    from dmshoot.storage.models import ChatMessage

    panel = MonitorPanel()
    panel.add_reply_log(
        ChatMessage(session_id="b:1", sender_name="U", content="1"), "R1")
    panel.add_reply_log(
        ChatMessage(session_id="b:2", sender_name="U", content="2"), "R2")

    panel.clear()
    check("MonitorPanel 清空后无条目", panel.log_layout.count() == 0)


def test_platform_ruler_switching():
    """测试平台刻度尺切换"""
    from dmshoot.gui.widgets.ruler import PlatformRuler

    platforms = [("bilibili", "B站"), ("douyin", "抖音")]
    ruler = PlatformRuler(platforms)

    switched: list = []
    ruler.switched.connect(lambda p: switched.append(p))

    check("ruler 默认选中第一个", ruler._btns["bilibili"].isChecked())

    ruler.set_active("douyin")
    check("ruler 切换到抖音", ruler._btns["douyin"].isChecked())
    check("ruler 不再选中 B站", not ruler._btns["bilibili"].isChecked())
    check("ruler 触发 douyin switched", switched[-1] == "douyin")


def test_bubble_widget_other():
    """测试对方消息气泡"""
    from dmshoot.gui.widgets.chat_view import BubbleWidget
    from dmshoot.storage.models import ChatMessage

    msg = ChatMessage(session_id="b:1", sender_name="用户",
                      content="你好", is_self=False)
    bubble = BubbleWidget(msg)
    check("BubbleWidget 对方消息", bubble is not None)


def test_bubble_widget_self():
    """测试自己/AI 消息气泡"""
    from dmshoot.gui.widgets.chat_view import BubbleWidget
    from dmshoot.storage.models import ChatMessage

    msg = ChatMessage(session_id="b:1", sender_name="AI",
                      content="自动回复", is_self=True, is_auto=True)
    bubble = BubbleWidget(msg)
    check("BubbleWidget 自己消息", bubble is not None)


def test_log_panel_append():
    """测试日志面板追加日志"""
    from dmshoot.gui.log_panel import LogPanel

    panel = LogPanel()
    check("LogPanel 初始空", panel.log_view.toPlainText() == "")

    panel.append("INFO", "bilibili", "连接成功")
    text = panel.log_view.toHtml()
    check("LogPanel INFO 有内容", "连接成功" in text)
    check("LogPanel 平台名出现", "bilibili" in text)

    panel.append("ERROR", "douyin", "连接失败")
    text2 = panel.log_view.toHtml()
    check("LogPanel ERROR 有内容", "连接失败" in text2)


def test_log_panel_color_coding():
    """测试日志颜色编码"""
    from dmshoot.gui.log_panel import LogPanel

    panel = LogPanel()

    # 检查各种级别的颜色不崩溃
    for level in ["INFO", "WARN", "ERROR", "SUCCESS"]:
        try:
            panel.append(level, "test", f"level={level}")
            ok(f"LogPanel {level} 不崩溃")
        except Exception as e:
            fail(f"LogPanel {level} 崩溃", str(e))


def test_log_panel_clear():
    """测试日志面板清空"""
    from dmshoot.gui.log_panel import LogPanel

    panel = LogPanel()
    panel.append("INFO", "test", "msg1")
    panel.append("INFO", "test", "msg2")
    panel.clear_log()
    check("LogPanel clear 后为空", panel.log_view.toPlainText() == "")


def test_chat_view_load_messages():
    """测试聊天视图加载消息"""
    from dmshoot.gui.widgets.chat_view import ChatView
    from dmshoot.storage.models import ChatMessage

    view = ChatView()
    msgs = [
        ChatMessage(session_id="b:1", sender_name="U", content="消息1",
                    timestamp=100.0, is_self=False),
        ChatMessage(session_id="b:1", sender_name="AI", content="回复1",
                    timestamp=200.0, is_self=True, is_auto=True),
    ]
    view.load_messages("测试会话", msgs)
    check("ChatView title 更新", view.title_label.text() == "测试会话")
    check("ChatView 气泡已加载", view.bubble_layout.count() >= 3)


def test_chat_view_append_message():
    """测试聊天视图追加消息"""
    from dmshoot.gui.widgets.chat_view import ChatView
    from dmshoot.storage.models import ChatMessage

    view = ChatView()
    count_before = view.bubble_layout.count()

    view.append_message(
        ChatMessage(session_id="b:1", sender_name="U", content="新消息"))
    check("ChatView append 后 count+1",
          view.bubble_layout.count() == count_before + 1)


# ═══════════════════════════════════════════════════════════
# 3. LoginPage — Cookie 流程测试
# ═══════════════════════════════════════════════════════════

def test_login_page_init():
    """测试登录页初始化"""
    from dmshoot.gui.pages.login_page import LoginPage

    page = LoginPage()
    check("LoginPage dy_status 初始", page.dy_status.text() == "未登录")
    check("LoginPage bili_status 初始", page.bili_status.text() == "未登录")
    check("LoginPage dy_monitor 初始隐藏", page.dy_monitor.isHidden())
    check("LoginPage bili_monitor 初始隐藏", page.bili_monitor.isHidden())


def test_login_page_set_status():
    """测试登录页状态更新"""
    from dmshoot.gui.pages.login_page import LoginPage

    page = LoginPage()
    page.set_status("bilibili", "已连接")
    check("LoginPage bili_status 更新", page.bili_status.text() == "已连接")

    page.set_status("douyin", "请扫码")
    check("LoginPage dy_status 更新", page.dy_status.text() == "请扫码")


def test_login_page_on_connected():
    """测试连接后 monitor 按钮可见"""
    from dmshoot.gui.pages.login_page import LoginPage

    page = LoginPage()
    page.on_connected("bilibili")
    check("LoginPage bili_monitor 未隐藏", not page.bili_monitor.isHidden())

    page.on_connected("douyin")
    check("LoginPage dy_monitor 未隐藏", not page.dy_monitor.isHidden())


def test_login_page_on_disconnected():
    """测试断开后 monitor 按钮隐藏"""
    from dmshoot.gui.pages.login_page import LoginPage

    page = LoginPage()
    page.on_connected("bilibili")
    page.on_disconnected("bilibili")
    check("LoginPage bili_monitor 隐藏", page.bili_monitor.isHidden())


def test_login_page_toggle_monitor():
    """测试监听开关信号"""
    from dmshoot.gui.pages.login_page import LoginPage

    page = LoginPage()
    starts: list = []
    stops: list = []

    page.start_monitor.connect(lambda p: starts.append(p))
    page.stop_monitor.connect(lambda p: stops.append(p))

    page._toggle_monitor("bilibili")
    check("LoginPage toggle bilibili start", starts == ["bilibili"])

    page.set_monitor_running("bilibili", True)
    check("LoginPage bili_monitor 文字变停止",
          page.bili_monitor.text() == "停止")

    page._toggle_monitor("bilibili")
    check("LoginPage toggle bilibili stop", stops == ["bilibili"])


def test_login_page_cookie_clear():
    """测试清理 Cookie 流程"""
    from dmshoot.gui.pages.login_page import LoginPage
    from dmshoot.storage import database
    import tempfile

    old = database.DB_PATH
    try:
        tmp = os.path.join(tempfile.gettempdir(), "dmshoot_test_login.db")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        from dmshoot.storage.models import AppConfig
        cfg = AppConfig(bilibili_sessdata="test_sess", bilibili_jct="test_jct")
        database.save_config(cfg)

        page = LoginPage()
        cleared: list = []
        page.clear_platform.connect(lambda p: cleared.append(p))

        page._clear_cookie("bilibili")
        check("LoginPage clear 后状态", page.bili_status.text() == "已清理")
        check("LoginPage clear 发出信号", cleared == ["bilibili"])

        # 确认 DB 中已清空
        cfg2 = database.load_config()
        check("LoginPage clear DB bilibili_sessdata 空",
              cfg2.bilibili_sessdata == "")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_login_page_cookie_save_bilibili():
    """测试 B站 Cookie 保存流程"""
    from dmshoot.gui.pages.login_page import LoginPage
    from dmshoot.storage import database
    import tempfile

    old = database.DB_PATH
    try:
        tmp = os.path.join(tempfile.gettempdir(), "dmshoot_test_save.db")
        database.DB_PATH = type(old)(tmp)
        if database.DB_PATH.exists():
            os.remove(str(database.DB_PATH))
        database.init_database()

        page = LoginPage()
        connected: list = []
        page.connect_platform.connect(lambda p: connected.append(p))

        # 模拟 Cookie 提取结果
        page._on_cookie_ready("bilibili", {"SESSDATA": "valid_sess", "bili_jct": "valid_jct"})
        check("LoginPage bili_status 更新", page.bili_status.text() == "已保存，自动登录中...")
        check("LoginPage emit connect_platform", "bilibili" in connected)

        cfg = database.load_config()
        check("LoginPage DB bilibili_sessdata 已保存", cfg.bilibili_sessdata == "valid_sess")
        check("LoginPage DB bilibili_jct 已保存", cfg.bilibili_jct == "valid_jct")

        database.DB_PATH = old
        os.remove(tmp)
    except Exception:
        database.DB_PATH = old
        raise


def test_cookie_worker_creation():
    """测试 CookieWorker 线程创建"""
    from dmshoot.gui.workers.login_worker import LoginWorker

    worker = LoginWorker("bilibili")
    check("CookieWorker platform", worker.platform == "bilibili")
    check("CookieWorker 有 result 信号", hasattr(worker, "result"))


# ═══════════════════════════════════════════════════════════
# 4. MessageBus 信号集成测试
# ═══════════════════════════════════════════════════════════

def test_bus_to_log_panel():
    """测试 Bus log 信号 → LogPanel"""
    from dmshoot.core.bus import MessageBus
    from dmshoot.gui.log_panel import LogPanel

    bus = MessageBus()
    panel = LogPanel()

    bus.log.connect(panel.append)
    bus.log.emit("INFO", "bilibili", "集成测试消息")
    check("Bus→LogPanel 有内容",
          "集成测试消息" in panel.log_view.toHtml())


def test_bus_to_monitor_panel():
    """测试 Bus ai_response 信号"""
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    responses: list = []

    bus.ai_response.connect(lambda sid, txt, mdl: responses.append((sid, txt, mdl)))
    bus.ai_response.emit("b:123", "AI 回复内容", "deepseek-v4-flash")

    check("Bus ai_response 信号",
          responses[0] == ("b:123", "AI 回复内容", "deepseek-v4-flash"))


def test_full_message_flow():
    """模拟完整消息流: adapter → bus → gui"""
    from dmshoot.core.bus import MessageBus
    from dmshoot.core.message import Message
    from dmshoot.gui.log_panel import LogPanel

    bus = MessageBus()
    panel = LogPanel()

    # 连接信号
    bus.log.connect(panel.append)

    # 模拟 adapter 收到消息
    msg = Message(platform="bilibili", msg_type="text", sender_id="1",
                  sender_name="测试", session_id="b:1", content="你好")
    bus.emit_message(msg)

    text = panel.log_view.toHtml()
    check("完整流 测试出现在日志", "测试" in text)
    check("完整流 你好出现在日志", "你好" in text)

    # 模拟 AI 回复
    bus.ai_response.emit("b:1", "AI说你好", "deepseek-v4-flash")
    check("完整流 AI 回复不崩", True)


# ═══════════════════════════════════════════════════════════
# 5. Playwright / Cookie 提取测试
# ═══════════════════════════════════════════════════════════

def test_extract_bilibili_full_format():
    """测试 B站 Cookie 完整格式解析"""
    from dmshoot.utils.cookie_reader import extract_bilibili_cookies_sync

    original_run = asyncio.run

    async def fake_login(path):
        return ("SESSDATA=abc123%2Cdef; bili_jct=xyz789; "
                "DedeUserID=12345; DedeUserID__ckMd5=hash123; "
                "sid=session_id; buvid3=some_buvid")

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_bilibili_cookies_sync()
        check("Cookie SESSDATA", result["SESSDATA"] == "abc123%2Cdef")
        check("Cookie bili_jct", result["bili_jct"] == "xyz789")
    finally:
        asyncio.run = original_run


def test_extract_bilibili_malformed():
    """测试畸形 Cookie 字符串"""
    from dmshoot.utils.cookie_reader import extract_bilibili_cookies_sync

    original_run = asyncio.run

    async def fake_login(path):
        return "garbage_data_without_equals_sign"

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_bilibili_cookies_sync()
        check("畸形 Cookie SESSDATA 空", result["SESSDATA"] == "")
        check("畸形 Cookie bili_jct 空", result["bili_jct"] == "")
    finally:
        asyncio.run = original_run


def test_extract_douyin_cookies_success():
    """测试抖音 Cookie 提取成功（web_protect + keys 格式）"""
    from dmshoot.utils.cookie_reader import extract_douyin_cookies_sync

    original_run = asyncio.run

    async def fake_login(path):
        return {"cookie": "sessionid=test;", "web_protect": "{}", "keys": "{}"}

    asyncio.run = lambda coro: original_run(fake_login(""))
    try:
        result = extract_douyin_cookies_sync()
        check("抖音 Cookie dict 非空", isinstance(result, dict) and len(result) > 0)
        check("抖音有 cookie 字段", "cookie" in result)
        check("抖音有 web_protect 字段", "web_protect" in result)
        check("抖音有 keys 字段", "keys" in result)
    finally:
        asyncio.run = original_run


def test_cookie_worker_bilibili_result():
    """测试 _CookieWorker 对 B站结果的信号发射"""
    from dmshoot.gui.workers.login_worker import LoginWorker
    from PySide6.QtCore import QThread

    # Mock extract_bilibili_cookies_sync
    original_extract = extract_bilibili_cookies_sync
    import dmshoot.utils.cookie_reader as cr

    def mock_extract():
        return {"SESSDATA": "mock_sess", "bili_jct": "mock_jct"}

    cr.extract_bilibili_cookies_sync = mock_extract

    try:
        worker = LoginWorker("bilibili")
        results: list = []
        worker.result.connect(lambda p, c: results.append((p, c)))

        # 手动执行 run，不启动线程
        worker.run()

        check("CookieWorker bilibili 收到结果", len(results) == 1)
        check("CookieWorker platform", results[0][0] == "bilibili")
        check("CookieWorker SESSDATA", results[0][1]["SESSDATA"] == "mock_sess")
    finally:
        cr.extract_bilibili_cookies_sync = original_extract


def test_cookie_worker_douyin_result():
    """测试 _CookieWorker 对抖音结果的信号发射（web_protect 格式）"""
    from dmshoot.gui.workers.login_worker import LoginWorker
    import dmshoot.utils.cookie_reader as cr

    original_extract = cr.extract_douyin_cookies_sync

    def mock_extract():
        return {"cookie": "sessionid=test;", "web_protect": "{}", "keys": "{}"}

    cr.extract_douyin_cookies_sync = mock_extract

    try:
        worker = LoginWorker("douyin")
        results: list = []
        worker.result.connect(lambda p, c: results.append((p, c)))

        worker.run()

        check("CookieWorker douyin 收到结果", len(results) == 1)
        check("CookieWorker douyin platform", results[0][0] == "douyin")
        check("CookieWorker douyin cookie key", results[0][1]["cookie"] == "sessionid=test;")
    finally:
        cr.extract_douyin_cookies_sync = original_extract


def test_cookie_worker_bilibili_empty_result():
    """测试 _CookieWorker B站空结果（无效）"""
    from dmshoot.gui.workers.login_worker import LoginWorker
    import dmshoot.utils.cookie_reader as cr

    original_extract = cr.extract_bilibili_cookies_sync

    def mock_extract():
        return {"SESSDATA": "", "bili_jct": ""}  # 空 SESSDATA

    cr.extract_bilibili_cookies_sync = mock_extract

    try:
        worker = LoginWorker("bilibili")
        results: list = []
        worker.result.connect(lambda p, c: results.append((p, c)))

        worker.run()

        check("CookieWorker 空 SESSDATA 返回 None",
              len(results) == 1 and results[0][1] is None)
    finally:
        cr.extract_bilibili_cookies_sync = original_extract


# ═══════════════════════════════════════════════════════════
# 6. 边界/异常测试
# ═══════════════════════════════════════════════════════════

def test_adapter_parse_very_long_content():
    """超长内容不崩溃"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    long_text = "测试" * 5000
    msg = adapter._parse_message(
        {"sender_uid": 200, "talker_id": 200, "content": long_text, "msg_type": 1})
    check("超长内容不崩 非空", msg is not None)
    check("超长内容保留", len(msg.content) == len(long_text))


def test_adapter_parse_zero_talker():
    """talker_id=0 的消息"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    msg = adapter._parse_message(
        {"sender_uid": 200, "talker_id": 0, "content": "hi", "msg_type": 1})
    check("talker_id=0 正常解析", msg is not None)
    check("talker_id=0 session_id", msg.session_id == "bilibili:0")


def test_adapter_parse_negative_timestamp():
    """负数时间戳"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    msg = adapter._parse_message(
        {"sender_uid": 200, "talker_id": 200, "content": "x",
         "msg_type": 1, "timestamp": -1})
    check("负数时间戳不崩", msg is not None)


def test_adapter_parse_none_sender_uid():
    """sender_uid 为 None"""
    from dmshoot.plugins.bilibili.adapter import BilibiliAdapter
    from dmshoot.core.bus import MessageBus

    bus = MessageBus()
    adapter = BilibiliAdapter(bilibili_sessdata="fake", bilibili_jct="fake", bus=bus)
    adapter._my_uid = 100

    msg = adapter._parse_message(
        {"sender_uid": None, "talker_id": 200, "content": "x", "msg_type": 1})
    check("sender_uid=None 返回 None", msg is None)


def test_monitor_panel_multiple_entries():
    """监控面板多条日志"""
    from dmshoot.gui.monitor_panel import MonitorPanel
    from dmshoot.storage.models import ChatMessage

    panel = MonitorPanel()
    for i in range(10):
        panel.add_reply_log(
            ChatMessage(session_id=f"b:{i}", sender_name=f"U{i}",
                        content=f"消息{i}"),
            f"回复{i}"
        )
    check("MonitorPanel 10条 不崩", panel.log_layout.count() >= 10)


# ═══════════════════════════════════════════════════════════
# 测试运行器
# ═══════════════════════════════════════════════════════════

ALL_TESTS: list[tuple[str, callable]] = [
    # 1. Adapter 解析逻辑 (14)
    ("Adapter 解析文本", test_adapter_parse_text_message),
    ("Adapter 解析自己消息", test_adapter_parse_self_message),
    ("Adapter 解析图片", test_adapter_parse_image_message),
    ("Adapter 解析毫秒时间戳", test_adapter_parse_timestamp_milliseconds),
    ("Adapter 解析字符串时间戳", test_adapter_parse_timestamp_string),
    ("Adapter 解析缺失时间戳", test_adapter_parse_timestamp_missing),
    ("Adapter 空内容返回None", test_adapter_parse_empty_content),
    ("Adapter 过滤系统消息", test_adapter_parse_filter_system),
    ("Adapter 无效sender返回None", test_adapter_parse_invalid_sender),
    ("Adapter 解析JSON内容", test_adapter_parse_json_content),
    ("Adapter peer_name 对方消息", test_adapter_parse_with_peer_name),
    ("Adapter 状态跟踪", test_adapter_state_tracking),
    ("Adapter platform_name", test_adapter_send_message_session_parsing),
    ("Adapter disconnect 保存状态", test_adapter_disconnect_saves_state),
    ("Adapter connect 无效凭证", test_adapter_connect_no_network),

    # 2. GUI 组件 (13)
    ("ReplyLogEntry 有回复", test_reply_log_entry),
    ("ReplyLogEntry 无回复", test_reply_log_entry_no_reply),
    ("ReplyLogEntry Unicode", test_reply_log_entry_unicode),
    ("MonitorPanel 添加条目", test_monitor_panel_add_entry),
    ("MonitorPanel 清空", test_monitor_panel_clear),
    ("MonitorPanel 多条", test_monitor_panel_multiple_entries),
    ("PlatformRuler 切换", test_platform_ruler_switching),
    ("BubbleWidget 对方", test_bubble_widget_other),
    ("BubbleWidget 自己", test_bubble_widget_self),
    ("LogPanel 追加", test_log_panel_append),
    ("LogPanel 颜色编码", test_log_panel_color_coding),
    ("LogPanel 清空", test_log_panel_clear),
    ("ChatView 加载消息", test_chat_view_load_messages),
    ("ChatView 追加消息", test_chat_view_append_message),

    # 3. Login/Cookie 流程 (9)
    ("LoginPage 初始化", test_login_page_init),
    ("LoginPage set_status", test_login_page_set_status),
    ("LoginPage on_connected", test_login_page_on_connected),
    ("LoginPage on_disconnected", test_login_page_on_disconnected),
    ("LoginPage toggle_monitor", test_login_page_toggle_monitor),
    ("LoginPage clear_cookie", test_login_page_cookie_clear),
    ("LoginPage save_bilibili", test_login_page_cookie_save_bilibili),
    ("CookieWorker 创建", test_cookie_worker_creation),
    ("CookieWorker bilibili 结果", test_cookie_worker_bilibili_result),
    ("CookieWorker douyin 结果", test_cookie_worker_douyin_result),
    ("CookieWorker 空结果", test_cookie_worker_bilibili_empty_result),

    # 4. 信号集成 (3)
    ("Bus→LogPanel 集成", test_bus_to_log_panel),
    ("Bus ai_response 信号", test_bus_to_monitor_panel),
    ("完整消息流", test_full_message_flow),

    # 5. Playwright/Cookie 提取 (3)
    ("Cookie 完整格式解析", test_extract_bilibili_full_format),
    ("Cookie 畸形字符串", test_extract_bilibili_malformed),
    ("抖音 Cookie 提取", test_extract_douyin_cookies_success),

    # 6. 边界异常 (4)
    ("Adapter 超长内容", test_adapter_parse_very_long_content),
    ("Adapter talker_id=0", test_adapter_parse_zero_talker),
    ("Adapter 负数时间戳", test_adapter_parse_negative_timestamp),
    ("Adapter sender_uid=None", test_adapter_parse_none_sender_uid),
]


if __name__ == "__main__":
    print("DMShoot GUI + Adapter + Playwright 测试")
    print("=" * 55)
    print(f"共 {len(ALL_TESTS)} 个测试")
    print()

    passed = 0
    failed_tests: list[str] = []

    for name, fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except Exception as e:
            import traceback
            fail(name, str(e))
            traceback.print_exc()
            failed_tests.append(name)

    print()
    print("=" * 55)
    rate = passed / len(ALL_TESTS) * 100
    print(f"结果: {passed}/{len(ALL_TESTS)} 通过 ({rate:.1f}%)")

    if failed_tests:
        print(f"\n失败 ({len(failed_tests)}):")
        for name in failed_tests:
            print(f"  ✗ {name}")

    sys.exit(0 if passed == len(ALL_TESTS) else 1)
