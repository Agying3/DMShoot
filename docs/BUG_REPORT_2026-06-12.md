# DMShoot Bug 审查报告 (2026-06-12)

**审查范围**: 上次审查后新增/变更的代码  
**新增文件**: `sign.py`, `login.py`, `im_client.py`, `kuaishou/adapter.py`, `xhs_proxy.py`, `capture_im.py`, `probe_xhs_galaxy.py`  
**变更文件**: `main_window.py`, `login_page.py`, `models.py`, `database.py`, `douyin/adapter.py`, `xhs/adapter.py`

---

## 🔴 实际影响运行的高危 bug（6 个）

### BUG #1 — `_QRDialog` 的 `closeEvent` 被定义两次，动画清理丢失

**文件**: `dmshoot/gui/pages/login_page.py`（_QRDialog 类）  
**根因**: 同一个类里定义了**两个** `closeEvent`，第二个覆盖第一个：

```python
# 第一个（被覆盖）
def closeEvent(self, event):
    if hasattr(self, '_rotate_anim'):
        self._rotate_anim.stop()       # ← 这段永远不会执行！
    super().closeEvent(event)

# 第二个（实际生效）
def closeEvent(self, event):
    super().closeEvent(event)          # 只调父类，不动画清理
```

**影响**: 用户关闭二维码弹窗时，旋转动画仍在运行，关联的 widget 已被销毁。可能导致 PySide6 内部警告或偶发性 crash（访问已释放的 C++ 对象）。

**修复**: 删除第二个，在第一个末尾加状态通知逻辑。

---

### BUG #2 — `on_connected` 缺少 `kuaishou` 分支，快手连上后改的是小红书状态

**文件**: `dmshoot/gui/pages/login_page.py:on_connected()`  
**代码**:
```python
def on_connected(self, platform: str):
    if platform == "douyin":
        self._has_dy = True
        self.dy_monitor.setVisible(True)
    elif platform == "bilibili":
        self._has_bili = True
        self.bili_monitor.setVisible(True)
    else:
        self._has_xhs = True          # ← "kuaishou" 落到这里！
        self.xhs_monitor.setVisible(True)  # ← 显示小红书的启动按钮！
```

**影响**: 快手登录成功后，`_has_xhs` 被设为 `True`，小红书的"启动"按钮显示，快手的按钮不显示。如果同时登录小红书和快手，状态完全混乱。

**修复**: 在 `elif platform == "bilibili"` 之后加 `elif platform == "kuaishou":` 分支。

---

### BUG #3 — `_stop_adapter_from_ui` 和 `_on_platform_status` 缺少快手显示名

**文件**: `dmshoot/gui/main_window.py`  
**两处同样的 map**:
```python
name = {"douyin": "抖音", "bilibili": "B站", "xiaohongshu": "小红书"}.get(platform, platform)
```

**影响**: 停止快手适配器时日志显示 `"kuaishou 监听已停止"` 而不是 `"快手 监听已停止"`。不崩溃，但显示异常。

**修复**: map 加 `"kuaishou": "快手"`。

---

### BUG #4 — `_run_async_verify` 的 enabled 检查漏了快手，快手永远不会自动启动

**文件**: `dmshoot/gui/main_window.py:_run_async_verify()`  
**代码**:
```python
enabled = {"douyin": self.config.douyin_enabled,
            "bilibili": self.config.bilibili_enabled,
            "xiaohongshu": self.config.xhs_enabled}.get(platform, False)
```
缺了 `"kuaishou": self.config.ks_enabled`。

**影响**: 即使 `ks_enabled=True`，快手验证成功后也不会自动启动适配器。

**修复**: 补上快手。

---

### BUG #5 — `xhs_proxy.py` 的 `start()` 状态文件不存在时直接 crash

**文件**: `dmshoot/utils/xhs_proxy.py:50`  
**代码**:
```python
async def start(self):
    try:
        ...
        state_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))  # ← 文件不存在 → FileNotFoundError
        ...
    except Exception as e:
        logger.error(f"XHS代理启动失败: {e}")  # 只打日志，proxy 不可用
```

**影响**: 首次启动时 `xhs_browser_state.json` 不存在，`XHSProxy.start()` 直接抛异常，代理不可用。所有依赖此代理的功能（如果有的话）全部失败。没有降级逻辑。

**修复**: 加文件存在检查 + 空字典 fallback：
```python
if STATE_FILE.exists():
    state_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
else:
    state_data = {}
```

---

### BUG #6 — `generate_xray_traceid()` 每次签名都 spawn Node.js 子进程

