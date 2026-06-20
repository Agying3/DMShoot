# DMShoot 技术问答

> 面向不了解项目的朋友，基于实际代码回答。更新时间：2026-06-13。

---

## 一、程序功能与实现

### 1. Cookie 管理与存续

**问：B站和抖音的 Cookie 分别存哪了？怎么存才能自动续期？**

**存储位置：**

| 平台 | 存储方式 | 字段 | 额外备份 |
|------|---------|------|---------|
| B站 | SQLite `config` 表 | `bilibili_sessdata`, `bilibili_jct` | — |
| 抖音 | SQLite `config` 表 | `douyin_cookie`, `douyin_web_protect`, `douyin_keys` | — |
| 小红书 | SQLite `config` 表 | `xhs_cookie` | `data/xhs_cookie.txt` 兜底 + 环境变量 `XHS_COOKIE` 读取 |
| 快手 | SQLite `config` 表 | `ks_cookie` | `data/kuaishou_cookie.json`（17 个 Cookie 完整保留） |

**自动续期：目前没有。** 代码中不存在 `refresh_token` 或任何 Cookie 自动续期逻辑。Cookie 过期后的唯一续命方式是通过 Playwright 扫码重新登录。各平台 SDK 也未提供 session 刷新接口。

> 建议方向：监控 API 返回 `-101`（登录过期），触发 GUI 弹窗提醒用户重新扫码。

---

### 2. B站私信收发：核心循环与重试逻辑

**问：代码里处理 B站私信的核心循环在哪？如果某条消息发送失败，重试逻辑是怎么写的？重试几次？间隔多久？**

**核心循环：** `dmshoot/plugins/bilibili/adapter.py` 第 331-401 行 `_poll_messages()`

```
_poll_messages()
  ├── bsync(sess.get_sessions())              # 获取所有会话列表
  ├── 遍历会话，找 unread_count > 0 的
  ├── bsync(sess.fetch_session_msgs(...))      # 拉取该会话未读消息
  ├── 逐条解析 → _parse_message()
  ├── _on_message(dm_msg)                      # 触发 AI 回复
  └── _replied.add(seq)                        # 内存去重
```

**重试逻辑（两层）：**

| 层 | 位置 | 异常类型 | 重试间隔 | 最大次数 | 行为 |
|----|------|---------|---------|---------|------|
| **内层** `_poll_messages` 异常 | `adapter.py:392-393` | `except Exception` | 5 秒 | 无限 | 本轮跳过，外层循环继续 |
| **外层** `_poll_loop` 异常 | `core/adapter.py:103-105` | `except Exception` | 2 秒 | 无限 | 记录日志后继续 `_poll_loop` |

- **没有最大重试次数限制**，异常不会导致线程退出，会一直重试直到程序停止。
- 正常无新消息时轮询间隔：3 秒。
- B站 API 调用使用 `bilibili_api.sync`（同步阻塞），不是 `asyncio`。

---

### 3. 主程序与 Go 模块通信

**问：Python 主程序和 Go 数据库模块之间，通过什么方式通信？通信失败时怎么降级？**

**协议：HTTP API + WebSocket，Go 作为子进程管理。**

```
Python 主进程
  ├── subprocess.Popen ──────→ dmshoot-go.exe（子进程）
  ├── HTTP POST/GET ────────→ Gin HTTP Router (localhost:9800)
  └── WebSocket ───────────── 实时消息推送
```

**Go 进程生命周期：**

1. 启动时自动检测 `dmshoot-go/dmshoot-go.exe` 是否存在
2. 不存在则自动执行 `go build` 编译
3. 通过 `DMSHOOT_DB` 环境变量传入数据库路径
4. 启动后轮询 `GET /api/health` 最多 15 秒等待就绪
5. 退出时 `SIGTERM` → 等 3 秒 → `SIGKILL`

