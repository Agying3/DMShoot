# dmshoot-go —— DMShoot 高并发消息服务

Go 实现的消息处理后端，通过 HTTP + WebSocket 与 Python GUI 通信。

## 架构

```
Python GUI (PySide6)
    │
    │ HTTP REST + WebSocket
    ▼
Go msg-service (localhost:9800)
    ├─ /api/register    — 注册平台 worker
    ├─ /api/unregister  — 停止 worker
    ├─ /api/send        — 发送消息
    ├─ /api/status      — 查询运行状态
    ├─ /api/health      — 健康检查
    └─ /ws              — WebSocket 实时推送
```

## 编译

```bash
# 安装 Go (https://go.dev/dl/)，然后:
cd dmshoot-go
go mod tidy
go build -o msg-service.exe .
```

## 运行

```bash
# 直接启动
msg-service.exe

# 或从 Python 端启动
python -c "from dmshoot.core.go_bridge import get_go_bridge; get_go_bridge().start()"
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DMSHOOT_DB` | 自动发现（exe 目录 → cwd） | SQLite 路径。优先用此 env，否则按候选路径搜索 |

## API 文档

### POST /api/register

```json
{
    "platform": "douyin",
    "cookie": "...",
    "interval_ms": 3000
}
```

### POST /api/send

```json
{
    "platform": "douyin",
    "session_id": "douyin:0:1:xxx:yyy:0:",
    "content": "你好"
}
```

### GET /api/status

```json
{
    "workers": 2,
    "platforms": ["douyin", "bilibili"]
}
```

### WebSocket /ws

推送格式:
```json
{
    "platform": "douyin",
    "session_id": "douyin:...",
    "sender_name": "张三",
    "content": "在吗",
    "timestamp": 1700000000
}
```

## 待实现

> **注意**: 平台协议层（抖音 protobuf、B站 API）由 Python 适配器处理，
> Go 服务负责基础设施（DB 批量写入、WS 中继）。以下 Go 侧 worker 非必需。

- [ ] 抖音平台 worker — Python `DouyinAdapter` 已通过 WebSocket + protobuf 完整实现
- [ ] B站平台 worker — Python `BilibiliAdapter` 已通过 asyncio 并发轮询完整实现
- [ ] 消息去重 — Python 端双防线（DB UNIQUE + 内存 set）已覆盖
- [ ] 用户信息缓存 — Python 端 `peer_cache` 已实现

**当前 Go 服务实际职责**:
| 能力 | 实现方式 |
|------|---------|
| SQLite 批量写入 | `BatchWriter` — 合并写入减少 DB 锁竞争 |
| WebSocket 实时广播 | 多客户端消息推送 |
| HTTP DB API | 消息/会话 CRUD 代理 |
| WAL checkpoint | 优雅关闭前自动触发 |
