# DMShoot Bug 审查报告

**审查日期**: 2026-06-05  
**审查范围**: 全部 44 个 Python 源文件  

---

## 严重程度说明

| 等级 | 含义 |
|------|------|
| 🔴 高 | 运行期可能崩溃/数据错误/逻辑错误，建议尽快修复 |
| 🟡 中 | 封装破坏/资源泄漏/性能退化，中期修复 |
| 🟢 低 | 代码异味/死代码/风格问题，低优先级 |

---

## 🔴 高危 bug（6 个）

### BUG #1 — AI 上下文重复注入（每次新消息被加两次）

**文件**: `dmshoot/ai/backend.py:83-93`  
**根因**: `_get_or_create_context()` 从 DB 加载历史时包含了刚存进去的**当前消息**，然后 `chat()` 又 `ctx.append` 了一遍。

```
消息流:
1. _on_new_message → save_message(msg) → 当前消息已写入 DB
2. _call_ai → handle_message → chat(msg)
3. chat() 内部:
   a. _get_or_create_context() → 从 DB 加载历史（含当前消息！）
   b. ctx.append(msg) → 又加了一遍当前消息！
```

**影响**: 每条用户消息在 AI 上下文中出现两次，导致 token 浪费、上下文容易溢出、AI 回复质量下降。

**修复建议**:
```python
# backend.py chat() 方法中，检查最后一条是否与当前消息重复
async def chat(self, session_id, user_message, sender_name="用户"):
    ctx = self._get_or_create_context(session_id)
    # 避免重复：如果 DB 最后一条就是当前消息，不再追加
    if not ctx or ctx[-1].get("content") != user_message:
        ctx.append({"role": "user", "content": user_message})
    ...
```

---

### BUG #2 — `sender_name` 被设为 cookie 前缀

**文件**: `dmshoot/utils/douyin_msg_sync.py:85`  
**代码**:
```python
sender_name=peer_name if not is_self else config.douyin_cookie[:10],
```

**影响**: 自己发的消息在通讯录中显示为 Cookie 前 10 个字符（如 `"sessionid="`），严重泄露 Cookie 信息。

**修复建议**: 使用 `_my_name` 或 `"我"` 代替 `config.douyin_cookie[:10]`。

---

### BUG #3 — `generate_csrf_token()` 使用未定义的 `logger`

**文件**: `dmshoot/utils/douyin_sdk.py:181`  
**代码**:
```python
except Exception as e:
    logger.warning(f"CSRF token 获取失败: {e}")  # ← logger 未定义！
```

**影响**: 当抖音 CSRF token 获取失败时，程序会抛出 `NameError: name 'logger' is not defined`，覆盖原始异常，可能导致适配器崩溃。

**修复建议**: 在模块顶部添加 `logger = get_logger(__name__)`，或改为 `import logging; logging.getLogger(__name__).warning(...)`。

---

### BUG #4 — `_get_conn()` 存在竞态条件（可能泄漏连接）

**文件**: `dmshoot/storage/database.py:30-37`  
**代码**:
```python
def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:          # 线程A检查: None ✓
        _conn = sqlite3.connect(...)  # 线程B也检查: None ✓ → 两个连接！
        _conn.row_factory = ...
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn
```

**影响**: 多线程同时首次调用时，可能创建两个 SQLite 连接，一个泄漏。虽然 `_lock` 保护写操作，但 `_get_conn()` 本身不使用锁。

**修复建议**:
```python
def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:  # 双重检查
                _conn = sqlite3.connect(...)
                ...
    return _conn
```

---

### BUG #5 — 去重索引在并发初始化时可能丢失

**文件**: `dmshoot/storage/database.py:113-117`  
**代码**:
```python
cur.execute("DROP INDEX IF EXISTS idx_messages_dedup")  # 先删
cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dedup ...""")  # 后建
```

**影响**: 在 `DROP` 和 `CREATE` 之间没有事务包裹，如果此时有新消息写入，该消息不会被唯一索引约束。当前 `init_database()` 只在启动时调用一次，实际影响小，但防御性不足。

**修复建议**: 使用 `CREATE UNIQUE INDEX IF NOT EXISTS` 直接创建（不用先 DROP），或者判断索引定义是否有变化再决定是否重建。

---

### BUG #6 — `_stop_adapter_from_ui` 在原始 Python 线程中操作 QThread

**文件**: `dmshoot/gui/main_window.py:512-513`  
**代码**:
```python
import threading
threading.Thread(target=adapter.stop, daemon=True).start()
```

`adapter.stop()` 内部调用 `self.quit()` + `self.wait(3000)` + `self.terminate()`。这些是 QThread 的方法，在非 Qt 线程中调用可能不安全。

**影响**: 可能导致线程管理混乱、`wait()` 返回不正确、`terminate()` 在错误的线程上下文中执行。