**文件**: `dmshoot/plugins/xiaohongshu/sign.py:135-137, 142-165`  
**代码**:
```python
def generate_xray_traceid() -> str:
    return _node_require_call('xhs_xray.js', 'traceId')  # 每次 spawn 一个 Node！

def generate_xsc(a1, api, data=""):
    ...
    return {
        ...
        "x-xray-traceid": generate_xray_traceid(),   # 每请求一次就调一次
    }
```

**影响**: `generate_xsc` 被 `_generate_xsc_headers` → `_fetch_sec_cookies` / `generate_qrcode` / `check_qrcode_status` / `verify_login` / `signed_request` 等大量调用。每次调用都额外起一个 Node.js 子进程生成 traceid（约 0.5-1s 开销），而 `x-b3-traceid` 用纯 Python 生成几乎零开销。登录流程中 `generate_xsc` 至少被调用 5 次，每次多等 0.5-1s。

**修复**: 缓存 `xray_traceid`，或像 `x-b3-traceid` 一样纯 Python 生成。一个会话中 traceid 不需要每次请求都换。

---

## 🟡 中危 bug（3 个）

### BUG #7 — `login.py` 的 QR 码登录模块是未使用的死代码

**文件**: `dmshoot/plugins/xiaohongshu/login.py`

`qrcode_login_step1()`, `qrcode_login_step2()`, `qrcode_login_step3()` 三个函数 + `XHSLoginResult` 类 + 所有辅助函数（`generate_init_cookies`, `generate_qrcode`, `check_qrcode_status`, `verify_login`）定义了完整的纯 HTTP QR 码登录流程，但**没有任何地方调用**。

`_CookieWorker` 中小红书扫码用的还是旧路径 `extract_xiaohongshu_cookies_sync`（Playwright 方案）。

**影响**: ~400 行代码完全闲置。如果这是你计划中要切换到的新方案，那它是好的待用代码；如果已经确定不需要，可以删。

---

### BUG #8 — `kuaishou/adapter.py` 创建的 `httpx.AsyncClient` 从未关闭

**文件**: `dmshoot/plugins/kuaishou/adapter.py:209`  
**代码**:
```python
async def _request(self, method, path, ...):
    if not self._client:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=False)
    ...
```

**影响**: 虽然当前快手 `send_message` 直接 return False、`_poll_messages` 只是 sleep，但 `connect()` 时创建了 AsyncClient，`disconnect()` 没有 `await self._client.aclose()`。如果以后启用轮询/发送，这是个潜在的连接泄漏。

**修复**: 在 `disconnect` 中补上关闭逻辑（或改同步 requests，毕竟不需要异步）。

---

### BUG #9 — `login.py` 中 `_fetch_sec_cookies` 静默吞所有异常

**文件**: `dmshoot/plugins/xiaohongshu/login.py:96-146`

整个 JSVMP 执行逻辑被包在 `try/except Exception: pass` 中。如果 Node.js 找不到、JS 执行报错、JSON 解析失败等，全部静默忽略。

**影响**: websectiga 获取失败时没有日志，可能造成后续 API 调用静默失败（缺少反爬 cookie），排查困难。

**修复**: 至少加 `logger.debug` 记录异常。

---

## 🟢 低优先级（4 个）

| # | 文件 | 问题 |
|---|------|------|
| 10 | `login_page.py:_on_cookie_ready` | `QTimer = None` 后立即 `from ... import QTimer`，冗余行 |
| 11 | `bilibili/adapter.py` | `_debug()` 仍然每次写磁盘，长期运行无限增长 |
| 12 | `im_client.py:list_chats` | 缩进不一致（`if code == -100:` 多了 4 空格），不报错但阅读迷惑 |
| 13 | `main_window.py` | `bilibili_auto_monitor` 字段名误导，实际控制所有平台的自动监听 |

---

## 修复优先级

| 优先级 | Bug | 修复量 |
|--------|-----|--------|
| **P0 立即** | #1 closeEvent 覆盖 | 删 3 行 |
| **P0 立即** | #2 on_connected 缺快手 | 加 3 行 |
| **P1 本周** | #3 显示名 map 缺快手 | 加 2 处 |
| **P1 本周** | #4 enabled 漏快手 | 加 1 行 |
| **P2 有空** | #5 xhs_proxy 文件不存在 | 加 3 行 |
| **P2 有空** | #6 traceid 性能 | 改 2 行（缓存） |
| **P3 闲时** | #7~#13 | 清理/风格 |

---

## 统计

- 新增代码约 1500 行
- 🔴 实际影响运行的高危 bug: **6 个**
- 🟡 中危: **3 个**
- 🟢 低优先级: **4 个**
