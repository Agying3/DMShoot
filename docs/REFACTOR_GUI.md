# DMShoot GUI 重构拆分方案

**目标**: `main_window.py` 从 1000+ 行减到 ~300 行，大类拆小文件，重复逻辑提取

---

## 一、5 个 Widget 类 → 独立文件（0 风险，纯搬迁）

每个类保持内部逻辑完全不动，只改 import 语句。

| 当前位置 (main_window.py) | 行数 | 搬到 | 新 import |
|---|---|---|---|
| `PinButton` (43-137) | 95 | `gui/widgets/pin_button.py` | `from dmshoot.gui.widgets.pin_button import PinButton` |
| `RotatingGear` (140-186) | 47 | `gui/widgets/rotating_gear.py` | `from dmshoot.gui.widgets.rotating_gear import RotatingGear` |
| `TitleBar` (189-258) | 70 | `gui/widgets/title_bar.py` | `from dmshoot.gui.widgets.title_bar import TitleBar` |
| `ShadowContainer` (263-284) | 22 | `gui/widgets/shadow_container.py` | `from dmshoot.gui.widgets.shadow_container import ShadowContainer` |
| `MarkdownViewer` (289-387) | 99 | `gui/widgets/markdown_viewer.py` | `from dmshoot.gui.widgets.markdown_viewer import MarkdownViewer` |

**操作**: 每个类 Ctrl+X → 新文件保持完全一致 → 旧文件加 import。不改一行逻辑。

---

## 二、平台名常量 → 集中定义（0 风险，纯改引用）

当前 `{"douyin": "抖音", "bilibili": "B站", "kuaishou": "快手"}` 在 6 处重复。

### 新建 `dmshoot/core/platforms.py`

```python
"""平台常量 — 加平台只改这一个文件"""

PLATFORM_NAMES = {
    "douyin": "抖音",
    "bilibili": "B站",
    "kuaishou": "快手",
}

# 平台 → 启动所需 cookie/config key
PLATFORM_COOKIE_KEYS = {
    "douyin": "douyin_cookie",
    "bilibili": "bilibili_sessdata",
    "kuaishou": "ks_cookie",
}

# 平台 → 启用开关 key
PLATFORM_ENABLED_KEYS = {
    "douyin": "douyin_enabled",
    "bilibili": "bilibili_enabled",
    "kuaishou": "ks_enabled",
}

# 各平台的状态文件名（清理 cookie 时删除）
PLATFORM_STATE_FILES = {
    "douyin": ["data/douyin_state.json"],
    "bilibili": ["data/bilibili_state.json"],
    "kuaishou": ["data/kuaishou_state.json", "data/kuaishou_cookie.json"],
}

# 不需要 Playwright 验证的平台（只要有 cookie 即信任）
TRUST_COOKIE_PLATFORMS = frozenset({"douyin", "kuaishou"})

# Web 端不支持私信的平台（启动时给警告）
IM_UNAVAILABLE_PLATFORMS = frozenset({"kuaishou"})

def get_name(platform: str) -> str:
    return PLATFORM_NAMES.get(platform, platform)

def get_cookie(config, platform: str) -> str:
    key = PLATFORM_COOKIE_KEYS.get(platform, "")
    return getattr(config, key, "") if key else ""

def is_enabled(config, platform: str) -> bool:
    key = PLATFORM_ENABLED_KEYS.get(platform, "")
    return getattr(config, key, False) if key else False
```

### 改动范围

`main_window.py` 中下列方法改引用，每个改 1 行:

| 方法 | 原来 | 改为 |
|------|------|------|
| `_verify_saved:682` | `{"douyin": "抖音"...}.get(...)` | `get_name(platform)` |
| `_connect_platform:709` | 同上 | 同上 |
| `_start_adapter_from_ui:798` | 同上 | 同上 |
| `_stop_adapter_from_ui:809` | 同上 | 同上 |
| `_on_clear_platform:839` | 同上 | 同上 |
| `_on_platform_status:881` | 同上 | 同上 |
| 三处 enabled dict | `{"douyin": self.config.douyin_enabled...}` | `is_enabled(self.config, platform)` |
| `_start_adapter_from_ui:791` | `{"douyin": self.config.douyin_cookie...}` | `get_cookie(self.config, platform)` |
| `_on_clear_platform:825` | `state_files = {...}` | `PLATFORM_STATE_FILES.get(platform, [])` |

共省 ~40 行重复代码。

---

## 三、平台管理逻辑 → `core/adapter_manager.py`

`MainWindow` 中与适配器生命周期相关的 8 个方法提取出来。

### 新建 `dmshoot/core/adapter_manager.py`