**修复建议**: 直接用 QTimer 或 `QThread.finished.connect(adapter.deleteLater)` 管理生命周期：
```python
adapter.stop()  # 直接调用即可，stop() 内部有 wait(3000) 并已经在子线程 run()
# 或者用 finished 信号异步清理
adapter.finished.connect(adapter.deleteLater)
adapter.stop()
```

---

## 🟡 中危 bug（7 个）

### BUG #7 — `_on_ai_response` 穿透私有 API + 绕过写锁

**文件**: `dmshoot/gui/main_window.py:640-645`  
**代码**:
```python
conn = database._get_conn()  # 访问私有方法
conn.execute("""UPDATE sessions SET ...""", (...))
conn.commit()  # 没有用 _lock 保护！
```

**影响**: 直接绕过 `database` 模块的 `_lock`，与 `upsert_session()` 等函数形成并发写入冲突。

**修复建议**: 在 `database.py` 中暴露一个 `update_session_last_message()` 公共方法，内部正确使用 `_lock`。

---

### BUG #8 — B站适配器 `_debug()` 在轮询循环中高频写文件

**文件**: `dmshoot/plugins/bilibili/adapter.py:36-42`  
**代码**:
```python
def _debug(msg: str):
    with open(str(debug_path), "a", encoding="utf-8") as f:
        f.write(f"[...] {msg}\n")
```

**影响**: 每条消息、每个异常都写磁盘。在线程池中大量并发时产生大量磁盘 I/O。长期运行后 `adapter_debug.txt` 无限制增长。

**修复建议**: 改为 `logger.debug()` 走控制台；或加文件大小上限 + rotate。

---

### BUG #9 — 抖音 `_patch_imports()` 在每次 `send_message()` 时重复执行

**文件**: `dmshoot/plugins/douyin/adapter.py:112-114`  
**代码**:
```python
def send_message(self, session_id, text):
    from dmshoot.utils.douyin_sdk import _patch_imports
    _patch_imports()  # 每次发送都重新创建假模块、重新导入 SDK！
```

**影响**: 每次发送消息时重建 `sys.modules["utils.dy_util"]`，并重新 `from builder.auth import DouyinAuth` 等导入。这在高频发送时浪费 CPU，且在并发中 `sys.modules` 操作不是完全线程安全的。

**修复建议**: 将 `_patch_imports()` 移到适配器的 `connect()` 方法中，只执行一次。

---

### BUG #10 — `_AvatarLoader.quit()` 调用无效果 + 阻塞 UI 线程

**文件**: `dmshoot/gui/widgets/contact.py:178-179, 263-264`  
**代码**:
```python
# closeEvent
self._loader.quit()         # QThread 没有事件循环，quit() 无效果
self._loader.wait(2000)     # 阻塞 GUI 线程 2 秒！

# _load_avatars
self._loader.quit()         # 同上
self._loader.wait(1000)     # 阻塞 GUI 线程 1 秒
```

**影响**: 关闭窗口或重新加载头像时，UI 冻结 1~2 秒。

**修复建议**: `_AvatarLoader` 继承 `QThread` 但没有 event loop，应该改继承 `QObject` + `moveToThread`，或使用 `requestInterruption()` + `isInterruptionRequested()` 检查模式。

---

### BUG #11 — `__index_hint` 属性从头到尾未设置

**文件**: `dmshoot/gui/widgets/contact.py:190`  
**代码**:
```python
idx = self.list.row(w) if hasattr(w, '__index_hint') else -1
```

**影响**: `__index_hint` 从未在 `ContactItem` 或任何代码中赋值，`hasattr` 永远返回 `False`，始终用 O(n) 遍历。这是一个"幽灵优化"——代码写了但从未生效。

**修复建议**: 删除 `__index_hint` 逻辑，或者在设置 item widget 时存储 index：
```python
item.setData(Qt.UserRole, self.list.count() - 1)  # 存储 row index
```

---

### BUG #12 — `unread_count` 永不为正（未读角标永远不显示）

**文件**: `dmshoot/gui/main_window.py:581-589` + `dmshoot/gui/widgets/contact.py:86-91`  

**根因**: `_on_new_message()` 创建 `SessionRecord` 时使用默认值 `unread_count=0`，然后 `upsert_session` 将其更新为 0，覆盖已有的计数值。

**影响**: 通讯录中的未读角标功能完全失效。

**修复建议**: `upsert_session` 的 `ON CONFLICT DO UPDATE` 中，`unread_count` 应当只在消息不是"已读"状态时递增，或者使用 `unread_count = sessions.unread_count + 1`（仅当非自身消息）。

---

### BUG #13 — `douyin_msg_parser.py` 与 `proto_msg_parser.py` 功能重复

