# DMShoot Godot 前端方案可行性分析

## 1. 架构对比

```
当前架构（同进程）：
┌──────────────────────────────────┐
│          Python 3.12             │
│  ┌────────────┐  ┌────────────┐  │
│  │ PySide6 GUI│←→│  后端逻辑   │  │  Qt Signal/直接调用
│  └────────────┘  │ · Adapter   │  │
│                  │ · AI        │  │
│                  │ · Storage   │  │
│                  └────────────┘  │
└──────────────────────────────────┘

目标架构（双进程，HTTP/WebSocket）：
┌──────────────┐     JSON      ┌──────────────────────┐
│ Godot 4.5    │ ←────HTTP───→ │  Python 后端 (FastAPI)│
│ · 登录页     │               │ · Adapter (不用动)    │
│ · 聊天页     │ ←──WebSocket→ │ · AI (不用动)         │
│ · 设置页     │    实时推送    │ · Storage (不用动)    │
│ · 通讯录     │               │ · Playwright (不用动)  │
│ · 提示词     │               │ · DouYin Spiders (不动)│
└──────────────┘               └──────────────────────┘
            Godot.exe                Backend.exe
             ~30MB                    ~40MB (pyinstaller)
```

**关键原则：后端一行 Python 不用改，只给 MessageBus 加一个 WebSocket 出口。**

---

## 2. 后端改造（main_headless.py）

### 2.1 新增依赖
```
fastapi>=0.115
uvicorn>=0.34
python-socketio>=5.12    # WebSocket 替代 bus.Signal
```

### 2.2 API 设计（15 个端点）

#### 连接管理
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/adapter/start` | 启动平台监听 `{platform, cookie}` |
| POST | `/api/adapter/stop` | 停止平台监听 `{platform}` |
| GET  | `/api/adapter/status` | 所有平台连接状态 |

#### 登录
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/login/scan` | 触发扫码，通过 WS 推送 QR 图 |
| POST | `/api/login/cancel` | 取消扫码 |

#### 消息
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/sessions` | 通讯录会话列表 |
| GET  | `/api/messages/{session_id}` | 历史消息 `?limit=50&before=ts` |
| POST | `/api/message/send` | 发送消息 `{session_id, text}` |
| POST | `/api/ai/active` | AI 主动生成消息 `{session_id}` |

#### 设置
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/config` | 读取配置 |
| PUT  | `/api/config` | 更新配置 `{key: value, ...}` |
| GET  | `/api/prompts` | 提示词列表 |
| PUT  | `/api/prompts` | 更新/添加提示词 |

#### AI
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/ai/test` | 测试 AI 连通性 |

### 2.3 WebSocket 事件（实时推送）

```
ws://localhost:9876/ws

客户端 ← 服务端推送：
{
  "event": "message",         // 新私信
  "platform": "douyin",
  "data": { session_id, sender_name, content, timestamp, avatar }
}

{
  "event": "platform_status", // 连接状态变化
  "platform": "douyin",
  "data": { status: "online"|"offline"|"error", detail: "..." }
}

{
  "event": "qr_code",         // 扫码二维码
  "platform": "douyin",
  "data": { b64: "data:image/png;base64,..." }
}

{
  "event": "login_ok",        // 登陆成功
  "platform": "douyin"
}

{
  "event": "ai_stream",       // AI 回复流
  "session_id": "...",
  "chunk": "文字片段...",
  "done": false
}