**API 端点一览：**

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/health` | GET | 就绪检查 |
| `/api/db/messages/save` | POST | 批量写入消息 |
| `/api/db/messages` | GET | 读取消息 |
| `/api/db/sessions/upsert` | POST | 批量写入会话 |
| `/api/db/sessions` | GET | 读取会话 |
| `/api/db/sessions/delete` | POST | 删除会话 |
| `/api/db/config` | GET/POST | 配置读写 |
| `/ws` | WebSocket | 实时消息推送 |

**降级策略：** `MessageService`（`dmshoot/core/msg_service.py`）支持热切换：

```python
service = MessageService(backend="go")   # 走 Go HTTP API
service = MessageService(backend="python")  # 走本地 sqlite3
```

Go 进程挂掉后可以切回 Python 后端，不影响核心功能。切换在 GUI 设置页面一键完成。

---

### 4. Go 数据库模块：连接池配置

**问：Go 代码里，数据库连接池是怎么配置的？最大连接数、空闲连接数、连接最大生命周期各是多少？**

**文件：** `dmshoot-go/internal/writer/batch.go` 第 54-59 行

```go
db, err := sql.Open("sqlite",
    dbPath+"?_journal_mode=WAL&_synchronous=NORMAL&_busy_timeout=3000")
db.SetMaxOpenConns(1)
```

| 参数 | 设定值 | 说明 |
|------|--------|------|
| **MaxOpenConns** | **1** | SQLite 写串行限制，合理 |
| **MaxIdleConns** | 未设置（Go 默认 2） | 可优化为 1，避免多余空闲连接 |
| **ConnMaxLifetime** | 未设置（永不过期） | 建议加，防极端情况下的内存泄漏 |

**其他关键配置：**

| 参数 | 值 | 说明 |
|------|-----|------|
| 驱动 | `modernc.org/sqlite` | 纯 Go 实现，无需 CGO，跨平台编译友好 |
| 日志模式 | WAL | 支持读写并发 |
| 同步模式 | NORMAL | 平衡安全与性能 |
| 锁超时 | 3000ms | 锁等待最大时间 |
| 批量写入器 | 100 条或 500ms Flush | 缓冲通道积累后批量 `INSERT` |

**Python 端（`dmshoot/storage/database.py` 第 34 行）：**

```python
sqlite3.connect(db_path, timeout=10, check_same_thread=False)
```

Python 端也没有显式连接池配置。

---

### 5. B站异步与并发

**问：B站消息收发部分，用的是同步 requests 还是异步 aiohttp？如果是同步，改成异步的话，需要改动哪些函数？你预期 QPS 能提升多少？**

**现状：主轮询同步，历史同步用 asyncio。**

| 操作 | 方式 | 函数名 | 位置 |
|------|------|--------|------|
| 主轮询拉消息 | `bsync()` 同步阻塞 | `_poll_messages()` | adapter.py:331 |
| 历史消息同步 | `asyncio.gather()` 并发 | `_async_sync_history()` | adapter.py:142 |
| 用户信息 HTTP | `httpx.get()` 同步 | `_get_user_name()` | adapter.py:83 |
| 轮询间隔 | `time.sleep(3)` 阻塞 | `_poll_messages()` | adapter.py:396 |
| 共享线程池 | `ThreadPoolExecutor` | `ConcurrencyManager` | concurrency.py |

**改成全异步需要改动的函数：**

1. `_poll_messages()` → `async def`，`bsync()` → `await sess.get_sessions_async()`
2. `time.sleep(3)` → `await asyncio.sleep(3)`
3. `_get_user_name()` → 改用 `httpx.AsyncClient`
4. BaseAdapter 的 QThread `run()` → 需要 `asyncio.run()` 事件循环
5. 各平台 adapter 的 `_replied` 检查可以在异步上下文中直接做

**QPS 提升预估：**

当前串行轮询：每个会话顺序拉取，N 个会话耗时 O(N × 200ms)。改 `asyncio.gather` 并发后，N 个会话拉取时间降到 O(200ms)，实际吞吐提升取决于同时活跃会话数，预估 **2-5 倍**。

---

### 6. 自动报警

**问：报警触发条件写在哪？超过阈值后，通过什么渠道通知？**

**没有自动报警系统。** 代码中不存在邮件、短信、Webhook、桌面通知等任何外部告警渠道。

仅 `PerfMonitor`（`dmshoot/core/perf_monitor.py`）在内部维护了性能指标阈值：

| 指标 | 警告阈值 | 致命阈值 | 含义 |
|------|---------|---------|------|
| 队列积压 | >10 条 | >50 条 | 消息处理跟不上 |
| API 响应时间 | >200ms | >500ms | 平台 API 缓慢 |
| 错误率 | >1% | >5% | 连续请求失败 |
| 线程池活跃度 | >70% | >90% | 线程池饱和 |
| 内存占用 | >512MB | >1024MB | 可能内存泄漏 |
| 消息速率 | <5 条/秒 | <2 条/秒 | 轮询效率下降 |
| DB 写入延迟 | >50ms | >100ms | 数据库瓶颈 |

这些阈值仅用于 GUI 性能图表的颜色变化（绿→黄→红），**不触发任何外部通知**。

---

### 7. 日志

**问：程序运行日志文件存在哪？日志级别怎么配置？错误日志有没有包含足够的上下文？**

**日志不写文件，仅输出到控制台。**

配置位置：`dmshoot/utils/console_log.py`

| 项目 | 设定 |
|------|------|
| 日志级别 | `DEBUG` |
| 输出目标 | `sys.stdout`（`StreamHandler`） |
| 文件写入 | **无**（没有 `RotatingFileHandler`） |
| 第三方库抑制 | `httpx/httpcore/urllib3/asyncio/playwright` → `WARNING`；`websocket` → `CRITICAL` |

**日志格式：**

```
2026-06-13 22:01:16 [douyin] 收到新消息
2026-06-13 22:01:16 [bilibili] 轮询异常: ConnectionError
```

包含时间戳和平台名，但**不包含**用户名、请求参数、消息内容等详细上下文。

**额外的调试输出：** `_debug()` 辅助函数将调试信息追加写入 `dmshoot/data/adapter_debug.txt`，但仅 B站和小红书 adapter 调用。

---

## 二、测试与质量

### 1. 测试覆盖率

**问：dmshoot 项目当前的测试覆盖率具体是多少？**

**没有测量过。** 项目中没有 `coverage`、`pytest-cov` 等覆盖率工具配置。存在 3 个测试文件但从未在覆盖率统计下运行：

- `test_dmshoot.py`（~837 行）— 核心功能
- `test_xhs.py`（~923 行）— 小红书
- `test_new_features.py`（~175 行）— 新功能

---

### 2. 关键模块测试

**问：B站登录、消息发送、Cookie 解析这三个核心模块，有没有对应的单元测试？测试文件在哪？**

| 模块 | 测试文件 | 覆盖情况 |
|------|---------|---------|
| B站登录 | `test_dmshoot.py` | 部分覆盖，侧重 adapter 功能 |
| 消息发送 | `test_dmshoot.py` | 包含 AI 回复流程测试 |
| Cookie 解析 | `test_dmshoot.py` | 部分覆盖 |
| 小红书 | `test_xhs.py` | 签名、登录、IM 模块较完整 |
| 性能监控 | `test_new_features.py` | 新功能测试 |

**Go 模块：没有 `*_test.go` 文件，零测试。**

---

### 3. `except: pass` 位置

**问：代码里 `except: pass` 的具体位置在哪？改成具体异常捕获后，如何验证改对了？**

**生产代码中约 27 处**裸 `except:` 或宽泛异常捕获。集中分布：

| 文件 | 数量 | 代表性位置 |
|------|------|-----------|
| `plugins/bilibili/adapter.py` | 7 处 | 第 26, 41, 181, 199, 287, 310, 362 行 |
| `plugins/kuaishou/adapter.py` | 8 处 | 第 35, 43, 58, 79, 127, 146, 167, 175 行 |
| `plugins/xiaohongshu/adapter.py` | 4 处 | 第 37, 45, 84, 420 行 |
| `plugins/douyin/adapter.py` | 2 处 | 第 91, 186 行 |
| `utils/proto_msg_parser.py` | 4 处 | 第 28, 37, 74, 91 行 |
| `core/go_bridge.py` | 1 处 | 第 161 行（`except Exception: return {}`） |

**改后验证方式：**

1. 模拟超时：`raise httpx.TimeoutException` / `raise asyncio.TimeoutError`
2. 模拟网络断连：`raise ConnectionError` / `raise httpx.ConnectError`
3. 模拟 JSON 解析失败：传入非法 payload 触发 `json.JSONDecodeError`
4. 模拟 Cookie 过期：返回 `{"code": -101, "msg": "登录已过期"}`
5. 已有测试文件中有 mock 用例可参考

---

### 4. Go 模块测试

**问：Go 数据库模块有基准测试吗？测试函数名是什么？执行命令怎么写？**

**没有。** `dmshoot-go/` 下不存在 `*_test.go` 文件。

如果要加基准测试，创建 `dmshoot-go/internal/writer/batch_test.go` 后执行：

```bash
cd dmshoot-go
go test -bench=. -benchmem ./...
```

---

### 5. 集成测试

**问：Python 主程序和 Go 模块联调时，有没有端到端测试？比如发一条 B站私信 → Go 模块记录日志 → 断言日志写入成功。**

**没有。** 当前无任何集成测试。Python-Go 联调全靠手动运行程序验证。

---

## 三、依赖与部署

### 1. 第三方依赖

**问：`requirements.txt` 里列了哪些包？哪些是必须的，哪些是僵尸依赖？**

```text
PySide6>=6.5.0              ✅ 必须 — GUI 框架
httpx>=0.27.0               ✅ 必须 — HTTP 客户端
pyyaml>=6.0                 ✅ 必须 — YAML 配置解析
aiosqlite>=0.20.0           ⚠️ 僵尸 — 声明但代码中未使用，用的是同步 sqlite3
bilibili-api-python>=17.4.0 ✅ 必须 — B站 API SDK
playwright>=1.60.0          ✅ 必须 — 扫码登录浏览器自动化
websocket-client>=1.8.0     ✅ 必须 — WebSocket 客户端
urllib3>=2.0                ✅ 必须 — HTTP 底层（httpx 依赖）
```

**僵尸依赖：`aiosqlite`** — 可安全移除。

**Go 依赖（`dmshoot-go/go.mod`）：**

| 包 | 版本 | 用途 |
|----|------|------|
| `gin-gonic/gin` | v1.10.0 | HTTP 路由框架 |
| `gorilla/websocket` | v1.5.3 | WebSocket 支持 |
| `modernc.org/sqlite` | v1.34.0 | 纯 Go SQLite 驱动（无 CGO） |

---

### 2. 环境配置与密钥

**问：B站和抖音的 API Key、Cookie、签名密钥存在哪？**

| 配置项 | 存储位置 | 说明 |
|--------|---------|------|
| DeepSeek API Key | SQLite `config` 表 `api_key` | GUI 设置页面输入，非硬编码 |
| DeepSeek Base URL | 默认 `https://api.deepseek.com` | `models.py:49` 硬编码，可在设置页修改 |
| 各平台 Cookie | SQLite `config` 表（独立字段） | 扫码后自动写入 |
| 小红书 Cookie | 环境变量 `XHS_COOKIE` 优先 → 数据库 → `data/xhs_cookie.txt` | 三级回退 |
| Go 数据库路径 | Go 端硬编码 `H:/DMShoot/dmshoot/data/dmshoot.db` | `main.go:24`，Python 端通过 `DMSHOOT_DB` 环境变量传入 |

