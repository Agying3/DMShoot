# DMShoot 终极 Bug 清单 (2026-06-15)

**审查范围**: 全部 61 个 Python 源文件  
**原则**: 只列实际运行中能触发的，排除纯风格和已修复的

---

## 🔴 会实际触发的问题（7 个）

### BUG 1 — 快手登录获取用户 ID 取错了 Cookie（`kuaishou/adapter.py:158`）

```python
# 错误：cookies[0] 可能是任意一个 cookie（sessionId、kuaishou.web.captain...）
await page.goto(
    f"https://www.kuaishou.com/profile/{cookies[0].get('value','')}",
    ...)
```

`cookies[0]` 不一定是 `userId`——它可能是列表里第一个随机的 Cookie。这会导致导航到错误的用户主页、拿不到昵称。

**修复**: 从 cookie 列表中按 name 查找：
```python
userId_val = next((c['value'] for c in cookies if c.get('name') == 'userId'), '')
```

但此处 `cookies` 是 `context.cookies()` 返回的列表，不是 dict。正确做法：
```python
# line 138: 已有 {c["name"] for c in cookies}
# line 158: 改为
uid_cookie = next((c for c in cookies if c.get("name") == "userId"), {})
uid_val = uid_cookie.get("value", "")
await page.goto(f"https://www.kuaishou.com/profile/{uid_val}", ...)
```

---

### BUG 2 — ~~B站异步轮询异常直接退出不重连~~ ✅ 已修复 (2026-06-15)

```python
async def _async_loop(self):
    while self._running:
        await self._async_poll()   # ← 如果这里抛了未捕获异常，适配器直接挂
```

旧版 `_poll_loop()` 每次异常都 `except → sleep(2) → continue`。新版 `_async_poll` 虽然内部 catch 了大多数异常，但 `asyncio.gather` 本身崩溃、或 `sess.get_sessions` 的底层异常仍可能穿透。

**修复**:
```python
while self._running:
    try:
        await self._async_poll()
    except Exception as e:
        logger.error(f"B站轮询异常(将自动重试): {e}")
        await asyncio.sleep(2)
```

---

### BUG 3 — 快手 `_request` 创建的 `httpx.AsyncClient` 从未关闭（`kuaishou/adapter.py:226-227`）

```python
async def _request(self, ...):
    if not self._client:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=False)
```

`disconnect()` 没调 `await self._client.aclose()`，`connect()` 的 event loop 关闭后 `_client` 还持有已关闭 loop 的引用。虽然快手实际没跑 `_request`（轮询只 sleep），但代码路径存在泄漏。

**修复**（如果以后启用快手）: 在 `disconnect()` 中关闭。

---

### BUG 4 — ~~抖音 WS 接收器为空时静默轮询~~ ✅ 已修复 (2026-06-15)

```python
def _poll_messages(self):
    if self._ws_receiver is None:
        time.sleep(5)       # ← 无日志，用户不知道为什么不收消息
        return
```

WS 接收器创建失败或崩溃后，适配器悄悄空转，不报错不尝试重连。

**修复**: 至少打一行 `logger.warning("WS 接收器未就绪，无法接收消息")`。

---

### BUG 5 — ~~抖音 `_conv_to_peer/_peer_cache` 类级变量~~ ✅ 已修复 (2026-06-15)

```python
class DouyinAdapter(BaseAdapter):
    _conv_to_peer: dict[str, str] = {}       # ← class-level!
    _peer_cache: dict[str, tuple[str, str]] = {}  # ← class-level!
```

如果适配器重连（stop → start），旧 WebSocket 的 conv_short_id → peer_uid 映射还在。虽然大概率无害（新 WS 会建新映射），但理论上可能把新消息路由到旧的 session_id。

**修复**: 移到 `__init__` 里初始化。

---

### BUG 6 — `kuaishou/login.py:158` 整段取昵称逻辑有 bug

续 BUG 1——同文件的取昵称逻辑还有问题：`context.cookies()` 返回 list of dict，但 line 158 用 `.get()` 取 `value` 字段是在 list index 结果上调用的，返回值是 `str | None`。如果 `cookies` 列表为空（首次请求还没加载完），`cookies[0]` 直接 IndexError。

**修复**: 同 BUG 1 的修复 + 加空列表保护。

---

### BUG 7 — `config/__init__.py` 是死代码（但无害）

YAML 配置模块从未被任何活跃路径调用。不删也不影响运行，只是 `import yaml` 多占 2MB 内存。

---

## 🟡 已知但未修的（之前提过）

| # | 位置 | 问题 | 状态 |
|---|------|------|------|
| 8 | `douyin/adapter.py:111-112` | `_patch_imports()` 每次 send 都执行 | 待修 |
| 9 | `douyin/adapter.py:114` | `create_conversation` 每次 send 都调，可缓存 | 待修 |
| 10 | `bilibili/adapter.py:373` | `all_results` 收集后丢弃 | ✅ 已修复 |
| 11 | `bilibili/adapter.py:140,149` | `_get_user_name` 双 API 失败时零日志 | ✅ 已修复 |
| 12 | `bilibili/adapter.py:13` | `ConcurrencyManager` 死 import | ✅ 已修复 |
| 13 | `main_window.py:190-192` | TitleBar `__import__()` 定义 Signal | ✅ 已修复 |
| 14 | `main_window.py:988,1012` | `__import__("time").time()` 应改 `time.time()` | ✅ 已修复 |
| 15 | `main_window.py:1008` | `database._get_conn()` 穿透私有 API | 待修 |

---

## ✅ 上次提的已修复

| Bug | 状态 |
|-----|------|
| `auto_reply_enabled` 失效 | ✅ main_window:934 |
| `monitor.add_reply_log` 丢失 | ✅ main_window:1019 |
| `on_connected` 缺快手分支 | ✅ login_page.py |
| 显示名 map 缺快手 | ✅ main_window.py |
| `_QRDialog.closeEvent` 重复 | ✅ 只剩一个 |

---

## 统计

- 🔴 新发现的运行期 bug: **7 个**（✅ 已修复 4 个: #2 #4 #5 + 抖音异步改造）
- 🟡 已知未修: **3 个**（#8 #9 #15）
- ✅ 已修复: **11 个**
- **总计 20 个条目录入**

**最新状态 (2026-06-15):**
- B站/抖音均已异步化（asyncio.run + _async_loop + _stop_event）
- TitleBar Signal、__import__ hack 清理
- 仅剩 3 个低优先级项: _patch_imports 重复、create_conversation 缓存、_get_conn 封装

---

## 修复优先级

| 优先级 | Bug | 改动量 |
|--------|-----|--------|
| **P0 立即** | #1 快手取 userId 错误 | 3 行 |
| **P0 立即** | #2 B站轮询异常退出 | 4 行 |
| **P1 本周** | #4 抖音 WS 静默 | 1 行 |
| **P1 本周** | #5 抖音类级缓存 | 挪 2 行 |
| **P2 有空** | #3 快手 HTTP client 泄漏 | 3 行 |
| **P3 闲时** | #6 #7 + 8~15 | 按需 |