{
  "event": "log",             // 终端日志（可选）
  "level": "INFO",
  "module": "douyin",
  "message": "..."
}
```

客户端向服务端发送：
```json
{"action": "ping"}
{"action": "typing", "session_id": "..."}
```

### 2.4 实现估算

| 文件 | 行数 | 难度 |
|------|:---:|:---:|
| `main_headless.py` | ~80 | 低 |
| `dmshoot/api/__init__.py` | ~20 | 低 |
| `dmshoot/api/routes.py` | ~250 | 中 |
| `dmshoot/api/ws_bridge.py` | ~150 | 中 |
| `dmshoot/api/models.py` | ~60 | 低 |
| 修改 `dmshoot/core/bus.py` | ~20 | 低 |
| **合计** | **~580** | |

WS 桥接的核心就是把 MessageBus 的 6 个 Signal 映射到 WebSocket 事件——改动极小。

---

## 3. Godot 前端

### 3.1 页面清单（需还原的 PySide6 页面）

| 页面 | 复杂度 | 主要组件 |
|------|:---:|------|
| 登录页 | 高 | 平台选择、扫码弹窗、状态指示、一键提取、重新扫码 |
| 聊天首页 | 高 | 通讯录列表、聊天气泡、输入框、分隔线、AI按钮 |
| AI 设置页 | 中 | API Key、模型选择、温度、上下文轮数 |
| 提示词管理 | 中 | 列表、编辑区、角色/行为预设 |
| 设置对话框 | 中 | 主题、限速、回复延迟、平台开关 |
| 侧边栏 | 低 | 连接状态图标、导航按钮 |
| 性能监控 | 中 | 折线图、饼图（Godot 内置 Chart 或画） |
| 标题栏 | 低 | 窗口拖拽、最小化/关闭 |

### 3.2 Godot 需要引入的外部能力

| 能力 | 方案 | 可用性 |
|------|------|:---:|
| HTTP 请求 | Godot 内置 `HTTPRequest` 节点 | ✅ |
| WebSocket | Godot 内置 `WebSocketClient` | ✅ |
| JSON 解析 | Godot 内置 `JSON.new()` | ✅ |
| 二维码显示 | 自绘或嵌 Base64 PNG 到 TextureRect | ✅ |
| Markdown 渲染 | 需社区插件或自写解析器 | ⚠️ |
| 富文本聊天气泡 | `RichTextLabel` (支持 BBCode) | ✅ |
| 文件选择 | Godot 内置 `FileDialog` | ✅ |
| 窗口最小化/关闭 | Godot 内置 `DisplayServer` | ✅ |
| 系统托盘 | 需 GDExtension 或命令行工具 | ⚠️ |
| Emoji 渲染 | 系统字体支持，需测试 | ⚠️ |
| 中文字体 | 打包思源黑体 4MB | ✅ |

### 3.3 无法直接在 Godot 实现的功能

| 功能 | 当前 PySide6 实现 | Godot 替代方案 |
|------|------|------|
| 壁纸更换 | QFileDialog → setStyleSheet | Godot FileDialog → TextureRect |
| 窗口圆角/透明 | Qt.WA_TranslucentBackground | Godot 4.x 支持 `transparent_bg` |
| 系统托盘 | QSystemTrayIcon | ❌ Godot 无内置，需第三方扩展 |
| Playwright 浏览器 | QThread + asyncio | 后端处理，前端只显示状态 |
| Markdown 渲染 | markdown 库 | 社区插件 markdown-label 或自写 |

---

## 4. 时间估算

### 阶段 1：后端 API 层（3 天）

| 任务 | 预估 |
|------|:---|
| FastAPI + WebSocket 框架搭建 | 半天 |
| 15 个 REST 端点实现 | 1 天 |
| MessageBus → WebSocket 桥接 | 1 天 |
| 测试 & 调试 | 半天 |

### 阶段 2：Godot 前端（12 天）

| 任务 | 预估 |
|------|:---|
| 项目搭建 + 主题系统 + 导航架构 | 1 天 |
| 登录页（扫码 + QR 显示 + 状态） | 2 天 |
| 聊天页（通讯录 + 气泡 + 输入框 + 滚动） | 2.5 天 |
| AI/提示词设置页 | 1.5 天 |
| 设置对话框 | 1 天 |
| 侧边栏 + 标题栏 | 0.5 天 |
| 性能监控页 | 1 天 |
| 动画/交互细节（分隔线、消息滑入、主题切换） | 1 天 |
| 适配 & 边界测试 | 1.5 天 |

### 阶段 3：打包 & 发布（1 天）

| 任务 | 预估 |
|------|:---|
| Godot 导出 Windows .exe（30-40MB） | 半天 |
| Python 后端 PyInstaller 打包（40MB） | 之前已做好 |
| 合并为 release zip | 半天 |

**总计：约 16 个工作日（3 周）**

---

## 5. 风险和阻碍

### 🔴 高风险

| 风险 | 说明 |
|------|------|
| **Markdown 聊天渲染** | QQ/TG 风格的富文本聊天气泡在 Godot 里需要自写解析器。Godot `RichTextLabel` 支持 BBCode，但 Markdown→BBCode 需要转换层。社区插件质量参差不齐。 |
| **滚动性能** | 几百条消息的聊天列表，Godot 的 `ScrollContainer` 在大量子节点时可能卡顿，需要虚拟列表优化。 |
| **你从未用过 Godot** | 学习 GDScript + Godot 节点系统 + 信号机制至少 3 天熟悉阶段。 |

### 🟡 中风险

| 风险 | 说明 |
|------|------|
| **双向通信延迟** | HTTP/WS 跨进程比同进程 Qt Signal 多 1-10ms 延迟，对聊天应用无感知 |
| **窗口多实例** | 如果用户开了多个聊天窗口/弹出监控 —— Godot 的 `Window` 节点可以，但跨窗口状态共享需要设计 |
| **主题系统** | Godot Theme 系统不如 CSS/QSS 灵活，深色/浅色切换需要手动管理两个 Theme 文件 |

### 🟢 低风险

| 风险 | 说明 |
|------|------|
| **分布体积** | Godot 导出 ~30MB + Python 后端 ~40MB = ~70MB，比现在 150MB 减半 |
| **跨平台** | Godot 原生 Windows/Mac/Linux 导出，Python 后端 PyInstaller 跟着走 |

---

## 5. 性能监控图表

### 5.1 当前实现

`dmshoot/gui/widgets/perf_chart.py` (~500 行)，纯 QPainter 手绘：

| 图表类型 | 数据来源 | 效果 |
|------|------|------|
| 折线图 (×3) | CPU / 内存 / 消息吞吐量 | 60 秒时间窗口，带渐变色填充 |
| 饼图 | 事件分类统计 | 彩色扇区 + 中心文字 |
| 柱状图 | 线程池各 worker 负载 | 彩色柱 + 标签 |

5 套配色主题可切换。

### 5.2 Godot 替代方案对比

| 方案 | 开发量 | 效果 |
|------|:---:|------|
| **A: 纯手绘 (推荐)** | 1 天 | 用 `draw_polyline`/`draw_rect`/`draw_circle` 复刻当前效果，比 QPainter 更简单 |
| **B: Chart.js 嵌入** | 0.5 天 | Godot 4.x 无内置 WebView，需要加 CEF 扩展，反而更重 |
| **C: 社区插件** | 0.3 天 | [godot-chart](https://github.com/...) 等插件可用，但灵活性受限 |

**推荐方案 A**：用 Godot 的 `_draw()` 回调手绘折线图+饼图，1 天足够。Godot 的 2D 绘制 API 比 QPainter 更直觉——没有 QPen/QBrush/QPainterPath 那些 C++ 层的抽象，直接调 `draw_line(from, to, color, width)`。5 套配色主题直接用 Godot Theme 变量切换。

### 5.3 数据流

```
perf_monitor.py (现有，不动)
    → WS 每秒推送 {cpu, memory, msg_rate, events_breakdown}
    → Godot GodotPerfChart.gd
        → _draw() 渲染图表
        → 动画：Tween.interpolate_value(point_a, point_b, duration)