**没有 `.env` 文件**（仅 `docker/.env` 用于 mitmproxy 环境，不影响主程序）。生产密钥不硬编码在代码中。

---

### 3. 部署流程

**问：dmshoot 部署到服务器需要几步？写下从 `git clone` 到 `python main.py` 跑起来的完整命令。**

目前没有正式部署文档。手动步骤：

```bash
# —— 第一步：克隆 ——
git clone <repo_url> DMShoot
cd DMShoot

# —— 第二步：Python 环境 ——
python -m venv venv
source venv/bin/activate      # Linux/Mac
# venv\Scripts\activate       # Windows

pip install -r requirements.txt

# —— 第三步：Playwright 浏览器 ——
python -m playwright install chromium

# —— 第四步：外部依赖（抖音签名） ——
cd external/DouYin_Spider
pip install -r requirements.txt
cd ../..

# —— 第五步：启动 ——
python main.py

# —— 可选：性能分析 ——
python main.py --profile

# —— 可选：Go 后端 ——
# 需要先安装 Go，然后在 GUI 设置页一键切换后端
```

> ⚠️ 缺少：`dmshoot/data/` 目录自动初始化、Go 模块编译的自动化、服务器无头部署（GUI 程序不适合纯服务器）。

---

## 四、已知问题

### 1. 隐藏的异常吞没

