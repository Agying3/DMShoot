# DMShoot 头像缓存 & 首页状态问题报告

> 发现时间：2026-05-31 10:12
> 涉及文件：`contact.py`、`main_window.py`

---

## 问题 A：头像下载缓存机制缺陷

**文件**：`dmshoot/gui/widgets/contact.py` — `_AvatarLoader.run()` 第 104~131 行

### A1：缓存 key 用 session_id 而非 URL（P0）

```python
# 第 111 行 — 当前实现
cache_key = sid.replace(":", "_")[:32]   # sid = "douyin:0:1:12345:67890:0:"
cp = AVATAR_DIR / f"{cache_key}.png"

# 第 113 行 — 只检查文件是否存在和大小
if cp.exists() and cp.stat().st_size > 4096:
    data = cp.read_bytes()  # 直接读缓存
```

**问题**：抖音头像 URL 是 CDN 动态链接（如 `p3-dy.byteimg.com/aweme/...`），同一用户换头像后 URL 会变，但 `session_id` 不变。结果：
- 用户换了新头像 → URL 变了 → 代码只看 `cp.exists()` → 命中了旧缓存 → **永远显示旧头像**
- 即使删了缓存文件，等用户再次换头像又会复现

**修复**：缓存 key 改用 URL 的 hash，URL 变了自动重新下载：

```python
import hashlib
cache_key = hashlib.md5(url.encode()).hexdigest()[:16]
cp = AVATAR_DIR / f"{cache_key}.png"
```

### A2：缓存 key 碰撞风险（P2）

```python
cache_key = sid.replace(":", "_")[:32]
```

两个不同的 session_id 截断到 32 字符后可能相同。例如：
- `douyin:0:1:123456789012345:67890:0:`
- `douyin:0:1:123456789012346:67890:0:`

前 32 字符完全一致 → 写入同一个缓存文件 → 两个不同用户的头像串了。

**修复**：改用 hash（见 A1 方案）从根源消除碰撞。

### A3：下载失败无 negative cache（P1）

```python
r = httpx.get(url, ...)
if r.status_code != 200 or len(r.content) < 4096:
    self.done.emit(("progress", pct))
    continue  # ← 失败了，下次启动还会重试
```

头像 URL 404/超时/网络断开后，没有任何失败标记。每次重启 DMShoot 都会重新尝试下载这些已经确认失败的 URL。

**修复**：加 `.fail` 标记文件，24 小时内失败不再重试：

```python
fail_flag = AVATAR_DIR / f"{cache_key}.fail"
if fail_flag.exists():
    if time.time() - fail_flag.stat().st_mtime < 86400:
        continue  # 跳过
    fail_flag.unlink(missing_ok=True)  # 超时了，再试一次

r = httpx.get(url, ...)
if r.status_code != 200:
    fail_flag.write_text("1")
    continue
```

---

## 问题 B：首页在适配器未连接时显示"监听中"

**文件**：`dmshoot/gui/main_window.py` — `_sync_config_to_ui()` 第 212~232 行

### B1：侧边栏状态灯的语义错误（P0）

```python
# 第 221~229 行 — 启动时立即执行
if c.douyin_cookie:
    self.sidebar.update_status("douyin", "●")    # ← 亮绿灯
if c.bilibili_sessdata:
    self.sidebar.update_status("bilibili", "●")  # ← 亮绿灯
```

**实际启动时序**：
```
__init__()
  ├─ _sync_config_to_ui()   ← 侧边栏显示 ●（此时适配器未启动）
  ├─ QTimer.singleShot(800, _auto_login)
  │    └─ _verify_saved()   ← 800ms 后才验证 cookie
  │         └─ _run_async_verify()
  │              └─ on_done  → 成功才设 ●，失败设 ✕
```

**问题**：
- `_sync_config_to_ui` 里 "有 cookie = ●" 的语义是错的
- 用户打开首页看到三个平台都亮绿灯，以为已在监听
- 如果 cookie 过期，800ms 后验证失败，但侧边栏的状态不会自动更新（`_auto_login` 的 `_verify_saved` 里 `on_done` 失败时会调 `update_status("✕")` 但只在 `_auto_login` 触发时才走）

**修复**：区分三种状态：

| 状态 | 图标 | 含义 |
|------|------|------|
| 未保存 | `✕` | 没有 cookie，需要扫码 |
| 已保存/验证中 | `—` 或 `⟳` | 有 cookie 但尚未验证连接 |
| 已连接 | `●` | 适配器运行中 |

```python
# _sync_config_to_ui()
if c.douyin_cookie:
    self.sidebar.update_status("douyin", "—")   # 灰线，表示"待验证"
    # _auto_login 完成后再由 _on_platform_status 改为 ●

# AI 也有同样的问题
if c.api_key:
    self.sidebar.update_ai_status("—")   # 而非直接 ●
```

---

## 修复清单

| # | 文件 | 行 | 修复内容 | 严重度 |
|---|------|----|---------|--------|
| 1 | `contact.py` | 111 | 缓存 key 从 session_id 改为 URL hash | 🔴 P0 |
| 2 | `contact.py` | 120-123 | 下载失败写 `.fail` 标记 | 🟠 P1 |
| 3 | `main_window.py` | 221-229 | 有 cookie 时显示 `—` 而非 `●` | 🔴 P0 |
| 4 | `main_window.py` | 216-219 | AI 状态同理 | 🟡 P2 |
