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

- [ ] 抖音平台 worker (需逆向协议)
- [ ] B站平台 worker (bilibili-api Go 版)
- [ ] 消息去重 (conversation_id + msg_index)
- [ ] 用户信息缓存 (name + avatar)