**问：除了 `except: pass`，还有没有其他隐藏的错误？**

存在以下模式：

| 模式 | 影响 | 典型位置 |
|------|------|---------|
| `except: pass` | 完全静默，排错无从下手 | 快手 adapter 8 处 |
| `except Exception: pass` | 同样吞异常 | `go_bridge.py:161` |
| `except: logger.error(e)` | 只记异常消息，无堆栈 | `adapter.py:103` |
| `except Exception as e:` 不记日志 | 捕获了但无迹可查 | 多处 adapter |

---

### 2. 性能瓶颈

**问：你觉得 dmshoot 最慢的操作是什么？有没有性能剖析数据？**

**排名（按实际影响）：**

| 瓶颈 | 原因 | 位置 |
|------|------|------|
| 1. B站历史同步 | `bsync()` 阻塞串行拉取大量会话 | `_sync_history()` |
| 2. 数据库写入 | 热轮询循环逐条 `INSERT` | 各 adapter `_poll_messages` |
| 3. 抖音签名 | 每次调用 spawn Node.js 子进程 | `douyin_signer.py` |

**性能数据：** `python main.py --profile` 会生成 `docs/profile_MMDD_HHMM.prof` 文件。但截至目前**尚未在 profiling 下运行过**，没有实际 `cProfile` 数据。