```

比 QPropertyAnimation + QEasingCurve 更简单。

---

## 6. 和当前 PySide6 方案的对比

| 维度 | PySide6（当前） | Godot + FastAPI（新） |
|------|:---:|:---:|
| 打包体积 | 150MB | ~70MB |
| 启动速度 | 3-5 秒 | 2-4 秒 |
| UI 灵活度 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 动画效果 | QPropertyAnimation，有限 | 内置 Tween 系统，强 |
| 图表渲染 | QPainter 手绘 500 行 | Godot `_draw()` 手绘 ~300 行 |
| 开发效率（已知） | 已经在用 | 需学习 GDScript |
| 聊天窗口性能 | Qt，稳定 | 需验证 |
| 技术债 | 累积中（MainWindow God Object） | 零（从头写） |
| 维护 | 1 个 Python 项目 | 1 个 Python 项目 + 1 个 Godot 项目 |
| 社区生态 | Qt 成熟 | Godot GUI 小众但官方文档好 |

---

## 7. 建议的执行路径

### 第一步：验证关键风险（3 天）

**不要一开始就全面开工。** 先做一个最小 MVP：

```
MVP 目标：
1. 后端 main_headless.py（FastAPI + WS）
2. Godot 启动时自动连上后端
3. Godot 显示一个通讯录列表（从 /api/sessions 拉）
4. 点击联系人，显示历史消息（从 /api/messages 拉）
5. 能发一条消息（POST /api/message/send）
```

如果 MVP 在 2-3 天内能跑通，说明这条路可行。如果卡在 Markdown 渲染或滚动性能，说明 Godot 不适合这个场景。

### 第二步：完整开发（按阶段 2 估算，12 天）

MVP 过了就全速推进。旧 PySide6 代码保留在 `main.py`，两个入口并行，互不影响。

### 第三步：切换 & 废弃（1 天）

确认新版本稳定后，把 `main.py` 标记为 legacy，正式切换到 Godot 前端。

---

## 8. 结论

**可行。** 最坏情况是 MVP 3 天失败——代价很低，不会影响当前 PySide6 版本。最大的不确定性不是代码量，而是 Godot 的聊天渲染能不能达到 Qt 的水平。

建议先做 MVP，别一口气全换。3 天就能知道这个决定对不对。