**文件**: `dmshoot/utils/douyin_msg_parser.py` vs `dmshoot/utils/proto_msg_parser.py`

**影响**: 两个文件功能重叠（protobuf 消息提取）。`douyin_msg_parser.py` 的 `extract_all_messages()` 仅被已弃用的 `douyin_msg_sync.py` 引用。代码维护负担，容易在修复一个时忘记另一个。

**修复建议**: 确认 `douyin_msg_parser.py` + `douyin_msg_sync.py` 是否还在使用；若已废弃，清理掉。

---

## 🟢 低危问题（9 个）

### BUG #14 — TitleBar 使用 `__import__()` 动态定义 Signal（3 次）

**文件**: `dmshoot/gui/main_window.py:84-86`

顶部已导入 `from PySide6.QtCore import Signal as QtSignal`，却在类体内用 `__import__()` 重新导入。代码不清晰且不必要的性能开销。

---

### BUG #15 — `adapter.py:79` 重复 `import time as _time`

**文件**: `dmshoot/core/adapter.py:79`  
顶部第 3 行已有 `import time`，`_poll_loop()` 内又 `import time as _time`。冗余但 Python 缓存了 import，性能影响可忽略。

---

### BUG #16 — `concurrency.py:34` 导入未使用的 `deque`

**文件**: `dmshoot/core/concurrency.py:34`  
`from collections import deque, defaultdict` — `deque` 从未使用。

---

### BUG #17 — `database.py:46` 初始化创建临时连接

**文件**: `dmshoot/storage/database.py:46`  
`init_database()` 创建独立连接做建表+迁移，关闭后再由 `_get_conn()` 创建持久连接。这在 WAL 模式下一般安全，但两个连接的生命周期有短暂重叠（第 122 行 `_get_conn()` 在 `conn.close()` 之后调用），更干净的写法是让 `init_database` 复用 `_get_conn()`。

---

### BUG #18 — `_bili_running`/`_dy_running`/`_xhs_running` 三个独立布尔

**文件**: `dmshoot/gui/pages/login_page.py`（Explore agent 报告）

三个平台运行状态用三个独立布尔变量，应合并为一个 `dict[str, bool]`，减少重复代码。

---

### BUG #19 — `chat_view.py` 硬编码滚动阈值 60px

**文件**: `dmshoot/gui/widgets/chat_view.py`

`_smart_scroll()` 用硬编码 60px 判断用户是否在底部。应改为类常量或可配置项。

---

### BUG #20 — `settings_dialog.py` 最小尺寸对小屏不友好

**文件**: `dmshoot/gui/settings_dialog.py`

`setMinimumSize(550, 480)` 对 1366x768 及以下分辨率不够友好。

---

### BUG #21 — `message.py` 缺少 `from_xhs()` 工厂方法

**文件**: `dmshoot/core/message.py`

有 `from_douyin()`、`from_bilibili()` 但没 `from_xhs()`。小红书适配器手动构造 Message，API 不统一。

---

### BUG #22 — 适配器轮询错误后无重连机制

**文件**: `dmshoot/core/adapter.py:81-87`  

`_poll_loop()` 中的 `except` 只 `sleep(2)` 然后继续。如果 Cookie 过期或 API 不可用，会永久在 2 秒间隔的错误循环中打转，不会触发重连或通知用户。

---

## 架构级问题（非 bug，但值得关注）

| 问题 | 文件 | 说明 |
|------|------|------|
| **God Object** | `main_window.py` (684行) | MainWindow 直接管理适配器生命周期、AI 调用、DB 操作、UI 同步，职责过重 |
| **配置双轨制** | YAML + SQLite | `config/__init__.py` 还有 YAML 配置方案，与 SQLite 并存 |
| **私有 API 穿透** | 多处 | `_get_conn()` 被 main_window、douyin_im_sync 等外部模块直接调用 |
| **无 GUI 集成测试** | 全局 | 所有测试都是手动验证，没有自动化 GUI 测试 |

---

## 修复优先级建议

| 优先级 | Bug 编号 | 简述 |
|--------|---------|------|
| **P0 立即** | #1 | AI 上下文重复注入 |
| **P0 立即** | #3 | `logger` 未定义导致崩溃 |
| **P0 立即** | #2 | Cookie 泄露到 sender_name |
| **P1 本周** | #4 | `_get_conn()` 竞态条件 |
| **P1 本周** | #6 | QThread stop 线程不安全 |
| **P1 本周** | #7 | 数据库写锁绕过 |
| **P2 本月** | #8~#13 | 性能/封装/死代码 |
| **P3 有空** | #14~#22 | 代码质量 |

---

## 统计

- 审查文件数: 44
- 🔴 高危 bug: 6 个
- 🟡 中危 bug: 7 个
- 🟢 低危问题: 9 个
- 架构级问题: 4 个
- **总计发现问题: 26 个**