**已实施的优化：**

| 优化项 | 状态 |
|--------|------|
| SQLite WAL 模式 | ✅ 已启用 |
| 批量写入（`executemany`） | ✅ 已实现 |
| `@dataclass(slots=True)` | ✅ 已实施 |
| `frozenset` 常量 | ✅ 已实施 |
| 共享线程池 + 背压控制 | ✅ 已实施 |
| AdaptivePoller 自适应间隔 | ✅ 代码就绪 |
| Token bucket 限流器 | ✅ 已实现 |
| asyncio 事件循环复用 | 🔄 部分 |
| Go 批量写入器 | 🔄 代码就绪，未深度集成 |

详细优化方案见 `docs/DMShoot_性能优化方案.md`。

---

### 3. 放弃小红书和快手的真正原因

**问：放弃小红书和快手的技术障碍具体是什么？**

总结自 `docs/XHS_IM_逆向日志.md`，**24 种方法全部尝试，全部失败**。核心是一个三方互相保护的死结：

```
要抓移动端 IM token
    └→ 必须绕过 SSL Pinning
        └→ 必须在 ARM64 环境运行 Frida
            └→ 当前只有 x86 模拟器（LDPlayer/MuMu/AVD）
                └→ ARM→x86 翻译层（libhoudini）对 hook 库不兼容
                    └→ SIGSEGV / ptrace 被拦截 / DEX 合并崩溃
```

**SSL Pinning 三层防护（每层独立，需同时击穿）：**

| 层 | 实现位置 | 尝试方案 | 结果 |
|----|---------|---------|------|
| Java CertificatePinner | DEX Application 层 | Smali 字节码修补 | DEX 合并错误，XhsApplication 丢失致启动 crash |
| 自定义 OkHttp Platform | Framework 层 | Frida Hook `checkServerTrusted` | 内核 5.15 拦截 ptrace 系统调用 |
| libshield.so | Native C 层 | 无法 hook | ARM64-only binary，x86 无法加载 |

**Web 端权限不足：** 所有 IM 端点在 Web Cookie 下返回 `-100 登录已过期` 或 `406 无权限`，必须用移动端 app token。

**已就绪的代码：** XHS 签名系统（x-s/x-t）、adapter、IM client 已完整实现，token 到手即可激活。

**唯一可行路径：** 真机 Android 14 + Magisk root + LSPosed + Frida。当前项目所处的 x86 模拟器环境无法攻克。

---

## 五、总体评价

| 维度 | 评分 | 说明 |
|------|:----:|------|
| 核心功能 | ★★★★☆ | B站/抖音私信收发 + AI 回复可用 |
| 代码结构 | ★★★☆☆ | 插件架构合理，MainWindow 偏重（God Object） |
| 异常处理 | ★★☆☆☆ | 27+ 处裸 `except:` 吞异常 |
| 测试 | ★☆☆☆☆ | 3 个测试文件，无覆盖率，Go 零测试 |
| 日志 | ★★☆☆☆ | 仅控制台，不写文件，无持久化 |
| 告警 | ★☆☆☆☆ | 无外部通知渠道 |
| 文档 | ★★★☆☆ | 有优化方案、逆向日志，缺部署文档 |

**最值的三项改进（投入小、收益大）：**

1. 日志加 `RotatingFileHandler` — 排查线上问题必需
2. 收窄所有 `except:` 为具体异常类型 — 降低排错成本
3. 给 Go 模块加 `_test.go` 基准测试 — 验证批量写入收益