```
class AdapterManager:
    """适配器启动/停止/验证生命周期管理"""
    
    def __init__(self, bus, plugins, config_getter, on_started, on_stopped)
    
    # ── 从 MainWindow 移入 ──
    start_adapter(platform)          # 原 _start_adapter (line 846)
    stop_adapter(platform)           # 原 _stop_adapter_from_ui (line 803)
    start_from_ui(platform)          # 原 _start_adapter_from_ui (line 789)
    verify_saved(platform)           # 原 _verify_saved (line 680)
    auto_login()                     # 原 _auto_login (line 696)
    run_async_verify(...)            # 原 _run_async_verify (line 729)
    on_clear_platform(platform)      # 原 _on_clear_platform (line 814)
    stop_all()                       # 原 _stop_adapters (line 873)
    
    # ── 状态查询 ──
    is_running(platform) -> bool
    running_platforms() -> list[str]
```

### MainWindow 中对应的变化

```python
# __init__ 中:
self.adapter_mgr = AdapterManager(
    self.bus, self.plugins,
    config_getter=lambda: self.config,
    on_started=self._on_adapter_started,   # 原来散落在 _start_adapter 的 UI 更新
    on_stopped=self._on_adapter_stopped,
)

# _start_adapter_from_ui → self.adapter_mgr.start_from_ui(platform)
# _auto_login → self.adapter_mgr.auto_login()
# ...以此类推
```

MainWindow 只保留 UI 回调（`_on_adapter_started`、`_on_adapter_stopped`），不再碰适配器启停细节。

---

## 四、消息处理流程 → `core/message_handler.py`

`_on_new_message` + `_call_ai` + `_on_ai_response` 三个方法提取。

### 新建 `dmshoot/core/message_handler.py`

```
class MessageHandler:
    """消息 → DB → AI → 回复 → 平台发送 统一编排"""
    
    def __init__(self, bus, config_getter, on_reply_sent)
    
    handle_new_message(msg)           # 原 _on_new_message (line 892)
    _call_ai(msg)                     # 原 _call_ai (line 944)
    _on_ai_reply(session_id, text)    # 原 _on_ai_response (line 963)
```

### 额外收益

- `_AIThread` 类可以提到模块级别，不再是每调用一次动态建类
- AI 回复的 `<msg>` 解析、DB 存储、平台发送三段逻辑可以各自独立测试

---

## 五、函数内的类提到模块级

### `_AIThread` → `gui/workers/ai_worker.py`

```python
# 从 _call_ai() 内部移到独立文件，只建一次类
class AIWorker(QThread):
    done = QtSignal(str, str)       # session_id, reply_text
    
    def __init__(self, ai, msg, parent=None):
        super().__init__(parent)
        self._ai = ai
        self._msg = msg
    
    def run(self):
        ...
```

### `_VerifyWorker` → `gui/workers/verify_worker.py`

```python
class VerifyWorker(QThread):
    result = QtSignal(bool, str)
    
    def __init__(self, plugins, platform, cookie, bili_params, parent=None):
        ...
```

---

## 六、杂项修复

| 问题 | 改法 |
|------|------|
| `TitleBar` 三处 `__import__("PySide6.QtCore")` | 改为 `Signal`（文件顶部已有导入） |
| `__import__("time").time()` 三处 | 顶部加 `import time`，改为 `time.time()` |
| `database._get_conn()` 穿透 | 在 `database.py` 加公共方法 `update_session_last(pid, text, ts)` |
| 2 处 `from dmshoot.core.concurrency import ConcurrencyManager` | closeEvent 和 _tick_perf 各导一次，提到顶部 |

---

## 执行顺序（从低风险到高收益）

| 步骤 | 内容 | 改动行数 | 风险 |
|------|------|---------|------|
| 1 | 提取 5 个 Widget 类到独立文件 | 0 逻辑变化 | 极低 |
| 2 | 建 `platforms.py` + 改 6 处引用 | ~40 行省 | 极低 |
| 3 | TitleBar 信号改 `Signal`、加 `import time`、`database` 加公共方法 | 3 处各 1 行 | 极低 |
| 4 | 提取 `AdapterManager` | ~200 行移动 | 低 |
| 5 | 提取 `MessageHandler` | ~150 行移动 | 中 |
| 6 | `_AIThread` / `_VerifyWorker` 移出函数 | 60 行移动 + 调引用 | 中 |

---

## 最终效果

```
重构前:
  main_window.py  1000+行
    ├── 5 个 Widget 类
    ├── 6 个重复 map
    ├── 2 个内嵌 QThread 类
    ├── 8 个平台管理方法
    ├── 3 个消息处理方法
    └── 多处 __import__ 和私有 API 穿透

重构后:
  main_window.py  ~250行  信号路由 + 页面导航
  gui/widgets/    +5 文件  各 widget
  core/           +3 文件  platforms.py / adapter_manager.py / message_handler.py
  gui/workers/    +2 文件  ai_worker.py / verify_worker.py
```
