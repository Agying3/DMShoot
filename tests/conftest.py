"""DMShoot pytest 全局配置 — 单例隔离 + 临时数据库 + 截图"""

import pytest
import sys
import os
import tempfile
import uuid
from pathlib import Path

# 项目根路径
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))


# ═══════════════════════════════════════════════════════════
# PySide6 / pytest-qt 条件加载
# ═══════════════════════════════════════════════════════════

# 默认禁用 pytest-qt（conda 环境无 PySide6）
# GUI 测试用: pytest tests/ -m "gui" -p pytestqt
_HAS_PYSIDE6 = False
try:
    from PySide6.QtWidgets import QApplication
    _HAS_PYSIDE6 = True
except ImportError:
    pass


def pytest_configure(config):
    """仅在 PySide6 可用时激活 pytest-qt"""
    if not _HAS_PYSIDE6:
        return
    # 添加跳过标记：无 PySide6 时自动跳过 gui 测试
    config.addinivalue_line(
        "markers",
        "gui_skip: auto-skipped when PySide6 unavailable"
    )


def pytest_collection_modifyitems(config, items):
    """无 PySide6 时自动跳过标记为 gui 的测试"""
    if _HAS_PYSIDE6:
        return
    skip_gui = pytest.mark.skip(reason="PySide6 未安装，跳过 GUI 测试")
    for item in items:
        if "gui" in item.keywords:
            item.add_marker(skip_gui)


# ═══════════════════════════════════════════════════════════
# 单例重置 — 每个测试前后自动清理全局状态
# ═══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_singletons():
    """每个测试前重置所有单例，避免测试间状态污染"""
    # 先清理可能残留的单例
    _cleanup_modules()

    yield

    # 测试后再次清理
    _cleanup_modules()


def _cleanup_modules():
    """清理模块级单例状态"""
    singletons = {
        "dmshoot.core.bus": ["MessageBus"],
        "dmshoot.core.concurrency": ["ConcurrencyManager"],
        "dmshoot.core.perf_monitor": ["PerfMonitor", "_monitor_instance"],
        "dmshoot.core.go_bridge": ["_bridge"],
        "dmshoot.core.rate_limiter": ["_limiters"],
        "dmshoot.ai.backend": ["_ai_instance"],
    }

    for module_name, attrs in singletons.items():
        try:
            mod = sys.modules.get(module_name)
            if mod is None:
                continue
            for attr in attrs:
                obj = getattr(mod, attr, None)
                if obj is None:
                    continue
                # 调用 reset() 如果有的话
                reset_method = getattr(obj, "reset", None) or getattr(obj, "reset_instance", None)
                if reset_method:
                    try:
                        reset_method()
                    except Exception:
                        pass
                # 如果是个实例对象且有 shutdown
                elif hasattr(obj, "shutdown"):
                    try:
                        obj.shutdown(wait=False)
                    except Exception:
                        pass
                # 字典类直接清空
                if isinstance(obj, dict):
                    obj.clear()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 临时数据库 — 测试隔离
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库，测试后销毁"""
    import dmshoot.storage.database as dbmod

    old_path = dbmod.DB_PATH
    tmp_name = f"dmshoot_pytest_{uuid.uuid4().hex[:8]}.db"
    tmp_path = Path(tempfile.gettempdir()) / tmp_name

    try:
        dbmod.DB_PATH = tmp_path
        dbmod._conn = None
        dbmod._get_conn()  # 触发创建
        dbmod.init_database()
        yield tmp_path
    finally:
        # 恢复原路径
        dbmod.DB_PATH = old_path
        dbmod._conn = None
        # 清理临时文件
        for ext in ["", "-wal", "-shm"]:
            f = Path(str(tmp_path) + ext)
            if f.exists():
                try:
                    os.remove(str(f))
                except Exception:
                    pass


@pytest.fixture
def db_session(temp_db):
    """提供临时数据库的读写访问"""
    from dmshoot.storage import database as dbmod
    return dbmod


# ═══════════════════════════════════════════════════════════
# 截图工具 — 失败时自动截图
# ═══════════════════════════════════════════════════════════

SCREENSHOT_DIR = PROJECT / "reports" / "screenshots"


def _capture_screenshot(test_name: str):
    """捕获当前 PySide6 活跃窗口截图（仅 PySide6 可用时）"""
    if not _HAS_PYSIDE6:
        return
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        for widget in app.topLevelWidgets():
            if widget.isVisible():
                SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                fname = f"{test_name}_{uuid.uuid4().hex[:6]}.png"
                fpath = SCREENSHOT_DIR / fname
                pixmap = widget.grab()
                pixmap.save(str(fpath))
                break
    except Exception:
        pass


@pytest.fixture
def screenshot(request):
    """在测试失败时自动截图当前活跃窗口"""
    yield
    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        _capture_screenshot(request.node.name)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook: 在测试执行后记录结果，供 screenshot fixture 使用"""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


# ═══════════════════════════════════════════════════════════
# Qt 配置
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication — 仅 PySide6 可用时"""
    if not _HAS_PYSIDE6:
        pytest.skip("PySide6 未安装")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseSoftwareOpenGL)
    yield app


# ═══════════════════════════════════════════════════════════
# Mock 辅助
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def mock_config():
    """提供带假 cookie 的 AppConfig"""
    from dmshoot.storage.models import AppConfig

    return AppConfig(
        api_key="sk-test-mock",
        model="deepseek-v4-flash",
        douyin_enabled=False,
        bilibili_enabled=True,
        bilibili_sessdata="mock_sessdata",
        bilibili_jct="mock_jct",
        bilibili_buvid3="mock_buvid3",
        bilibili_buvid4="mock_buvid4",
        bilibili_dedeuserid="mock_dedeuserid",
        bilibili_ac_time_value="mock_ac_time",
    )


@pytest.fixture
def mock_bilibili_api(monkeypatch):
    """Mock bilibili-api 避免真实网络请求"""
    import bilibili_api.session as b_sess

    async def mock_get_sessions(*args, **kwargs):
        return {"session_list": [
            {"talker_id": 100, "unread_count": 1, "name": "TestUser",
             "account_info": "{'name': 'TestUser', 'pic_url': ''}", "system_msg_type": 0},
            {"talker_id": 200, "unread_count": 0, "name": "User2",
             "account_info": "{'name': 'User2', 'pic_url': ''}", "system_msg_type": 0},
        ]}

    async def mock_fetch_msgs(talker_id, *args, **kwargs):
        return {"messages": [
            {"sender_uid": talker_id, "content": f"msg_from_{talker_id}",
             "msg_seqno": 1, "timestamp": 1718000000, "talker_id": talker_id, "msg_type": 1}
        ]}

    monkeypatch.setattr(b_sess, "get_sessions", mock_get_sessions)
    monkeypatch.setattr(b_sess, "fetch_session_msgs", mock_fetch_msgs)

    # Also mock sync versions for send_message
    try:
        import bilibili_api.sync as b_sync
        monkeypatch.setattr(b_sess, "send_msg", lambda *a, **kw: None)
    except ImportError:
        pass
