# DMShoot 技术栈详解与学习路线

> 文档生成日期：2026-06-22 | 基于 DMShoot 源码全量审计

---

## 目录

1. [项目概述](#1-项目概述)
2. [完整技术栈清单](#2-完整技术栈清单)
3. [五层架构详解](#3-五层架构详解)
4. [并发模型详解](#4-并发模型详解)
5. [数据持久化方案](#5-数据持久化方案)
6. [各平台协议逆向](#6-各平台协议逆向)
7. [跨语言通信方案](#7-跨语言通信方案)
8. [设计模式应用](#8-设计模式应用)
9. [学习路线图](#9-学习路线图)
10. [关键文件索引](#10-关键文件索引)

---

## 1. 项目概述

DMShoot 是一个基于 **PySide6** 的多平台私信聚合桌面应用，支持以下四个平台：

| 平台 | 状态 | 通信方式 | 登录方式 |
|------|------|---------|---------|
| 抖音 | ✅ 完整支持 | WebSocket (protobuf) + HTTP | Playwright 扫码 |
| B站 | ✅ 完整支持 | HTTP (bilibili-api SDK) | Playwright 扫码 |
| 小红书 | ⚠️ 部分支持 | HTTP (JS 签名 + API) | Playwright 扫码 |
| 快手 | ❌ 仅登录 | Web 端不支持私信 | Playwright 扫码 |

核心功能：
- 四平台私信聚合到一个聊天界面
- DeepSeek API 驱动的 AI 自动回复（支持多角色切换）
- 扫码登录 + Cookie 持久化
- 双防线消息去重（DB 唯一索引 + 内存 set）
- 断线重连 + 速率限制
- 实时性能监控（CPU/内存/线程数）

---

## 2. 完整技术栈清单

### 2.1 核心运行时

| 运行时 | 版本 | 用途 |
|--------|------|------|
| Python | 3.12+ | 主体语言，GUI + 业务逻辑 + AI |
| Go | 1.22 | 可选的消息服务后端（Gin HTTP + SQLite） |
| Node.js | 22 | JS 签名引擎（抖音 a_bogus + 小红书 x-s） |

### 2.2 Python 依赖

| 依赖 | 版本 | 用途 | 重要性 |
|------|------|------|--------|
| `PySide6` | >=6.5 | Qt for Python GUI 框架 | ★★★★★ |
| `httpx` | >=0.27 | 异步 HTTP 客户端（各平台 API + DeepSeek） | ★★★★★ |
| `bilibili-api-python` | >=17.4 | B站官方风格 Python SDK | ★★★★ |
| `playwright` | >=1.60 | 浏览器自动化（扫码登录 Cookie 提取） | ★★★★ |
| `websocket-client` | >=1.8 | WebSocket 客户端（抖音 IM 实时推送） | ★★★★ |
| `cryptography` | >=48.0 | ECDSA 签名（抖音 req_sign） | ★★★★ |
| `psutil` | >=5.9 | 进程 CPU/内存/线程监控 | ★★★ |
| `markdown` | >=3.7 | Markdown 转 HTML（聊天气泡渲染） | ★★★ |
| `urllib3` | >=2.0 | HTTP 连接池（DouYin_Spider SDK 使用） | ★★ |
| `PyYAML` | >=6.0 | YAML 配置解析（bilibili-api 内部依赖） | ★★ |
| `requests` | >=2.31 | 同步 HTTP（DouYin_Spider SDK 使用） | ★★ |

### 2.3 Go 依赖

| 模块 | 用途 |
|------|------|
| `github.com/gin-gonic/gin` v1.10 | HTTP 框架，提供 REST API 端点 |
| `github.com/gorilla/websocket` v1.5 | WebSocket，向 Python 广播变更 |
| `modernc.org/sqlite` v1.34 | 纯 Go SQLite 驱动（无 CGO） |

### 2.4 Node.js 依赖

| 包 | 位置 | 用途 |
|----|------|------|
| `jsrsasign` | `external/DouYin_Spider/node_modules/` | 抖音 JS 签名辅助 |
| `crypto-js` | `dmshoot/plugins/xiaohongshu/static/node_modules/` | 小红书签名 JS |

### 2.5 测试依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `pytest` | >=7.0 | 测试框架 |
| `pytest-qt` | >=4.4 | Qt GUI 测试支持 |
| `pytest-html` | >=4.0 | HTML 测试报告 |

### 2.6 外部 SDK

| 模块 | 路径 | 集成方式 |
|------|------|---------|
| DouYin_Spider | `external/DouYin_Spider/` | Monkey-patch 替换 `execjs` 依赖 |

---

## 3. 五层架构详解

```
┌─────────────────────────────────────────────────────────────┐
│ L1  展示层 — PySide6 / Qt6                                   │
│     QMainWindow · QStackedWidget · Signal/Slot · QSS 样式   │
│     4 页面 · 5 Widget · 2 Worker 线程 · 10KB styles.qss     │
├─────────────────────────────────────────────────────────────┤
│ L2  核心层 — 事件总线 · 并发 · 服务                            │
│     MessageBus · ConcurrencyMgr · GoServiceBridge            │
│     BaseAdapter(QThread) · RateLimiter · PerfMonitor         │
│     AdaptivePoller · MessageService · AIBackend              │
├─────────────────────────────────────────────────────────────┤
│ L3  平台适配层 — 多端社交私信逆向                              │
│     Douyin(WS+Protobuf) · Bilibili(SDK+HTTP)                │
│     XHS(JS签名+HTTP) · Kuaishou(Web-不可用)                  │
│     asyncio嵌入QThread · subprocess Node.js 签名               │
├─────────────────────────────────────────────────────────────┤
│ L4  数据存储层 — SQLite · Go 双后端                            │
│     Python sqlite3(WAL) · Go msg-service(Gin+modernc)       │
│     DeepSeek/OpenAI API · Markdown 渲染                       │
├─────────────────────────────────────────────────────────────┤
│ L5  底层协议 — 多样化的网络通信                                │
│     WebSocket(protobuf) · HTTP/2 · ECDSA 签名 · Playwright   │
└─────────────────────────────────────────────────────────────┘
```

### L1 展示层 — 关键技术点

**窗口架构：**
- `QMainWindow` 无边框自定义标题栏，含图钉置顶按钮 + 破洞效果
- `Sidebar` 导航栏 + `QStackedWidget` 多页面切换
- 四个页面：首页聊天 / 登录 / AI设置 / 提示词配置

**样式系统：**
- `styles.qss` (10KB) 集中管理全应用样式
- 支持浅色/深色模式切换
- `Qt.AA_UseSoftwareOpenGL` 强制软件渲染（避免 GPU 驱动 segfault）

**核心 Widget：**
- `ChatView` — 聊天气泡渲染，上旧下新，Markdown 支持
- `Contact` — 联系人列表项
- `PerfChart` — QtCharts 性能折线图
- `GlowProgressBar` — 发光进度条
- `SettingsDialog` — 设置对话框（43KB，最大单一文件）

**特殊技巧：**
- 图钉按钮：`QPropertyAnimation` 旋转动画 + `QRegion` 破洞 mask
- 窗口置顶：`ctypes.windll.user32.SetWindowPos` Windows API 调用
- 防抖动：`QEasingCurve.OutCubic` 缓动曲线

### L2 核心层 — 关键技术点

**MessageBus（事件中枢）：**
```python
class MessageBus(QObject):
    new_message = Signal(Message)      # 新私信
    send_reply = Signal(str, str)      # 发送回复
    platform_status = Signal(str, str) # 平台状态变更
    log = Signal(str)                  # 日志输出
    ai_request = Signal(str)           # AI 请求
    ai_response = Signal(str)          # AI 响应
```

所有模块只与 Bus 对话，互相不直接耦合。

**ConcurrencyManager（并发管理）：**
```python
class ConcurrencyManager:
    PRIO_HIGH = 0    # 消息回复、AI调用（永不被拒绝）
    PRIO_MEDIUM = 1  # 批量同步、会话拉取
    PRIO_LOW = 2     # 头像下载、缓存刷新

    # 共享线程池
    executor = ThreadPoolExecutor(max_workers=CPU核数×2, limit=32)

    # 背压控制
    max_global_queue = 200   # 全局任务上限
    max_platform_queue = 60  # 单平台任务上限
```

**GoServiceBridge（Go 服务桥接）：**
```python
class GoServiceBridge:
    # 启动 Go 编译的 msg-service.exe 子进程
    # 通过 HTTP localhost:9800 发送命令
    # 通过 WebSocket 异步监听 Go 广播
```

### L3 平台适配层 — 关键技术点

详见 [各平台协议逆向](#6-各平台协议逆向)。

### L4 数据存储层 — 关键技术点

详见 [数据持久化方案](#5-数据持久化方案)。

### L5 底层协议 — 关键技术点

| 协议 | 应用场景 | 核心库 |
|------|---------|--------|
| WebSocket | 抖音 IM 实时推送 | `websocket-client` + protobuf |
| HTTP/2 | 各平台 REST API + DeepSeek | `httpx` + `requests` |
| ECDSA | 抖音 req_sign 签名 | `cryptography.hazmat.primitives` |
| Cookie | 扫码登录 Cookie 持久化 | Playwright + Base64 |

---

## 4. 并发模型详解

### 4.1 线程架构全景

```
主线程 (Qt 事件循环)
  │
  ├── QThread: DouyinAdapter  ─── 内部运行 asyncio 事件循环
  ├── QThread: BilibiliAdapter ─── 内部运行 asyncio 事件循环
  ├── QThread: XHSAdapter      ─── 同步 HTTP 调用
  ├── QThread: KuaishouAdapter ─── 同步 HTTP 调用
  ├── QThread: AIWorker        ─── 同步 API 调用（每次新建）
  ├── QThread: LoginWorker     ─── Playwright 扫码
  │
  ├── threading.Thread (daemon): DouyinWSReceiver ─── 抖音 WebSocket
  ├── threading.Thread (daemon): Go WS listener     ─── Go 广播监听
  │
  └── ThreadPoolExecutor (16 workers): ConcurrencyManager
       ├── PRIO_HIGH:   消息回复 / AI 调用
       ├── PRIO_MEDIUM: 批量同步 / 会话拉取
       └── PRIO_LOW:    头像下载 / 缓存刷新

Go subprocess
  └── goroutine: batchWriter · broadcastLoop · WAL checkpoint · NoopWorker
```

### 4.2 asyncio + QThread 混用（最关键的模式）

这是整个项目中最重要的并发模式。抖音和B站适配器需要在 QThread 内运行 asyncio 事件循环：

```python
class DouyinAdapter(BaseAdapter):
    def run(self):
        """QThread.run() 入口"""
        asyncio.run(self._async_loop())  # 阻塞直到 asyncio 循环结束

    async def _async_loop(self):
        """asyncio 主循环"""
        while self._running:
            # 并发拉取所有会话的新消息
            tasks = [self._fetch_session(s) for s in sessions]
            results = await asyncio.gather(*tasks)

            for msg in results:
                self.bus.new_message.emit(msg)  # 跨线程信号回主线程

            await asyncio.sleep(self.poll_interval)
```

关键点：
- `asyncio.run()` 在 QThread 内创建一个新的事件循环并阻塞
- 通过 Qt Signal `emit()` 将数据跨线程安全地传回主线程
- 主线程不需要知道 asyncio 的存在

### 4.3 线程安全机制

| 场景 | 方案 |
|------|------|
| SQLite 写入 | `threading.Lock()` 互斥锁 |
| RateLimiter Token Bucket | `threading.Lock()` 保护 |
| PerfMonitor 指标采集 | `threading.Lock()` 保护 |
| MessageBus 单例 | `threading.Lock()` 双重检查锁 |
| 消息去重 | DB UNIQUE 索引 + 内存 `set()` 双防线 |

### 4.4 数据流向

```
抖音 WebSocket 收到消息
  → queue.Queue (后台线程 put)
    → DouyinAdapter._async_poll() (QThread 内 asyncio 循环 get)
      → 批量写入 SQLite (通过 ConcurrencyManager 线程池)
        → Bus.new_message.emit (跨线程信号)
          → MainThread 收到信号
            → HomePage.render() 更新 UI

用户点击 AI 回复
  → Bus.ai_request.emit
    → AIWorker(QThread) 启动
      → httpx 异步调用 DeepSeek API（流式）
        → Bus.ai_response.emit
          → Adapter.send_message()
            → Bus.send_reply.emit
```

---

## 5. 数据持久化方案

### 5.1 SQLite 数据库

**文件：** `dmshoot/data/dmshoot.db`

**WAL 模式配置：**
```sql
PRAGMA journal_mode = WAL;           -- Write-Ahead Logging
PRAGMA wal_autocheckpoint = 200;     -- 200页(约800KB)自动合并
PRAGMA synchronous = NORMAL;         -- 平衡性能和安全
PRAGMA timeout = 10;                 -- 连接超时10秒
```

**数据库表结构：**

```sql
-- 会话表
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    platform TEXT NOT NULL,
    peer_name TEXT,
    peer_id TEXT,
    last_message TEXT,
    last_time REAL,
    unread_count INTEGER DEFAULT 0,
    avatar_url TEXT,
    created_at REAL,
    updated_at REAL
);

-- 消息表
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    sender_name TEXT,
    sender_id TEXT,
    content TEXT,
    msg_type TEXT,
    is_self INTEGER DEFAULT 0,
    is_auto INTEGER DEFAULT 0,
    persona TEXT,
    timestamp REAL,
    created_at REAL,
    UNIQUE(session_id, content, is_self)   -- 去重索引
);

-- 配置表
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

**关键索引：**
- `idx_messages_session` — `(session_id, timestamp DESC)` 加速消息查询
- `idx_messages_platform` — `(platform, timestamp DESC)` 按平台过滤
- `idx_messages_dedup` — `UNIQUE(session_id, content, is_self)` 去重

### 5.2 WAL 五层防御

| 层级 | 实现 | 说明 |
|------|------|------|
| L1 | Python `atexit.register(_checkpoint_on_exit)` | 进程正常退出时 checkpoint |
| L2 | Go 60s ticker `PRAGMA wal_checkpoint(PASSIVE)` | 定期被动 checkpoint |
| L3 | 启动时自动检测 WAL 状态 | 损坏自动恢复 |
| L4 | `tools/wal_checkpoint.py --force` | 手动紧急 checkpoint 脚本 |
| L5 | `wal_autocheckpoint=200`, `synchronous=NORMAL` | PRAGMA 底层调优 |

### 5.3 Python/Go 双后端数据库访问

**Python 端：**
- 直接使用 `sqlite3` 模块，单一持久连接 `_get_conn()`
- 批量写入：`save_messages_batch()` 使用 `executemany`
- 批量 upsert：`INSERT OR IGNORE` 自动去重

**Go 端：**
- 使用 `modernc.org/sqlite` 纯 Go SQLite 驱动（无 CGO 依赖）
- 批量写入器：500ms flush 间隔，100 条/批
- `SetMaxOpenConns(1)` 防写冲突（同一 SQLite 文件）
- 每 60 秒自动 WAL checkpoint

**Python ↔ Go 通信：**
```
Python GoServiceBridge
  ├── subprocess.Popen("msg-service.exe")
  ├── HTTP localhost:9800/api/messages (REST)
  └── WebSocket localhost:9800/ws (实时广播)
```

---

## 6. 各平台协议逆向

### 6.1 抖音 (Douyin) — 最复杂的平台

#### API 端点

| 端点 | 用途 | 认证方式 |
|------|------|---------|
| `wss://frontier-im.douyin.com/ws/v2` | WebSocket IM 实时推送 | Cookie + protobuf |
| `creator.douyin.com/web/api/media/user/info/` | 获取用户信息 | Cookie |
| `creator.douyin.com/creator-micro/home` | 验证 Cookie 有效性 | Cookie |
| `www.douyin.com/aweme/v1/web/user/profile/other/` | 获取用户昵称+头像 | Cookie + a_bogus |
| 抖音内部 API (通过 SDK) | 发消息/通知列表/创建会话 | Cookie + a_bogus + req_sign + ticket |

#### 签名链路（2026-06 重构后）

```
generate_req_sign()   → Python cryptography (纯 ECDSA SHA256withECDSA)
                         用 SECP256K1 曲线，签名字节用 DER 编码

generate_ree_key()    → Python cryptography (纯公钥导出)
                         从私钥派生公钥，传给服务端用于加密

generate_a_bogus()    → subprocess Node.js → dy_ab.js
                         唯一需要 JS 的函数，LRU 缓存 512 条结果
                         输入: URL路径 + User-Agent
                         输出: a_bogus 字符串
```

#### Monkey-Patch SDK 集成

```python
# 核心技巧：替换 SDK 的 execjs 依赖为我们的 subprocess 实现
fake_dy_util = types.ModuleType("utils.dy_util")
fake_dy_util.generate_a_bogus = our_get_a_bogus
fake_dy_util.generate_req_sign = our_get_req_sign  # 纯 Python ECDSA
fake_dy_util.generate_ree_key = our_get_ree_key
# ... 注入所有其他必要函数

sys.modules["utils.dy_util"] = fake_dy_util  # 全局 monkey-patch

# 现在导入 DouYin_Spider SDK 时，
# SDK 内部 `from utils import dy_util` 会拿到我们的假模块
```

#### WebSocket Protobuf 消息流

```
Protobuf 二进制帧 (PushFrame)
  → 手工解析 varint 编码的 field tag
    → 扫描 0x42 (field 8, wire type 2 = length-delimited)
      → 提取 sender_uid 和 content 字节
        → JSON 解析 content
          → queue.Queue (线程安全)
            → DouyinAdapter._async_poll() 消费
              → 批量写入 DB + Bus.new_message.emit
```

#### Protobuf 手工解析（无 .proto 文件）

```python
# proto_msg_parser.py 的核心逻辑
def parse_im_init_data(raw_bytes):
    """从 2000+ 字节的二进制 blob 中提取消息字段"""
    pos = 0
    while pos < len(raw_bytes):
        tag = read_varint(raw_bytes, pos)      # 读取 varint 编码的 field tag
        field_number = tag >> 3                 # field tag 的高位是字段号
        wire_type = tag & 0x07                  # 低 3 位是 wire type

        # field 8 = NewMessageNotify
        if field_number == 8 and wire_type == 2:
            msg_data = read_length_delimited(...)
            sender_uid = extract_sender_uid(msg_data)
            content = extract_content(msg_data)

        pos = move_to_next_field(...)
```

**Snowflake ID 时间戳解码：**
```python
def _decode_timestamp(server_message_id):
    """从抖音 Snowflake ID 推导真实 Unix 时间戳"""
    # 支持三种编码：Snowflake 标准 / 微秒 / 毫秒
    # Snowflake: timestamp = id >> 22
    # 微秒: timestamp = id / 1_000_000
    # 毫秒: timestamp = id / 1_000
```

### 6.2 B站 (Bilibili) — SDK 驱动

#### API 端点

| 端点 | 用途 | 依赖 |
|------|------|------|
| `bilibili_api.session.get_sessions()` | 获取会话列表 | SDK 封装 |
| `bilibili_api.session.fetch_session_msgs()` | 获取会话消息 | SDK 封装 |
| `bilibili_api.session.send_msg()` | 发送私信 | SDK 封装 |
| `bilibili_api.user.get_self_info()` | 获取自身信息 | SDK 封装 |
| `api.bilibili.com/x/web-interface/card` | 获取用户名片 | HTTP + Cookie |
| `api.bilibili.com/x/space/acc/info` | 获取用户空间(备用) | HTTP + Cookie |

#### 认证方式

```python
from bilibili_api import Credential

credential = Credential(
    sessdata=cookie_dict.get("SESSDATA"),
    bili_jct=cookie_dict.get("bili_jct"),
    buvid3=cookie_dict.get("buvid3"),
    dedeuserid=cookie_dict.get("DedeUserID"),
)
```

#### 并发策略

```python
async def _async_loop(self):
    while self._running:
        sessions = await session.get_sessions()
        # 并发拉取所有会话的新消息
        tasks = [session.fetch_session_msgs(s.talker_id) for s in sessions]
        all_messages = await asyncio.gather(*tasks)
```

### 6.3 小红书 (XHS) — JS 签名穿透

#### API 端点

| 端点 | 用途 | 状态 |
|------|------|------|
| `edith.xiaohongshu.com/api/sns/web/v2/user/me` | 验证身份 | ✅ 可用 |
| `edith.xiaohongshu.com/api/im/v3/chats` | IM 会话列表 | ⚠️ 需移动端 token |
| `edith.xiaohongshu.com/api/im/v3/chats/info` | 会话详情 | ⚠️ 需移动端 token |
| `creator.xiaohongshu.com/api/galaxy/user/info` | 用户信息 | ✅ 可用 |
| `creator.xiaohongshu.com/api/galaxy/message/list` | 创作者消息列表 | ✅ 仅通知 |

#### 签名方案

```
sign.py → subprocess Node.js → require("xhs_creator_260411.js")
  → 调用混淆 JS 函数生成:
    - x-s            ← 路径 + a1 Cookie + 请求体签名
    - x-t            ← 时间戳
    - x-s-common     ← 通用签名
    - x-b3-traceid   ← 链路追踪 ID
    - x-xray-traceid ← X-Ray 追踪 ID
```

**备用代理方案（绕过签名）：**
```python
# xhs_proxy.py — 通过 Playwright 浏览器注入 JS 代发请求
page.evaluate("""
    fetch(url, {
        method: 'POST',
        headers: {...},
        body: JSON.stringify(data)
    }).then(r => r.json())
""")
```

#### 当前限制

**Web 端 Cookie 无法访问 IM 私信 API。** 需要移动端 token (user_token/idToken) 才能使用 V3 IM 端点。SSL pinning 导致无法从手机抓包获取真实 token。

### 6.4 快手 (Kuaishou) — 仅登录

| 端点 | 用途 |
|------|------|
| `www.kuaishou.com` | 扫码登录 |
| `live.kuaishou.com` | 补充直播域 Cookie |

**当前限制：** `KuaishouAdapter._im_unavailable = True`。Web 端不支持私信收发，仅限移动端。

---

## 7. 跨语言通信方案

### 7.1 Python ↔ Node.js（签名生成）

```python
# subprocess 调用 Node.js 执行混淆 JS
def get_a_bogus(url, ua):
    """生成抖音 a_bogus 参数"""
    # 将输入写入临时 JSON 文件
    input_data = json.dumps({"url": url, "ua": ua})

    # 执行 Node.js 脚本
    result = subprocess.run(
        ["node", "dy_ab.js"],
        input=input_data,
        capture_output=True,
        text=True,
        cwd="external/DouYin_Spider/static/"
    )

    return json.loads(result.stdout)["a_bogus"]

# LRU 缓存避免重复调用
@lru_cache(maxsize=512)
def get_a_bogus_cached(url, ua):
    return get_a_bogus(url, ua)
```

### 7.2 Python ↔ Go（消息服务）

```python
# GoServiceBridge 管理 Go 子进程生命周期
class GoServiceBridge:
    def start(self):
        self.process = subprocess.Popen(
            ["dmshoot-go/msg-service.exe"],
            cwd="dmshoot-go/"
        )
        # 等待 HTTP 服务就绪
        self._wait_for_ready()

    def send_message(self, platform, content):
        """通过 HTTP 发送消息"""
        httpx.post(f"http://localhost:9800/api/{platform}/send",
                   json={"content": content})

    async def _ws_listen(self):
        """通过 WebSocket 监听 Go 广播"""
        async with websockets.connect("ws://localhost:9800/ws") as ws:
            async for msg in ws:
                data = json.loads(msg)
                self.bus.new_message.emit(Message(**data))
```

---

## 8. 设计模式应用

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **单例** | MessageBus, ConcurrencyManager, PerfMonitor, RateLimiter | `__new__` + 双重检查锁 |
| **适配器** | BaseAdapter → 四个平台 Adapter | 统一接口 `connect/disconnect/send/fetch` |
| **观察者** | Qt Signal/Slot + MessageBus | 发布-订阅解耦 |
| **门面** | DouyinClient, MessageService | 封装复杂子系统 |
| **策略** | AdaptivePoller, MessageService(Python/Go) | 运行时切换算法/后端 |
| **桥接** | GoServiceBridge + GoDatabaseClient | 抽象层与实现层独立变化 |
| **插件** | PluginManager + PLUGIN_INFO | `importlib` 自动发现和加载 |
| **依赖注入** | 构造函数注入 | `AdapterManager(auth, bus, db, ...)` |

---

## 9. 学习路线图

### 第一优先级：核心必须（先学这些才能跑起来）

#### 9.1 asyncio 异步编程

**掌握程度：** 熟练

**需要理解的概念：**
- `async def` / `await` 语法
- `asyncio.run()` 启动事件循环
- `asyncio.create_task()` 并发执行
- `asyncio.gather()` 等待多个协程
- `asyncio.sleep()` vs `time.sleep()`
- 协程 vs 线程的本质区别

**在项目中的应用：**
- 抖音和 B 站适配器并发拉取会话消息
- `asyncio.gather(*tasks)` 并发调用多个 API
- QThread 内部运行 asyncio 事件循环

**推荐学习资源：**
- Python 官方文档 `asyncio` 模块
- Real Python: "Async IO in Python: A Complete Walkthrough"

#### 9.2 PySide6 / Qt 基础

**掌握程度：** 熟练

**需要理解的概念：**
- `QApplication` 事件循环
- `QMainWindow` 窗口结构
- `QWidget` / `QLayout` 布局系统
- Signal/Slot 信号槽机制（核心）
- `QThread` 多线程与 GUI 线程安全
- QSS (Qt Style Sheets) 样式
- `QStackedWidget` 多页面导航

**在项目中的应用：**
- 整个 GUI 架构
- Signal/Slot 跨线程通信
- 自定义 Widget 开发
- 样式表集中管理

**推荐学习资源：**
- PySide6 官方教程
- Qt for Python 文档

#### 9.3 asyncio + QThread 混用（最关键技能）

**掌握程度：** 精通

**这是项目中最关键的并发模式：**

```python
class MyAdapter(QThread):
    def run(self):
        # QThread.run() 在新线程中执行
        asyncio.run(self._async_main())

    async def _async_main(self):
        while self._running:
            data = await fetch_data()          # 异步网络请求
            self.signal.emit(process(data))    # 跨线程发信号
            await asyncio.sleep(interval)
```

**注意陷阱：**
- 不能在 asyncio 协程中直接操作 Qt Widget（必须通过 signal）
- `asyncio.run()` 会阻塞 QThread，直到协程完成
- Signal 会自动在接收者线程（通常是主线程）执行 slot

#### 9.4 SQLite + WAL 模式

**掌握程度：** 熟练

**需要理解的概念：**
- WAL (Write-Ahead Logging) 原理
- `journal_mode` / `synchronous` / `wal_autocheckpoint` PRAGMA
- `check_same_thread=False` 多线程访问
- `threading.Lock()` 保护写操作
- 批量 `executemany` + `INSERT OR IGNORE` 去重
- 复合 UNIQUE 索引设计
- SQLite WAL 文件管理（checkpoint, 碎片整理）

**在项目中的应用：**
- 三表设计 (sessions, messages, config)
- WAL 五层防御
- Python/Go 双后端并发访问同一 SQLite 文件

#### 9.5 HTTP 客户端（httpx + requests）

**掌握程度：** 熟练

**需要理解的概念：**
- 同步 vs 异步 HTTP 客户端
- Cookie 管理（Jar, 域名匹配）
- 请求头伪造（User-Agent, Referer, Origin）
- JSON/Form 请求体
- 超时和重试机制
- SSL 证书验证 (`verify=False` 用于抓包调试)

**在项目中的应用：**
- 各平台 API 调用
- DeepSeek API 流式响应
- Cookie 持久化和加载

---

### 第二优先级：进阶技能

#### 9.6 多线程编程

**掌握程度：** 熟练

**需要理解的概念：**
- `threading.Thread` 创建和生命周期
- `threading.Lock()` 互斥锁
- `threading.Event` 事件通知
- `queue.Queue` 线程安全队列
- `ThreadPoolExecutor` 线程池
- 守护线程 `daemon=True`
- 生产者-消费者模式
- GIL 对 CPU 密集型任务的影响

**在项目中的应用：**
- WebSocket 后台接收线程
- ConcurrencyManager 线程池
- RateLimiter/PerfMonitor 锁保护
- 各平台 Adapter QThread

#### 9.7 Playwright 浏览器自动化

**掌握程度：** 了解（能写扫码登录脚本即可）

**需要理解的概念：**
- `browser = await playwright.chromium.launch(headless=True)`
- `page = await browser.new_page()`
- `await page.goto("https://example.com/login")`
- `await page.wait_for_url("**/callback**")` — 等待扫码跳转
- `cookies = await context.cookies()` — 提取 Cookie
- `await page.evaluate("js_code")` — 页面内注入 JS

**在项目中的应用：**
- 抖音/B站/小红书/快手扫码登录
- Cookie 持久化到 `.b64` 文件
- `xhs_proxy.py` 页面注入 JS 绕过签名

#### 9.8 subprocess 跨语言调用

**掌握程度：** 了解

**需要理解的概念：**
- `subprocess.run()` — 同步执行
- `subprocess.Popen()` — 异步子进程管理
- `stdin`/`stdout` 管道通信
- 子进程生命周期管理
- 进程间 JSON 协议

**在项目中的应用：**
- Python 调 Node.js 生成签名
- Python 管理 Go 子进程

#### 9.9 WebSocket 客户端

**掌握程度：** 了解

**需要理解的概念：**
- WebSocket vs HTTP 的区别
- `on_message` / `on_error` / `on_close` 回调
- Ping/Pong 保活
- 自动重连机制
- 线程安全的消息队列

**在项目中的应用：**
- 抖音 IM 实时推送接收
- Go ↔ Python WebSocket 广播

---

### 第三优先级：高级/边缘技能

#### 9.10 Protobuf 手工解析

**掌握程度：** 了解即可

**核心概念：**
- varint 编码（7 位一组，最高位表示是否继续）
- field tag = (field_number << 3) | wire_type
- wire type 0: varint, wire type 2: length-delimited
- 从二进制 bytes 中手工提取结构化数据

**在项目中的应用：**
- `proto_msg_parser.py` 解析抖音 IM 初始化数据
- 无 `.proto` 文件的逆向解析

#### 9.11 ECDSA 签名

**掌握程度：** 了解即可

**核心概念：**
- SECP256K1 椭圆曲线
- SHA256withECDSA 签名算法
- 私钥 → 公钥推导
- DER 编码的签名格式

**在项目中的应用：**
- 抖音 `req_sign` 生成（Python cryptography 库）
- 替代 Node.js `jsrsasign`，减少依赖

#### 9.12 Monkey-Patch

**掌握程度：** 了解即可

**核心技巧：**
```python
# 创建假模块
fake_module = types.ModuleType("target.module")
fake_module.some_func = our_implementation

# 注入 sys.modules
sys.modules["target.module"] = fake_module

# 后续所有 import target.module 都会拿到假的
```

**在项目中的应用：**
- 绕过 DouYin_Spider SDK 的 `execjs.compile()` 调用
- 用 subprocess + Node.js 替代浏览器内 JS 执行

#### 9.13 Go 语言基础

**掌握程度：** 可选

**需要理解的概念：**
- Gin Web 框架（路由、中间件、JSON）
- Gorilla WebSocket（升级 HTTP 连接）
- `modernc.org/sqlite` 纯 Go SQLite
- goroutine + channel 并发
- `go.mod` 模块管理

**在项目中的应用：**
- `dmshoot-go/` 消息服务后端（3 个 .go 文件，约 300 行）

#### 9.14 Node.js 辅助

**掌握程度：** 可选（只需知道怎么调）

**在项目中的应用：**
- 执行预编译的混淆 JS 文件（抖音 `dy_ab.js` + 小红书 `xhs_*.js`）
- `npm install` 安装 `jsrsasign` 和 `crypto-js`

---

### 9.15 设计模式与架构

| 模式 | 优先级 | 说明 |
|------|--------|------|
| 单例模式 | 必须 | `MessageBus` 等全局唯一实例 |
| 适配器模式 | 必须 | `BaseAdapter` 统一四平台接口 |
| 观察者模式 | 必须 | Qt Signal/Slot ≈ 发布订阅 |
| 门面模式 | 推荐 | `DouyinClient` 隔离 SDK 复杂度 |
| 策略模式 | 推荐 | `AdaptivePoller` 动态调整 |
| 桥接模式 | 推荐 | `GoServiceBridge` 子进程管理 |
| 依赖注入 | 推荐 | 构造函数注入解耦 |
| 插件模式 | 了解 | `PluginManager` 动态加载 |

---

### 9.16 学习顺序建议

```
第一阶段（2-3天）：跑通项目
  → Python asyncio 基础
  → PySide6 基础（QMainWindow, Signal/Slot, QThread）
  → SQLite 基础操作

第二阶段（3-5天）：理解核心
  → asyncio + QThread 混用模式
  → MessageBus 事件总线架构
  → httpx 异步 HTTP 调用
  → Playwright 扫码登录流程

第三阶段（5-7天）：深入平台
  → 抖音：WebSocket + protobuf + 签名链路
  → B站：bilibili-api SDK 使用
  → 小红书：JS 签名调用 + API 逆向
  → 快手：登录流程

第四阶段（2-3天）：进阶架构
  → ConcurrencyManager 线程池 + 背压
  → RateLimiter Token Bucket 限流
  → GoServiceBridge 跨语言通信
  → WAL 五层防御深入理解

第五阶段（可选）：
  → Protobuf 手工解析原理
  → ECDSA 签名原理
  → Go 语言入门（dmshoot-go）
  → pytest-qt GUI 测试编写
```

---

## 10. 关键文件索引

### 入口和配置

| 文件 | 路径 | 说明 |
|------|------|------|
| 入口 | `main.py` | 应用启动入口 |
| 依赖 | `requirements.txt` | Python 依赖列表 |
| 测试依赖 | `requirements-test.txt` | 测试依赖 |
| 开发笔记 | `DEV_NOTES.md` | 开发过程记录 |
| .gitignore | `.gitignore` | Git 忽略规则 |

### 核心层 (dmshoot/core/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `bus.py` | ~80 | MessageBus 单例事件中枢 |
| `adapter.py` | ~120 | BaseAdapter(QThread) 基类 |
| `adapter_manager.py` | ~80 | 适配器生命周期管理 |
| `concurrency.py` | ~180 | ConcurrencyManager 线程池 + 背压 |
| `rate_limiter.py` | ~60 | Token Bucket 限流器 |
| `perf_monitor.py` | ~80 | 性能监控（psutil） |
| `poller.py` | ~40 | AdaptivePoller 自适应轮询 |
| `go_bridge.py` | ~200 | GoServiceBridge 子进程管理 |
| `go_db_client.py` | ~100 | GoDatabaseClient HTTP 代理 |
| `message.py` | ~50 | Message、SessionRecord dataclass |
| `msg_service.py` | ~80 | MessageService 门面 |
| `message_analytics.py` | ~120 | SQL 聚合统计分析 |

### GUI 层 (dmshoot/gui/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `main_window.py` | ~700 | 主窗口（最大文件之一） |
| `settings_dialog.py` | ~800 | 设置对话框（最大文件） |
| `signal_wiring.py` | ~100 | Qt 信号连接集中管理 |
| `auth_controller.py` | ~150 | 自动登录验证 |
| `sidebar.py` | ~200 | 侧边栏导航 |
| `monitor_panel.py` | ~150 | 实时性能面板 |
| `log_panel.py` | ~80 | 日志面板 |
| `styles.qss` | ~300 | Qt 样式表 |

### 平台适配器 (dmshoot/plugins/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `douyin/adapter.py` | ~300 | 抖音适配器（最复杂） |
| `douyin/douyin_client.py` | ~200 | DouyinClient 门面 |
| `douyin/__init__.py` | ~30 | 插件注册 |
| `bilibili/adapter.py` | ~250 | B站适配器 |
| `bilibili/__init__.py` | ~30 | 插件注册 |
| `xiaohongshu/adapter.py` | ~200 | 小红书适配器 |
| `xiaohongshu/sign.py` | ~150 | XHS 签名模块 |
| `xiaohongshu/im_client.py` | ~200 | V3 IM API 客户端 |
| `xiaohongshu/login.py` | ~200 | 小红书登录流程 |
| `xiaohongshu/__init__.py` | ~30 | 插件注册 |
| `kuaishou/adapter.py` | ~100 | 快手适配器 |
| `kuaishou/__init__.py` | ~30 | 插件注册 |
| `manager.py` | ~80 | PluginManager 动态加载 |

### 工具层 (dmshoot/utils/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `douyin_sdk.py` | ~500 | SDK monkey-patch 桥接 |
| `douyin_signer.py` | ~200 | ECDSA 签名 + Node.js 调用 |
| `douyin_ws.py` | ~200 | WebSocket protobuf 接收器 |
| `proto_msg_parser.py` | ~135 | 手工 protobuf 字段解析 |
| `douyin_im_sync.py` | ~200 | IM 同步 + protobuf 解析 |
| `cookie_reader.py` | ~500 | Playwright 扫码登录 |
| `xhs_proxy.py` | ~150 | Playwright 无头浏览器代理 |
| `platform_connector.py` | ~100 | 平台连接验证器 |
| `console_log.py` | ~80 | 彩色终端日志 |

### AI 层 (dmshoot/ai/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `backend.py` | ~150 | AIBackend (DeepSeek/OpenAI) |
| `prompts.py` | ~100 | 提示词文件管理 |

### 存储层 (dmshoot/storage/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `database.py` | ~400 | SQLite DAO 层 |
| `models.py` | ~60 | 数据模型定义 |

### Go 服务 (dmshoot-go/)

| 文件 | 行数 | 说明 |
|------|------|------|
| `main.go` | ~150 | Gin HTTP + WebSocket + SQLite |
| `internal/writer/batch.go` | ~80 | 批量写入器 |
| `internal/worker/worker.go` | ~40 | 平台轮询注册表 |
| `go.mod` | ~10 | Go 模块定义 |

### 外部 SDK (external/)

| 目录 | 说明 |
|------|------|
| `external/DouYin_Spider/builder/` | SDK 核心 Python (protobuf + API) |
| `external/DouYin_Spider/static/` | JS 签名文件 (dy_ab.js 等) |

### 文档 (docs/)

| 文件 | 说明 |
|------|------|
| `ARCHITECTURE_REVIEW.md` | 架构评审报告 |
| `WAL_CHECKPOINT_SOLUTION.md` | WAL 防御方案文档 |

---

## 附录 A：推荐阅读顺序（源码）

```
1. main.py                                  ← 入口
2. dmshoot/core/bus.py                      ← 事件中枢
3. dmshoot/core/message.py                  ← 数据模型
4. dmshoot/core/adapter.py                  ← 适配器基类
5. dmshoot/plugins/manager.py               ← 插件加载
6. dmshoot/plugins/douyin/adapter.py        ← 最复杂平台
7. dmshoot/utils/douyin_sdk.py              ← SDK 集成
8. dmshoot/utils/douyin_signer.py           ← 签名方案
9. dmshoot/utils/douyin_ws.py               ← WebSocket
10. dmshoot/utils/proto_msg_parser.py       ← protobuf 解析
11. dmshoot/core/concurrency.py             ← 并发管理
12. dmshoot/gui/main_window.py              ← GUI 主窗口
13. dmshoot/gui/signal_wiring.py            ← 信号连接
14. dmshoot/gui/auth_controller.py          ← 登录流程
15. dmshoot/ai/backend.py                   ← AI 后端
16. dmshoot/storage/database.py             ← 数据层
17. dmshoot/core/go_bridge.py               ← Go 桥接
```

## 附录 B：项目代码量统计

| 目录 | 文件数 | 总行数(约) | 职责 |
|------|--------|-----------|------|
| `dmshoot/core/` | 12 .py | ~1100 | 事件总线、并发、服务 |
| `dmshoot/gui/` | 12 .py + .qss | ~2500 | GUI 界面 |
| `dmshoot/plugins/` | 12 .py | ~1800 | 平台适配 |
| `dmshoot/utils/` | 9 .py | ~2000 | SDK 桥接、签名、协议 |
| `dmshoot/ai/` | 2 .py | ~250 | AI 后端 |
| `dmshoot/storage/` | 2 .py | ~460 | 数据库 |
| `dmshoot-go/` | 3 .go | ~270 | Go 服务 |
| **合计** | **~52 源文件** | **~8400** | — |
