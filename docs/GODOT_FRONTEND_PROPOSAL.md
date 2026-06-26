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
