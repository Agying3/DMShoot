# DMShoot Godot 前端方案可行性分析（完整版）

---

## 目录

1. [架构对比](#1-架构对比)
2. [API 接口契约（逐字段定义）](#2-api-接口契约逐字段定义)
3. [Godot UI 状态管理方案](#3-godot-ui-状态管理方案)
4. [无法在 Godot 实现的功能——完整替代方案](#4-无法在-godot-实现的功能完整替代方案)
5. [性能监控图表在 Godot 的实现方案](#5-性能监控图表在-godot-的实现方案)
6. [打包与分发方案](#6-打包与分发方案)
7. [时间估算](#7-时间估算)
8. [风险与阻碍](#8-风险与阻碍)
9. [与当前 PySide6 方案对比](#9-与当前-pyside6-方案对比)
10. [建议执行路径](#10-建议执行路径)
11. [验收用例](#11-验收用例)
12. [失败场景与降级策略](#12-失败场景与降级策略)
13. [日志规范](#13-日志规范)
14. [部署检查清单](#14-部署检查清单)
15. [文档变更记录](#15-文档变更记录)

---

## 1. 架构对比

### 1.1 当前架构（同进程）

```
┌──────────────────────────────────────┐
│            Python 3.12               │
│  ┌──────────────┐  ┌──────────────┐  │
│  │ PySide6 GUI  │←→│  后端逻辑     │  │  Qt Signal / 直接调用
│  └──────────────┘  │ · Adapter    │  │
│                    │ · AI         │  │
│                    │ · Storage    │  │
│                    └──────────────┘  │
└──────────────────────────────────────┘
               DMShoot.exe   150MB
```

### 1.2 目标架构（双进程）

```
┌────────────────┐   JSON/HTTP   ┌──────────────────────────┐
│  Godot 4.5     │ ←──────────→ │  Python 后端 (FastAPI)     │
│  · 登录页      │              │  · Adapter (不用动)        │
│  · 聊天页      │  WebSocket   │  · AI (不用动)             │
│  · 设置页      │ ←──实时推送→ │  · Storage (不用动)        │
│  · 通讯录      │              │  · Playwright (不用动)      │
│  · 提示词      │              │  · DouYin Spiders (不动)    │
└────────────────┘              └──────────────────────────┘
   Godot.exe ~30MB                 Backend.exe ~40MB

总交付: DMShoot.zip + Launcher.exe ~70MB
```

**关键原则：后端一行 Python 代码不用改，只在 MessageBus 上加一个 WebSocket 出口。**

---

## 2. API 接口契约（逐字段定义）

### 2.0 通用约定

- **Base URL**: `http://127.0.0.1:9876`
- **Content-Type**: `application/json; charset=utf-8`
- **认证**: 无（本地进程间通信，绑定 127.0.0.1 不对外开放）
- **HTTP 状态码规则**:
  - `200` 成功
  - `400` 请求参数错误
  - `500` 后端内部错误
- **WebSocket URL**: `ws://127.0.0.1:9876/ws`

### 2.1 连接管理

#### POST /api/adapter/start

启动平台私信监听。

**Request**
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `platform` | string | ✅ | `"douyin"` \| `"bilibili"` \| `"kuaishou"` \| `"xiaohongshu"` |
| `auto_reply` | boolean | ❌ | 是否开启自动回复，默认 `true` |

**Response** `200 OK`
| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | boolean | 是否启动成功 |
| `platform` | string | 平台名 |
| `status` | string | `"online"` \| `"connecting"` \| `"error"` |
| `detail` | string\|null | 状态描述，失败时为错误原因 |

**Error** `400 / 500`
| 字段 | 类型 | 说明 |
|------|------|------|
| `error` | string | 错误类型 `"platform_not_found"` \| `"adapter_busy"` \| `"internal_error"` |
| `detail` | string | 详细错误信息 |

---

#### POST /api/adapter/stop

停止平台私信监听。

**Request**
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `platform` | string | ✅ | `"douyin"` \| `"bilibili"` \| `...` |

**Response** `200 OK`
```json
{ "ok": true, "platform": "douyin" }
```

---

#### GET /api/adapter/status

获取所有平台的连接状态。

**Request**: 无 Body

**Response** `200 OK`
| 字段 | 类型 | 说明 |
|------|------|------|
| `platforms` | object | 以平台名为 key |
| `platforms.{name}` | object | |
| `platforms.{name}.connected` | boolean | 是否已连接 |
| `platforms.{name}.status` | string | `"online"` \| `"offline"` \| `"connecting"` \| `"error"` |
| `platforms.{name}.name` | string\|null | 用户昵称 |
| `platforms.{name}.error` | string\|null | 错误原因 |
| `platforms.{name}.session_count` | integer | 会话数量 |

```json
{
  "platforms": {
    "douyin": {
      "connected": true,
      "status": "online",
      "name": "柁炑炑",
      "error": null,
      "session_count": 8
    },
    "bilibili": {
      "connected": false,
      "status": "offline",
      "name": null,
      "error": "Cookie 已过期",
      "session_count": 0
    }
  }
}
```

---

### 2.2 登录

#### POST /api/login/scan

触发扫码登录。后端启动 Playwright 浏览器，通过 WebSocket 实时推送二维码和登录结果。

**Request**
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `platform` | string | ✅ | `"douyin"` \| `"bilibili"` \| `"xiaohongshu"` \| `"kuaishou"` |

**Response** `200 OK` (立即返回，异步执行)
```json
{ "ok": true, "platform": "douyin", "status": "scanning" }
```

**后续 WebSocket 事件** (详见 2.7):

```
event: qr_code    → 二维码就绪，data.b64 是 base64 PNG
event: login_ok   → 扫码成功
event: login_fail → 扫码失败/超时
```

---

#### POST /api/login/cancel

取消正在进行的扫码。

**Request**
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `platform` | string | ✅ | |

---

### 2.3 消息

#### GET /api/sessions

获取通讯录会话列表（所有平台聚合）。

**Query Parameters**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `platform` | string | (全部) | 按平台筛选 |

**Response** `200 OK`
```json
{
  "sessions": [
    {
      "session_id": "douyin:0:1:1028742494552135:7581349050324026405:0:",
      "platform": "douyin",
      "peer_name": "云墨Tomia",
      "peer_id": "1028742494552135",
      "avatar_url": "https://...",
      "last_message": "午饭吃了吗？",
      "last_time": 1750929641.0,
      "unread": 2,
      "is_online": false
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 全局唯一会话 ID |
| `platform` | string | 平台 |
| `peer_name` | string | 对方昵称 |
| `peer_id` | string | 对方 UID |
| `avatar_url` | string | 头像 URL（空串表示无） |
| `last_message` | string | 最后一条消息预览 |
| `last_time` | number | Unix 时间戳 |
| `unread` | integer | 未读数 |
| `is_online` | boolean | 对方是否在线 |

---

#### GET /api/messages/{session_id}

获取历史消息。

**Query Parameters**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | integer | 50 | 返回条数，最大 200 |
| `before` | number | (最新) | Unix 时间戳，拉取此时间之前的消息 |

**Response** `200 OK`
```json
{
  "session_id": "douyin:0:1:...",
  "peer_name": "云墨Tomia",
  "messages": [
    {
      "msg_id": 12345,
      "sender_id": "1028742494552135",
      "sender_name": "云墨Tomia",
      "content": "你好呀",
      "msg_type": "text",
      "timestamp": 1750929600.0,
      "is_self": false
    }
  ],
  "has_more": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `msg_id` | integer | 消息唯一 ID |
| `sender_id` | string | 发送者 UID |
| `sender_name` | string | 发送者昵称 |
| `content` | string | 消息正文（Markdown） |
| `msg_type` | string | `"text"` \| `"image"` \| `"sticker"` |
| `timestamp` | number | Unix 时间戳 |
| `is_self` | boolean | 是否自己发送 |
| `has_more` | boolean | 是否还有更多历史消息 |

---

#### POST /api/message/send

发送消息。

**Request**
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `session_id` | string | ✅ | 目标会话 ID |
| `text` | string | ✅ | 消息内容（纯文本，最长 500 字符） |

**Response** `200 OK`
| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | boolean | 是否发送成功 |
| `error` | string\|null | 失败原因，如 `"rate_limited"` `"auth_expired"` |

**Error Codes**
| error 值 | HTTP | 含义 |
|----------|:---:|------|
| `rate_limited` | 400 | 发送过于频繁 |
| `auth_expired` | 400 | Cookie 过期，需重新扫码 |
| `platform_offline` | 400 | 目标平台未连接 |
| `session_not_found` | 400 | 会话 ID 不存在 |
| `internal_error` | 500 | 平台 API 异常 |

---

#### POST /api/ai/active

AI 主动生成消息（基于实时对话上下文）。通过 **WebSocket 流式返回**。

**Request**
| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `session_id` | string | ✅ | 目标会话 |
| `persona` | string | ❌ | 角色名，默认使用当前设置 |

**Response** `200 OK` (立即返回)
```json
{ "ok": true, "status": "generating" }
```

**后续 WebSocket 事件** (详见 2.7):
```
event: ai_stream → { session_id, chunk, done }
```

---

### 2.4 设置

#### GET /api/config

**Response** `200 OK`
```json
{
  "api_key": "sk-****",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-v4-flash",
  "auto_reply_enabled": true,
  "reply_delay_min": 1.0,
  "reply_delay_max": 3.0,
  "max_context_rounds": 10,
  "temperature": 0.7,
  "max_tokens": 1024,
  "theme": "dark",
  "rate_douyin": 3,
  "rate_bilibili": 3
}
```

---

#### PUT /api/config

**Request**
任意字段的 partial update，未传的字段保持不变。
```json
{ "theme": "light", "auto_reply_enabled": false }
```

**Response** `200 OK`
```json
{ "ok": true }
```

**Error** `400`
```json
{ "error": "invalid_field", "detail": "unknown key: xxx" }
```

---

#### GET /api/prompts

**Response** `200 OK`
```json
{
  "presets": {
    "默认助手": "你是一个热心的助手...",
    "02_热情朋友": "你是一个非常热情的朋友...",
    "03_专业客服": "你是专业客服...",
    "04_高冷话痨": "你是一个高冷话痨..."
  },
  "active": "默认助手",
  "behavior_presets": {
    "默认": "使用自然语气...",
    "精简版": "简洁回复..."
  },
  "active_behavior": "默认"
}
```

---

#### PUT /api/prompts

**Request**
```json
{
  "name": "02_热情朋友",
  "content": "你是一个非常热情的...",
  "type": "role"   // "role" | "behavior"
}
```

---

### 2.5 AI 连通性测试

#### GET /api/ai/test

**Response** `200 OK`
```json
{ "ok": true, "model": "deepseek-v4-flash", "latency_ms": 842 }
```

**Error** `500`
```json
{ "ok": false, "error": "API key 无效或网络不通", "detail": "ConnectionError..." }
```

---

### 2.6 性能监控

#### GET /api/perf/snapshot

获取当前性能快照。

**Response** `200 OK`
```json
{
  "cpu_percent": 12.5,
  "memory_mb": 156.3,
  "msg_rate": 2.3,
  "adapter_status": {
    "douyin": { "running": true, "queue_size": 3 },
    "bilibili": { "running": true, "queue_size": 0 }
  },
  "event_breakdown": {
    "api_call": 35,
    "db_write": 20,
    "ai_inference": 25,
    "ws_recv": 12,
    "other": 8
  }
}
```

---

### 2.7 WebSocket 事件（实时推送）

**连接**: `ws://127.0.0.1:9876/ws`

**服务端 → 客户端推送事件**:

| event | payload 字段 | 类型 | 触发时机 |
|------|------|------|------|
| `message` | `platform`, `session_id`, `sender_id`, `sender_name`, `content`, `msg_type`, `timestamp`, `is_self` | 见 2.3 messages 格式 | 收到新私信 |
| `platform_status` | `platform`, `status`, `detail` | string, string, string\|null | 连接状态变化 |
| `qr_code` | `platform`, `b64` | string, string | 二维码就绪 |
| `login_ok` | `platform` | string | 扫码成功 |
| `login_fail` | `platform`, `reason` | string, string | 扫码失败/超时 |
| `ai_stream` | `session_id`, `chunk`, `done` | string, string, boolean | AI 生成中 |
| `perf` | `cpu`, `memory`, `msg_rate`, `breakdown` | 见 2.6 | 每秒推送 |
| `log` | `level`, `platform`, `message` | string, string, string | 日志（可选） |
| `heartbeat` | `ts` | number | 每 5 秒心跳 |

**客户端 → 服务端发送**:
```json
{ "action": "ping" }
{ "action": "typing", "session_id": "..." }
```

---

## 3. Godot UI 状态管理方案

### 3.1 问题

PySide6 有一套完善的 MVC 体系：`QAbstractListModel` → `QListView`、Signal/Slot 自动绑定。Godot 没有这套东西——它的节点树是"全能控制器"，没有"模型"的概念。

### 3.2 方案：Autoload 全局状态 + 节点信号

采用 **单例状态管理器 + 节点级局部订阅** 的混合模式，不引入第三方框架。

```
┌─────────────────────────────────────────────────┐
│              AppState (Autoload 单例)             │
│                                                  │
│  var sessions: Array[SessionData]     ← API 拉取 │
│  var messages: Dictionary               缓存     │
│  var adapter_status: Dictionary                 │
│  var config: Dictionary                         │
│  var prompts: Dictionary                        │
│  var current_session_id: String                 │
│  var current_page: String                       │
│                                                  │
│  signal session_list_changed()                  │
│  signal message_received(session_id, msg)       │
│  signal platform_status_changed(platform, data) │
│  signal config_changed(key, value)              │
│  signal ai_stream_chunk(session_id, chunk)      │
│  signal login_state_changed(platform, state)    │
└─────────────────────────────────────────────────┘
         ↑                           ↓
    API.gd (HTTP)              UI 节点们订阅信号
    WSClient.gd (WebSocket)    更新自己的显示
```

**数据流示例：收到新消息**

```
WSClient.gd                       AppState.gd                  ChatPage.gd
   │                                  │                            │
   │ on_message(data)                 │                            │
   ├──→ appState.add_message(data)    │                            │
   │    ├── 写入 messages 缓存          │                            │
   │    ├── 更新 sessions 未读数        │                            │
   │    └── emit signal               │                            │
   │         message_received(sid,msg) ├──→ _on_message(sid,msg)   │
   │                                  │     ├── 添加气泡 (BubbleWidget)
   │                                  │     └── 滚动到底部
```

**关键规则**:
- UI 节点**永远不直接调 HTTP**，通过 `API.gd` 封装层
- `AppState` 是**唯一的数据源**，UI 节点只读不写
- 写操作走 `API.gd → 后端 → WS 推送 → AppState → UI 更新` 这个闭环

### 3.3 Autoload 文件清单

| 文件 | 职责 |
|------|------|
| `AppState.gd` | 全局状态 + 所有 Signal 定义 |
| `API.gd` | HTTP 请求封装，所有接口调用入口 |
| `WSClient.gd` | WebSocket 客户端，解析推送事件 → 写入 AppState |
| `ThemeManager.gd` | 深色/浅色主题切换 |
| `ConfigProvider.gd` | 从 AppState 读取配置的便捷方法 |

---

## 4. 无法在 Godot 实现的功能——完整替代方案

### 4.1 Markdown 渲染

**问题**: Godot `RichTextLabel` 只支持 BBCode，不支持 Markdown。

**方案**: 写一个 80 行的 Markdown→BBCode 转换器。只支持聊天场景需要的少数语法：

| Markdown | BBCode |
|------|------|
| `**粗体**` | `[b]粗体[/b]` |
| `*斜体*` | `[i]斜体[/i]` |
| `~~删除线~~` | `[s]删除线[/s]` |
| 纯文本 URL | `[url]url[/url]` |
| `\n` 换行 | Godot 自动 |

不需要支持表格、标题、代码块——聊天不涉及这些。

```gdscript
# MarkdownLabel.gd (extends RichTextLabel)
func set_markdown(text: String):
    text = text.replace("**", "[b]").replace("[/b]", "[/b]")  # 简化版
    # ... 实际用 regex 替换
    self.bbcode_text = result
```

### 4.2 系统托盘

**问题**: Godot 没有 `QSystemTrayIcon`。

**方案**: 用 Python 后端处理托盘图标。Godot 前端只需要通过 WS 收发消息，隐藏到托盘是后端的事。

```
后端 main_headless.py 启动时:
  if sys.platform == "win32":
      import pystray
      icon = pystray.Icon("DMShoot", image, "DMShoot", menu)
      icon.run_detached()
  # macOS/Linux: pystray 也支持
```

后端托盘菜单：`[显示 Godot 窗口] [退出]`。点击"显示 Godot 窗口"时通过 WS 发送 `{action: "show_window"}` 给 Godot，Godot 调 `DisplayServer.window_set_mode(Window.MODE_WINDOWED)`。

桌面图标也交给 Python 后端创建（`pystray` 原生支持），上帝ot。

### 4.3 Emoji 渲染

**问题**: Godot 的字体渲染对 emoji 支持不稳定，取决于系统字体。

**方案**: 分两步：
1. **打包 Twemoji 字体**（2MB），在 Godot 主题中注册为 fallback 字体
2. **宽度计算**: 用 `Font.get_string_size()` 测量 emoji 宽度，确保气泡不截断

如果仍有渲染问题，可以用 `[img]` 标签将常见 emoji 替换为打包的 PNG 图片（64×64，20 个常用表情 ≈ 500KB）。

### 4.4 桌面壁纸更换

**问题**: QFileDialog → setStyleSheet 是 PySide6 专有的。

**方案**:
```
Godot FileDialog → 选择图片 → 复制到 user://wallpaper.png
    → TextureRect.texture = load("user://wallpaper.png")
    → 保存选择到 AppState.config.wallpaper_path
    → 后端持久化到 SQLite
```

### 4.5 窗口圆角/透明背景

**方案**: Godot 4.x 原生支持。项目设置中：
```
display/window/size/transparent = true
display/window/per_pixel_transparency/enabled = true
```
然后在根节点的 `StyleBoxFlat` 中设 `corner_radius`。

### 4.6 播放声音提示

**方案**: Godot 内置 `AudioStreamPlayer`，收到新消息时播放 `res://assets/notification.wav`。需要后端 WS 推送 `message` 事件中包含 `is_self: false` 时才播放。

---

## 5. 性能监控图表在 Godot 的实现方案

### 5.1 方案选择

**纯手绘（推荐）**。不用 matplotlib，不用 WebView，不用社区插件。

理由：
- 当前实现（`perf_chart.py`）本身就是 500 行 QPainter 手绘，没有任何 matplotlib 依赖
- Godot 的 `_draw()` API 比 QPainter 更简洁：`draw_line(from, to, color, width)`，没有 QPen/QBrush/QPainterPath 等 C++ 抽象层
- 折线图 + 饼图 + 柱状图都在 Godot 的 2D 绘制能力范围内

### 5.2 具体实现

```gdscript
# PerfChart.gd (extends Control)

var data := []           # Array[{cpu, mem, msg, ts}]
var max_points := 60     # 60 秒窗口
var colors := {
    cpu = Color("#378add"),
    mem = Color("#74c7ec"),
    msg = Color("#a6e3a1"),
    grid = Color("#ffffff15"),
    text = Color("#cdd6f4"),
    fill_cpu = Color("#378add20"),   # 渐变填充 20% 透明度
}

func add_point(cpu: float, mem: float, msg: float):
    data.append({"cpu": cpu, "mem": mem, "msg": msg, "ts": Time.get_unix_time_from_system()})
    if data.size() > max_points:
        data.pop_front()
    queue_redraw()  # 触发 _draw()

func _draw():
    if data.is_empty(): return
    var rect := get_rect()
    var chart_height := rect.size.y - 40
    var chart_width := rect.size.x - 60
    var x_step := chart_width / max_points

    # 网格线
    for i in range(5):
        var y := 20 + chart_height * i / 4
        draw_line(Vector2(50, y), Vector2(50 + chart_width, y), colors.grid)

    # 折线
    for i in range(1, data.size()):
        var x0 := 50 + (i-1) * x_step
        var x1 := 50 + i * x_step
        var y0 := 20 + chart_height * (1 - data[i-1].cpu / 100)
        var y1 := 20 + chart_height * (1 - data[i].cpu / 100)
        draw_line(Vector2(x0, y0), Vector2(x1, y1), colors.cpu, 2.0)

        # 渐变填充 (CPU)
        var fill_points := PackedVector2Array([Vector2(x0, y0), Vector2(x1, y1),
                                                Vector2(x1, 20+chart_height), Vector2(x0, 20+chart_height)])
        draw_colored_polygon(fill_points, colors.fill_cpu)

    # 图例
    var font := get_theme_default_font()
    draw_string(font, Vector2(50, 15), "CPU", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, colors.cpu)
```

### 5.3 饼图实现

```gdscript
func draw_pie(breakdown: Dictionary, center: Vector2, radius: float):
    var total := 0.0
    for v in breakdown.values(): total += v
    var angle := 0.0
    var pie_colors := [Color("#378add"), Color("#74c7ec"), Color("#a6e3a1"),
                       Color("#fab387"), Color("#cba6f7")]
    var i := 0
    for label in breakdown:
        var slice_angle := 2 * PI * breakdown[label] / total
        var points := PackedVector2Array([center])
        for step in range(int(slice_angle * 60) + 1):
            var a := angle + step / 60.0
            points.append(center + Vector2(cos(a), sin(a)) * radius)
        draw_colored_polygon(points, pie_colors[i % pie_colors.size()])
        angle += slice_angle
        i += 1
```

### 5.4 数据流

```
perf_monitor.py (现有，bypass)
    → WS 每秒推送 {cpu, memory, msg_rate, breakdown}
    → AppState.perf_snapshot_changed signal
    → PerfChart.add_point() → queue_redraw() → _draw()
```

---

## 6. 打包与分发方案

### 6.1 方案选型

| 方案 | 体积 | 启动方式 | 缺点 |
|------|:---:|------|------|
| A: 两个独立 exe + 启动脚本 | ~70MB | 双击 .bat | 两个进程 |
| B: PyInstaller 把 Godot 当 data 包进去 | ~200MB | 双击 .exe | 体积回到现在 |
| C: subprocess 拉起 | ~70MB | 双击 Launcher.exe | Godot 无法打包进 Python |

**推荐方案 C**：一个轻量启动器（`Launcher.exe`），自动拉起后端和 Godot。

### 6.2 目录结构（发布包）

```
DMShoot-v0.3.0/
├── Launcher.exe          ← Python PyInstaller 打包，40MB
├── Godot.exe             ← Godot 导出，30MB
├── Godot.pck             ← Godot 资源包，2MB
├── node.exe              ← Node.js 运行时，87MB
│                         (可选，后端已内置 Node 发现)
├── backend/
│   ├── backend.exe       ← PyInstaller Python 后端
│   └── _internal/        ← PyInstaller 解压目录（运行时自动）
└── data/
    └── dmshoot.db         ← 用户数据目录（首次运行创建）
```

### 6.3 启动器实现（Launcher.py → Launcher.exe）

```python
# Launcher.py
import subprocess, sys, os, time, atexit, signal

ROOT = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
BACKEND = os.path.join(ROOT, "backend", "backend.exe")
GODOT = os.path.join(ROOT, "Godot.exe")

def main():
    # 1. 启动后端
    backend = subprocess.Popen([BACKEND], cwd=ROOT)
    atexit.register(lambda: backend.terminate())

    # 2. 等后端就绪
    import urllib.request, json
    for _ in range(30):
        try:
            r = urllib.request.urlopen("http://127.0.0.1:9876/api/health", timeout=1)
            if r.status == 200: break
        except: time.sleep(0.5)
    else:
        print("后端启动超时"); return 1

    # 3. 拉起 Godot
    godot = subprocess.Popen([GODOT], cwd=ROOT)
    atexit.register(lambda: godot.terminate())

    # 4. 等待 Godot 退出后关闭后端
    godot.wait()
    backend.terminate()
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 6.4 PyInstaller 配置（打包后端）

```python
# backend.spec
a = Analysis(["main_headless.py"], ...)
exe = EXE(..., name="backend", console=False, icon="resources/tujue.ico")
```

### 6.5 PyInstaller 配置（打包启动器）

```python
# launcher.spec
a = Analysis(["Launcher.py"], ...)
exe = EXE(..., name="Launcher", console=False, icon="resources/tujue.ico")
```

### 6.6 构建脚本

```bash
# build-release.bat
echo [1/3] Building Python backend...
cd dmshoot
pyinstaller backend.spec --noconfirm

echo [2/3] Building Launcher...
pyinstaller launcher.spec --noconfirm

echo [3/3] Copying Godot export...
copy ..\godot-project\export\DMShoot.exe dist\Godot.exe
copy ..\godot-project\export\DMShoot.pck dist\Godot.pck

echo Done: dist\Launcher.exe
```

### 6.7 体积测算

| 组件 | 大小 |
|------|-----:|
| Godot.exe + Godot.pck | ~32MB |
| backend.exe (Python + FastAPI + 后端) | ~40MB |
| Launcher.exe (Python 壳) | ~5MB |
| **合计** | **~77MB** |

如果不需要 Launcher.exe（用户手动依次启动），可以降到 ~72MB（Godot 30MB + Backend 40MB + 2MB 脚本）。

---

## 7. 时间估算

### 阶段 1：后端 API 层（3 天）

| 任务 | 预估 |
|------|:---|
| FastAPI + WebSocket 框架搭建 | 半天 |
| 15 个 REST 端点实现 | 1 天 |
| MessageBus → WebSocket 桥接 | 1 天 |
| 测试 & 调试 | 半天 |

### 阶段 2：Godot 前端（12 天）

| 任务 | 预估 | 说明 |
|------|:---:|------|
| 项目搭建 + 主题 + 导航 + Autoload | 1 天 | AppState / API / WSClient / ThemeManager |
| 登录页 | 2 天 | 平台选择、QR 显示、扫码状态、验证 |
| 聊天页 | 2.5 天 | 通讯录 scroll、气泡 renderer、输入框、AI 按钮 |
| AI/提示词设置页 | 1.5 天 | 表单控件、文件读写 |
| 设置对话框 | 1 天 | 主题切换、限速滑块、平台开关 |
| 侧边栏 + 标题栏 | 0.5 天 | 连接状态指示灯、导航按钮 |
| 性能监控页 | 1 天 | Godot `_draw()` 折线图+饼图 |
| 动画/交互细节 | 1 天 | 分隔线、消息滑入、主题切换过渡 |
| 适配 & 边界测试 | 1.5 天 | 断线重连、空状态、错误提示 |

### 阶段 3：打包 & 发布（1 天）

| 任务 | 预估 |
|------|:---|
| Godot 导出 Windows exe | 半天 |
| Python 后端 PyInstaller | 之前已有 |
| Launcher 脚本 + 测试 | 半天 |

**总计：约 16 个工作日（3 周）**

---

## 8. 风险与阻碍

### 🔴 高风险

| 风险 | 缓解措施 |
|------|------|
| 聊天列表滚动性能（Godot 大节点数可能卡） | MVP 第一天就测 100+ 消息，如果卡就上虚拟列表（只渲染可见的 20 条） |
| 跨进程通信可靠性 | 后端挂了 Godot 显示"重连中"，3 秒心跳超时自动重连 |
| 你从未用过 Godot | MVP 阶段熟悉，2-3 天学习曲线 |

### 🟡 中风险

| 风险 | 缓解措施 |
|------|------|
| Godot 字体/emoji 渲染一致性 | 打包思源黑体 + Twemoji，锁定字体不回退 |
| 窗口置顶/最小化等系统级操作 | Godot 4.x 的 `DisplayServer` 已足够 |
| 主题切换流畅度 | 用 Theme type variations 预定义两套，切换时全局替换 |

### 🟢 低风险

| 风险 | 缓解措施 |
|------|------|
| 分发体积 | Godot 30MB + Python 40MB = 70MB，比现在的 150MB 减半 |
| 跨平台 | Godot 原生导出，Python 需处理路径差异（工作量 <1h） |

---

## 9. 与当前 PySide6 方案对比

| 维度 | PySide6（当前） | Godot + FastAPI（新） |
|------|:---:|:---:|
| 打包体积 | 150MB | ~77MB |
| 启动速度 | 3-5 秒 | 2-4 秒（两进程并行启动） |
| UI 灵活度 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 动画效果 | QPropertyAnimation | Tween 系统，远超 Qt |
| 图表渲染 | QPainter 500 行 | Godot `_draw()` ~300 行 |
| 聊天窗口质量 | Qt 生产级 | 需 MVP 验证 |
| 技术债 | MainWindow God Object | 零 |
| 维护 | 1 个 Python 项目 | 1 个 Python + 1 个 Godot |
| 跨平台 | Windows | Windows + Linux + macOS(签名) |
| 手机版扩展 | 不可能 | Godot 导出 APK（空壳，需要后端） |
| 学习成本 | 已掌握 | GDScript 新鲜感 |

---

## 10. 建议执行路径

### 第一步：MVP 验证（3 天）

最低成本验证关键风险：

```
1. main_headless.py (FastAPI + WS)  ← 后端 API 层
2. Godot 连上 WS
3. 显示通讯录列表（GET /api/sessions）
4. 点击联系人 → 显示历史消息（GET /api/messages/xxx）
5. 发送一条消息（POST /api/message/send）
```

这 5 个功能跑通，就能确认：
- Godot ↔ Python 通信 OK
- 聊天渲染性能 OK
- 开发体验 OK

如果 MVP 在第 3 天失败（卡在渲染性能或 Markdown 转换），停掉就行——PySide6 版本不受任何影响。

### 第二步：完整开发（12 天）

MVP 过了就全速。旧 `main.py` 不动，新增：
- `main_headless.py`（后端入口）
- `dmshoot/api/`（API 层）
- `godot-project/`（Godot 工程目录）

### 第三步：切换 & 发布（1 天）

新版本稳定后，`main.py` 标记为 legacy，正式发布 Godot 版本。

---

## 11. 验收用例

### 11.1 适配器启动（POST /api/adapter/start）

| 用例 ID | 输入 | 预期 HTTP | 预期响应 | 预期 UI 状态 |
|------|------|:---:|------|------|
| TC-A001 | `{"platform":"douyin","auto_reply":true}` | 200 | `{"ok":true,"platform":"douyin","status":"connecting"}` | 侧边栏抖音指示灯变 ⏳ 加载动画，登录页状态显示"连接中..." |
| TC-A002 | `{"platform":"douyin"}` (缺 auto_reply) | 200 | `{"ok":true}` (默认 auto_reply=true) | 同上 |
| TC-A003 | `{"platform":"invalid"}` | 400 | `{"error":"platform_not_found"}` | Godot Toast 弹窗 "平台不存在" |
| TC-A004 | `{}` (缺 platform) | 400 | `{"error":"validation_error","detail":"platform is required"}` | Godot Toast "参数错误" |
| TC-A005 | `{"platform":"douyin"}` 无 Cookie | 200→WS推送 | `{"ok":true}` → 3秒后 WS `event:platform_status` status="error" | 侧边栏变 ❌，"请先扫码登录" |

### 11.2 扫码登录（POST /api/login/scan）

| 用例 ID | 输入 | 预期 HTTP | 预期 WS 事件序列 | 预期 UI |
|------|------|:---:|------|------|
| TC-L001 | `{"platform":"douyin"}` | 200 | `qr_code` (2-5s内) → 用户扫码 → `login_ok` | 弹窗显示二维码→扫码后2秒窗口关闭，登录页显示"已保存✓" |
| TC-L002 | `{"platform":"bilibili"}` | 200 | 同上 | 同上 |
| TC-L003 | 扫码超时 160 秒 | 200 | `qr_code` → 160s后 `login_fail` `{"reason":"timeout"}` | 弹窗自动关闭，**Toast "扫码超时，请重试"** |
| TC-L004 | 正在扫码中再发一次请求 | 400 | 无新 WS | **Toast "该平台正在扫码中，请等待"** |
| TC-L005 | Playwright 崩溃（无 Chromium） | 200→WS | `login_fail` `{"reason":"browser_error"}` | **弹窗关闭** + 红色 Toast "浏览器启动失败，请运行 playwright install chromium" |

### 11.3 发送消息（POST /api/message/send）

| 用例 ID | 输入 | 预期 HTTP | 预期响应 | 预期 UI |
|------|------|:---:|------|------|
| TC-M001 | `{"session_id":"douyin:...","text":"你好"}` | 200 | `{"ok":true}` | 消息气泡追加到聊天窗，输入框清空 |
| TC-M002 | `{"session_id":"douyin:...","text":""}` | 400 | `{"error":"validation_error"}` | 输入框不变，Toast "消息不能为空" |
| TC-M003 | `{"session_id":"","text":"xxx"}` | 400 | `{"error":"validation_error"}` | Toast "会话 ID 不能为空" |
| TC-M004 | 发送到未连接的平台 | 400 | `{"error":"platform_offline"}` | Toast "[平台名] 未连接，请先监听" |
| TC-M005 | 30 秒内连续发第 4 条 | 400 | `{"error":"rate_limited"}` | Toast "发送过于频繁，请稍候" + 输入框恢复 |
| TC-M006 | Cookie 过期后发送 | 400 | `{"error":"auth_expired"}` | **Toast "[平台名] Cookie 已过期" + 登录页对应平台红色提示** |

### 11.4 AI 主动消息（POST /api/ai/active）

| 用例 ID | 输入 | 预期 HTTP | 预期 WS 事件序列 | 预期 UI |
|------|------|:---:|------|------|
| TC-AI001 | `{"session_id":"douyin:..."}` | 200 | `ai_stream` × N 次 chunk 追加 → 最后一条 `done:true` | AI 按钮变灰"生成中..."→气泡逐字显示→结束后按钮恢复绿色 |
| TC-AI002 | DeepSeek API Key 未配置 | 500 | 无 WS 流 | Toast "API Key 未配置，请在 AI 设置页填写" |
| TC-AI003 | DeepSeek 网络超时 | 500 | 无 WS 流 | Toast "AI 服务超时，请检查网络" + 按钮恢复 |

### 11.5 通讯录（GET /api/sessions）

| 用例 ID | 输入 | 预期 HTTP | 预期响应 | 预期 UI |
|------|------|:---:|------|------|
| TC-S001 | 无参数 | 200 | `{"sessions":[...]}` | 通讯录列表按 `last_time` 降序排列 |
| TC-S002 | `?platform=douyin` | 200 | 仅抖音会话 | 列表只显示抖音联系人 |
| TC-S003 | 后端未启动（Godot 定时轮询时） | — | HTTP 超时 | 列表显示占位："后端未启动" + 重试按钮 |
| TC-S004 | 0 个会话 | 200 | `{"sessions":[]}` | 通讯录显示空状态插画"暂无对话" |

### 11.6 设置（GET/PUT /api/config）

| 用例 ID | 输入 | 预期 HTTP | 预期响应 | 预期 UI |
|------|------|:---:|------|------|
| TC-C001 | GET | 200 | 完整 config JSON | 设置页各控件显示当前值 |
| TC-C002 | `PUT {"theme":"light"}` | 200 | `{"ok":true}` | 全局 UI 瞬间切换浅色主题 |
| TC-C003 | `PUT {"invalid_key":"x"}` | 400 | `{"error":"invalid_field"}` | Toast "未知配置项: invalid_key" |
| TC-C004 | `PUT {"temperature":3.0}` | 400 | `{"error":"validation_error","detail":"temperature must be 0-2"}` | Toast "temperature 取值范围 0-2" |

### 11.7 性能监控（GET /api/perf/snapshot + WS perf 推送）

| 用例 ID | 输入 | 预期 | 预期 UI |
|------|------|------|------|
| TC-P001 | Godot 打开性能页 | WS 每秒收到 perf 事件 | 折线图实时刷新，数值标签更新 |
| TC-P002 | 性能页切走（隐藏） | WS perf 事件仍然到达 | 图表节点 `queue_redraw()` 被抑制（Godot 自动跳过不可见节点的绘制） |
| TC-P003 | 后端崩溃 | WS 断开 | 图表数据冻结，显示"已断开"遮罩层 |

---

## 12. 失败场景与降级策略

### 12.1 网络超时

**触发条件**: 任意 HTTP 请求 5 秒内无响应。

**系统行为**:
```
Godot API.gd:
  HTTPRequest.timeout = 5.0
  超时 → 显示 Toast "网络请求超时，正在重试..."
  → 每 3 秒重试一次，最多 3 次
  → 3 次全部失败 → Toast "无法连接到后端，请检查 DMShoot 服务是否运行"
  → 通讯录列表显示离线提示
```

**WebSocket 超时**:
```
WSClient.gd:
  5 秒没收到 heartbeat → 主动关闭 WebSocket
  → AppState 全局标记 backend_connected = false
  → 所有页面顶部显示红色横幅"后端已断开，正在重连..."
  → 每 2 秒尝试重连（指数退避: 2→4→8→16→30s，截断 30s）
  → 重连成功 → 横幅消失，自动拉取最新状态（GET /api/adapter/status + GET /api/sessions）
```

### 12.2 后端崩溃

**触发条件**: Python 进程异常退出（segfault / uncaught exception / OOM）。

**系统行为**:
```
Launcher.exe:
  subprocess.Popen 时设置监控线程
  → 检测到 backend.exe 退出码 ≠ 0
  → 自动重启 backend.exe（最多 3 次）
  → 3 次全部崩溃 → 弹窗 "后端服务异常，DMShoot 将关闭" → Launcher 退出

Godot 端:
  WS 断开 → 同 12.1 的行为
  → 如果 60 秒内未能重连 → 显示 "后端无响应，可能已崩溃" 
  → 用户可点击"重启后端"按钮 → 通过 Launcher 重新拉起
```

### 12.3 数据库断连

**触发条件**: SQLite 文件被删除 / 磁盘满 / WAL 损坏。

**系统行为**:
```
后端 routes.py:
  try: database.get_session()
  except OperationalError as e:
    → HTTP 500 { "error": "database_error", "detail": str(e) }
    → 同时 WS 推送 { "event": "system_error", "type": "database" }

Godot:
  → 收到 500 → Toast "数据库异常，请检查磁盘空间或运行工具修复"
  → WS 收到 system_error → 设置页显示红色警告横幅
```

**恢复策略**:
```
数据库检测到 WAL 文件损坏 → 自动执行:
  1. 关闭所有写操作
  2. 调用 tools/wal_checkpoint.py --force
  3. 如果恢复失败 → 从 dmshoot.db.bak 恢复（如果有）
  4. 如果备份也不存在 → 创建新数据库，记录到 log
```

### 12.4 认证过期

**触发条件**: Cookie 过期被平台返回 -101 / 401。

**系统行为**:
```
后端 adapter.py send_message():
  API 返回 -101
  → raise AuthExpiredError(platform, "Cookie 已过期")
  → routes.py 捕获 → HTTP 400 { "error": "auth_expired" }
  → 同时 WS 推送 { "event": "platform_status", "platform": "douyin", "status": "error", "detail": "Cookie 已过期" }

Godot:
  → HTTP 400 → Toast "[平台名] 登录已过期"
  → WS 推送 → 侧边栏对应平台变 ❌
  → 登录页对应平台的"自动登录"checkbox 被取消
  → 平台连接状态文字变红 "Cookie 已过期，请重新扫码"
```

### 12.5 参数校验失败

**触发条件**: 用户输入不合法、客户端 bug 导致发错字段。

**系统行为**:
```
后端:
  Pydantic BaseModel 自动校验
  → HTTP 422 / 400
  → Response body:
    {
      "error": "validation_error",
      "detail": [{"loc": ["body","text"], "msg": "field required"}]
    }

Godot API.gd (封装层):
  → 拦截所有 4xx 响应
  → 解析 detail 数组
  → 拼接为可读文案: "text: field required"
  → Toast 显示完整错误信息
  → 不会 crash，不会白屏
```

### 12.6 Godot 端错误边界

| 场景 | 行为 |
|------|------|
| GDScript 运行时错误 (null access) | `push_error()` 写入 Godot 日志，UI 继续渲染（Godot 不会崩整个进程） |
| HTTP 响应 JSON 解析失败 | `API.gd` fallback: 显示 "服务器返回异常数据" |
| 一张图片 load 失败 | TextureRect 不显示，不影响其他 UI |
| WS 收到未知 event 类型 | 静默忽略，写 WARN 日志 |
| 内存不足 | Godot 自动调用 `queue_free()` 释放未使用资源 |

---

## 13. 日志规范

### 13.1 日志级别定义

| 级别 | 使用场景 | 示例 |
|------|------|------|
| **DEBUG** | 开发调试，生产默认关闭 | 请求原始参数、中间计算结果 |
| **INFO** | 关键操作节点 | 请求到达、适配器启动、消息发送成功 |
| **WARN** | 可恢复的异常 | 重试、降级、Cookie 即将过期（提前 1h 预警） |
| **ERROR** | 需要人工关注 | API 失败、数据库异常、第三方服务不可用 |

### 13.2 日志字段规范

每条日志必须包含以下字段（后端使用 `logging` 模块的 `extra` 或结构化 JSON）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `req_id` | string | 请求唯一 ID（UUID4，从 HTTP 中间件注入） |
| `platform` | string | 涉及平台，无则填 `"system"` |
| `op` | string | 操作类型: `"adapter_start"\|"msg_send"\|"ai_gen"\|"login"\|"db_write"` |
| `uid` | string | 涉及用户 UID，无则填 `"0"` |
| `latency_ms` | number | 操作耗时（毫秒） |
| `timestamp` | string | ISO 8601 格式 `2026-06-26T19:20:00.000+08:00` |

### 13.3 日志格式模板

```python
# 后端统一日志格式
logger.info(
    "[%s] platform=%s op=%s uid=%s latency=%dms | %s",
    req_id, platform, op, uid, latency_ms, message,
    extra={"req_id": req_id, "platform": platform, "op": op, "uid": uid}
)
```

### 13.4 各模块日志示例

**适配器启动 (INFO)**
```
2026-06-26T19:20:01.234+08:00 INFO  dmshoot.api.routes
  [rq_a1b2c3d4] platform=douyin op=adapter_start uid=0 latency=0ms | 正在启动 douyin 适配器 (auto_reply=True)
```

**适配器启动成功 (INFO)**
```
2026-06-26T19:20:03.567+08:00 INFO  dmshoot.api.routes
  [rq_a1b2c3d4] platform=douyin op=adapter_start uid=7581349050324026405 latency=2333ms | douyin 适配器已启动, 昵称=柁炑炑
```

**消息发送成功 (INFO)**
```
2026-06-26T19:22:10.890+08:00 INFO  dmshoot.api.routes
  [rq_e5f6g7h8] platform=douyin op=msg_send uid=1028742494552135 latency=3200ms | 消息已发送, 长度=18
```

**消息发送失败 (ERROR)**
```
2026-06-26T19:22:15.123+08:00 ERROR dmshoot.api.routes
  [rq_e5f6g7h8] platform=douyin op=msg_send uid=1028742494552135 latency=520ms | 发送失败: auth_expired
  Traceback (most recent call last):
    ...
    dmshoot.core.adapter.AuthExpiredError: Cookie 已过期
```

**API 请求到达 (INFO)**
```
2026-06-26T19:21:00.001+08:00 INFO  dmshoot.api.middleware
  [rq_i9j0k1l2] platform=system op=http_request uid=0 latency=0ms | POST /api/message/send from 127.0.0.1
```

**API 请求完成 (INFO)**
```
2026-06-26T19:21:00.050+08:00 INFO  dmshoot.api.middleware
  [rq_i9j0k1l2] platform=system op=http_request uid=0 latency=49ms | 200 OK (49ms)
```

**数据库写入 (DEBUG)**
```
2026-06-26T19:22:10.891+08:00 DEBUG dmshoot.storage.database
  [rq_e5f6g7h8] platform=douyin op=db_write uid=1028742494552135 latency=1ms | INSERT chat_message (msg_hash=a3f8...)
```

**数据库异常 (ERROR)**
```
2026-06-26T19:25:00.000+08:00 ERROR dmshoot.storage.database
  [rq_m3n4o5p6] platform=system op=db_write uid=0 latency=0ms | SQLite operational error: database is locked
```

**AI 生成完成 (INFO)**
```
2026-06-26T19:23:45.678+08:00 INFO  dmshoot.ai.backend
  [rq_q7r8s9t0] platform=douyin op=ai_gen uid=1028742494552135 latency=5600ms | tokens=4708 model=deepseek-v4-flash
```

**WebSocket 重连 (WARN)**
```
2026-06-26T19:30:00.000+08:00 WARN  dmshoot.api.ws_bridge
  [rq_---] platform=system op=ws_reconnect uid=0 latency=0ms | WebSocket 客户端断开，30秒内第2次重连
```

**登录扫码开始 (INFO)**
```
2026-06-26T19:20:00.000+08:00 INFO  dmshoot.api.routes
  [rq_u1v2w3x4] platform=douyin op=login uid=0 latency=0ms | 启动扫码登录, Playwright 浏览器已打开
```

---

## 14. 部署检查清单

### 14.1 环境变量

- [ ] `DMSHOOT_PORT` — 后端 HTTP 端口，默认 `9876`，不与已运行服务冲突
- [ ] `DMSHOOT_DATA_DIR` — 数据库目录，默认 `./data/`，确保有读写权限
- [ ] `DMSHOOT_LOG_LEVEL` — 日志级别，生产设为 `INFO`，调试可临时改 `DEBUG`
- [ ] `DEEPSEEK_API_KEY` — AI Key，必须配置（不配置则 AI 功能不可用）
- [ ] (可选) `NODE_PATH` — 手动指定 Node.js 路径，留空则自动发现

### 14.2 依赖版本

- [ ] Python `3.12.x`（与开发环境一致，避免 pyinstaller 兼容问题）
- [ ] `fastapi==0.115.*`（API 框架）
- [ ] `uvicorn==0.34.*`（ASGI 服务器）
- [ ] `playwright==1.60.*` + `playwright install chromium`（浏览器已安装）
- [ ] `requests==2.31.*`（http client）
- [ ] `cryptography==48.*`（签名）
- [ ] `PySide6>=6.5`（仅旧版需要，Godot 版可选）
- [ ] PyInstaller `6.21.*`（打包工具）
- [ ] Godot Engine `4.5`（Godot 前端需要）

### 14.3 数据库

- [ ] 首次运行自动创建 `data/dmshoot.db`（SQLite）
- [ ] WAL 模式已启用（`database.py` 初始化时自动执行）
- [ ] `wal_autocheckpoint=200` 已设置
- [ ] 无旧版配置文件残留（v0.2.0 升级需迁移）
- [ ] 备份：确保 `tools/wal_checkpoint.py` 可执行

### 14.4 网络

- [ ] 防火墙放行 `127.0.0.1:9876`（仅本地回环，不需外部访问）
- [ ] 代理设置：如果使用系统代理，确保 `127.0.0.1` 不走代理（NoProxy）
- [ ] DeepSeek API 可达：`curl -I https://api.deepseek.com` 返回 200

### 14.5 Godot 导出配置

- [ ] `display/window/size/viewport_width` = `960`
- [ ] `display/window/size/viewport_height` = `680`
- [ ] `display/window/size/resizable` = `true`
- [ ] `application/config/name` = `"DMShoot"`
- [ ] `application/config/icon` = `res://assets/tujue.ico`
- [ ] 导出模板：Windows Desktop (Runnable)，**不要勾选** "Embed Pck"

### 14.6 启动测试

- [ ] `Launcher.exe` 双击能启动后端（任务管理器可见 `backend.exe`）
- [ ] `backend.exe` 启动后 3 秒内 HTTP `200` on `/api/health`
- [ ] `Godot.exe` 启动后 2 秒内 WS 连接成功
- [ ] 关闭 Godot 窗口 → `backend.exe` 也自动退出
- [ ] 重启后端 → Godot 自动重连（无需手动刷新）

### 14.7 回滚方案

- [ ] 保留旧版 PySide6 `main.py`（不删除，不覆盖）
- [ ] Git tag `v0.2.0-legacy` 指向最后一个 PySide6 版本
- [ ] 旧版 exe 备份：`DMShoot-v0.2.0.exe` 保存在 release assets
- [ ] 若 Godot 版严重 bug → 用户可下载 `v0.2.0` 继续使用
- [ ] 数据库向后兼容：Godot 版不修改 schema，可直接被 PySide6 版读取

### 14.8 监控与告警

- [ ] 后端健康检查端点：`GET /api/health` → `{"ok":true,"uptime":12345}`
- [ ] Godot 端心跳日志：每 30 秒打印一次 `WS heartbeat OK`
- [ ] 崩溃监控：`backend.exe` 退出码 ≠ 0 时 `Launcher.exe` 写 `crash.log`
- [ ] (可选) 集成 Sentry 或自定义 webhook 上报 ERROR 日志

### 14.9 分发前自测

- [ ] 新安装流程：解压 zip → 双击 `Launcher.exe` → Godot 窗口出现 → 扫码登录 → 发一条消息
- [ ] 从 v0.2.0 升级：旧版数据库被新版识别，会话列表正常加载
- [ ] 断网测试：拔网线 → Godot 显示"后端已断开" → 插回网线 → 自动恢复
- [ ] 杀后端测试：任务管理器结束 `backend.exe` → Launcher 自动重启 → Godot 自动重连
- [ ] 长时间运行：挂机 2 小时无内存泄漏（内存增长 < 10MB）

### 14.10 文档交付

- [ ] README.md 更新下载链接为 v0.3.0
- [ ] 用户手册：扫码登录步骤截图
- [ ] 故障排查：常见错误码对照表（-101 / auth_expired / rate_limited ...）
- [ ] API 文档：本文件 §2 的内容同步到 Godot 项目内的 `API_REFERENCE.md`

---

## 15. 文档变更记录

| 版本 | 日期 | 修改人 | 修改内容 | 修改原因 |
|------|------|------|------|------|
| v1.0 | 2026-06-26 | 助手 | 初稿：架构对比、API 设计、时间估算、风险分析 | 立项可行性评估 |
| v1.1 | 2026-06-26 | 助手 | 补充 §5 性能监控图表方案 | 明确 Godot 手绘替代 QPainter 的可行性 |
| v1.2 | 2026-06-26 | 助手 | 新增 §11 验收用例（7 模块 25 条用例） | 定义交付标准 |
| v1.2 | 2026-06-26 | 助手 | 新增 §12 失败场景（6 场景含降级策略） | 明确系统容错边界 |
| v1.2 | 2026-06-26 | 助手 | 新增 §13 日志规范（4 级别 + 6 字段 + 11 示例） | 统一前后端日志格式 |
| v1.2 | 2026-06-26 | 助手 | 新增 §14 部署检查清单（10 类 45 检查项） | 生产就绪交付标准 |
| v1.2 | 2026-06-26 | 助手 | 新增 §15 文档变更记录 | 文档版本管理 |

---

> **文档状态**: 待评审  
> **下一步**: 用户确认方案可行 → 启动 MVP 开发（§10 第一步）  
> **关联文档**: `docs/WAL_CHECKPOINT_SOLUTION.md`, `DEV_NOTES.md`
