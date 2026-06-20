# DMShoot 性能优化分析 (2026-06-14)

## 实际热点（按收益排序）

---

### 🥇 P0 — XHS 签名：每次 API 调用 spawn Node.js（300-800ms）

**位置**: `sign.py:159` — `generate_xsc()`  
**现状**: 每次 `signed_request()` → `generate_xsc()` → `_node_require_call()` → subprocess + 写临时文件 + 执行 JS + 解析输出

```python
# 每次都是完整流程：
def generate_xsc(a1, api, data):
    ret = _node_require_call('xhs_creator_260411.js', ...)  # ← 300-800ms!
```

**你做了什么 API 调用**: connect (1次) + sync_history (10次分页) + user info lookup (N次) + 每 3s 轮询

**量化**: 假设 connect 时拉 5 个用户信息 + 10 页历史 = 16 次签名调用 ≈ **8-12 秒纯签名耗时**

**方案**: `xhs_creator_260411.js` 没有任何状态——同一个 a1/api/data 组合，签名结果是一样的（除了时间戳）。把 Node.js **常驻为 daemon 子进程**，stdin/stdout JSON-RPC 通信：

```
启动时: node daemon → 加载 JS 一次 (1s)
每次调用: stdin 发 JSON → stdout 读结果 (<50ms)
```

**5 行改动就能存 80% 时间。**

---

### 🥈 P1 — 抖音 `send_message`：每次 `create_conversation` + `_patch_imports`

**位置**: `douyin/adapter.py:111-115`  
**现状**:
```python
def send_message(self, session_id, text):
    from dmshoot.utils.douyin_sdk import _patch_imports  # 每次导入
    _patch_imports()                                       # 每次重造 sys.modules
    from dy_apis.douyin_api import DouyinAPI
    cid, sid, ticket = DouyinAPI.create_conversation(...)   # 额外 API 调用！
    return DouyinAPI.send_msg(...)
```

`create_conversation` 是获取 conversation_short_id，但这个值在**消息接收时已经拿到了**（`msg.conversation_short_id 存在 Message 对象里`）。

**方案**:
1. `_patch_imports()` 移到 `connect()` 里执行一次
2. 会话 ID 缓存到 `_conv_cache` dict，下次同一个人发消息跳过 `create_conversation`

**预期**: AI 回复延迟从 2-3 秒降到 < 1 秒（省掉一次 API 调用）。

---

### 🥉 P2 — AI 上下文重复（token 翻倍）

**位置**: `ai/backend.py:68-69 + 83-91`  
**现状**: 每条消息在 context 里出现两次 → token 浪费 50-100%

**量化**: 如果有 10 轮对话上下文（20 条 messages），每条 ~100 tokens → 2000 tokens。翻倍后 4000 tokens，多花 ¥0.004/次（DeepSeek v4 价格）。看起来不多，但：
- 上下文更快达到 MAX_CONTEXT_MESSAGES 限制
- AI 理解能力下降（重复信息干扰）
- 响应时间多 10-20%

**方案**: 上次给过的 3 行 fix。

---

### P3 — B站轮询 `_debug()` 无限追加

**位置**: `bilibili/adapter.py:36-42`  
**现状**: 每 3 秒 append 一行到文件

**量化**: 跑 24 小时 = 28,800 行 → `adapter_debug.txt` 不断增大 → 磁盘碎片 + 每次 poll 多 1-3ms I/O

**方案**: 加一个简单的文件大小上限或 rotate：
```python
if DEBUG_FILE.stat().st_size > 1024 * 1024:  # 1MB
    DEBUG_FILE.rename(DEBUG_FILE.with_suffix(".old"))
```

---

### P4 — Python `requests` 不用连接池

**现状**: 每次 HTTP 调用重建 TCP 连接（TLS 握手 ~50-100ms）

**方案**: 改用 `requests.Session()` 持有一个全局 session：
```python
_session = requests.Session()
_session.headers.update(_base_headers())
```

对所有 XHS API 调用、抖音 name lookup 都有效。

---

### P5 — Douyin `_warm_peer_cache` 全量扫 DB

**位置**: `douyin/adapter.py:59`  
**现状**: 启动时 `SELECT * FROM sessions WHERE platform='douyin'` — 加载所有历史会话到内存。如果几百个会话，就是几百行 JSON 解析。

**方案**: 懒加载——收到消息时查 `peer_cache`，miss 了再查 DB + API。启动零成本。

---

## 不在优化范围内的（别花时间）

| 项目 | 为什么不优化 |
|------|------------|
| Go 服务 | 暂不需要，Python 够用 |
| 线程池放大到 64 | 当前 32 都只用 < 5 |
| WebSocket → Go 推送 | 当前 1 个客户端，没必要 |
| SQLite → PostgreSQL | 单用户场景，WAL 已最优 |
| asyncio 全改 | 重构成本 > 收益，现有 QThread 模型够用 |

---

## 优先级排序

| 优先级 | 改动 | 代码量 | 收益 |
|--------|------|--------|------|
| P0 | XHS Node.js daemon | ~30 行 | 签名字系统 300ms→50ms |
| P1 | 抖音去 `create_conversation` | 改 5 行 | 每次发送省 1 次 API |
| P1 | 抖音 `_patch_imports` 移 connect | 改 2 行 | 每次发送省 30-50ms |
| P2 | AI 上下文去重 | 改 3 行 | token 省 50% |
| P2 | 共用 `requests.Session` | 改 5 行 | 每次 HTTP 省 50ms |
| P3 | B站 debug 加 rotate | 改 3 行 | 长期运行不爆盘 |
| P3 | Douyin peer_cache 懒加载 | 改 10 行 | 启动快 100-500ms |
