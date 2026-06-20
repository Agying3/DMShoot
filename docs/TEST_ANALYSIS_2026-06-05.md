# DMShoot 测试分析报告

**日期**：2026-06-05
**分析范围**：全部 5 个测试文件，222+ 测试用例

---

## 一、总览

| 维度 | 评级 | 说明 |
|------|------|------|
| 测试覆盖广度 | ⭐⭐⭐⭐ | 核心模块覆盖良好，边缘模块有缺 |
| 测试覆盖深度 | ⭐⭐⭐ | 偏 happy path，异常/边界覆盖不足 |
| 测试框架成熟度 | ⭐⭐ | 自研框架功能原始，无参数化/夹具/标记 |
| 测试可维护性 | ⭐⭐⭐ | 结构清晰但大量重复代码 |
| 测试执行效率 | ⭐⭐⭐⭐ | 纯内存/临时文件，秒级跑完 |
| 综合评分 | **6.5/10** | 够用但不专业，有明确改进方向 |

## 二、测试文件一览

| 文件 | 用例数 | 覆盖模块 | 特点 |
|------|--------|----------|------|
| `test_dmshoot.py` | 82 | core, storage, ai, config, plugins, utils | 核心单元测试，覆盖最全面 |
| `test_dmshoot_douyin.py` | 48 | 抖音 SDK, 签名, Adapter, WS | 抖音专测，6 个用例已过期 |
| `test_dmshoot_gui.py` | 50 | GUI 组件, B站解析, Cookie, 信号集成 | 唯一涉及 GUI 的测试 |
| `test_new_features.py` | 42 断言 | proto_parser, XHS, AI hot-load | 新功能快速验证 |
| `test_screenshot.py` | 无断言 | 全应用 | GUI 截图诊断脚本，非测试 |

**总计**：约 **222 个测试用例**（除去 test_screenshot.py 的截图脚本）

## 三、测试框架分析

### 3.1 自研框架

项目**完全不依赖 pytest 或 unittest**，采用完全自研的轻量级测试框架：

```python
# 核心只有三个函数，不足 10 行逻辑
_results = []

def ok(name, detail=""):   # 记录通过
def fail(name, reason):    # 记录失败
def check(name, cond):     # 条件断言
```

运行方式：`python test_dmshoot.py`，每个文件独立可执行。

### 3.2 框架优缺点

| 优点 | 缺点 |
|------|------|
| 零依赖、零配置 | 无参数化测试（同一逻辑不同输入需重复写用例） |
| 秒级启动 | 无前置/后置夹具（setup/teardown 需手动处理） |
| 退出码反映通过/失败 | 无测试标记（skip/xfail/slow） |
| 对新人友好 | 失败信息简陋，只有断言失败提示 |
| | 无覆盖率收集 |
| | 无法按模块/标签筛选运行 |
| | 无法并行运行 |
| | 报告无结构化输出（纯 print） |

## 四、测试覆盖分析

### 4.1 已覆盖模块 ✅

| 模块 | 文件 | 覆盖程度 | 测试数 |
|------|------|----------|--------|
| `core/message.py` | test_dmshoot.py | ⭐⭐⭐⭐⭐ | 19 |
| `core/bus.py` | test_dmshoot.py | ⭐⭐⭐⭐ | 8 |
| `storage/models.py` | test_dmshoot.py | ⭐⭐⭐⭐ | 8 |
| `storage/database.py` | test_dmshoot.py | ⭐⭐⭐⭐ | 10 |
| `ai/backend.py` | test_dmshoot.py, test_new_features.py | ⭐⭐⭐⭐⭐ | ~20 |
| `ai/prompts.py` | test_dmshoot.py | ⭐⭐⭐ | 5 |
| `config/` | test_dmshoot.py | ⭐⭐⭐ | 5 |
| `plugins/manager.py` | test_dmshoot.py | ⭐⭐⭐ | 6 |
| `plugins/bilibili/adapter.py` | test_dmshoot_gui.py | ⭐⭐⭐⭐ | 14 |
| `plugins/douyin/adapter.py` | test_dmshoot_douyin.py | ⭐⭐⭐ | 16 |
| `plugins/xiaohongshu/adapter.py` | test_new_features.py | ⭐⭐⭐ | 14 |
| `utils/douyin_sdk.py` | test_dmshoot_douyin.py | ⭐⭐⭐⭐ | 13 |
| `utils/douyin_signer.py` | test_dmshoot_douyin.py | ⭐⭐ | 3 |
| `utils/cookie_reader.py` | test_dmshoot.py, gui | ⭐⭐⭐ | 7 |
| `utils/platform_connector.py` | test_dmshoot.py | ⭐⭐ | 2 |
| `utils/proto_msg_parser.py` | test_new_features.py | ⭐⭐⭐ | 9 |
| GUI 组件 | test_dmshoot_gui.py | ⭐⭐ | 14 |

### 4.2 未覆盖模块 ❌

| 模块 | 文件 | 风险 |
|------|------|------|
| `core/concurrency.py` | 并发管理器 | **高** — 背压控制、优先级调度未经验证 |
| `gui/main_window.py` | 主窗口 (684 行 God Object) | **高** — 最复杂组件零测试 |
| `gui/sidebar.py` | 侧边栏 | 中 |
| `gui/settings_dialog.py` | 设置对话框 | 中 |
| `gui/pages/` | 各页面（home/login/deepseek/prompt） | 中 |
| `gui/monitor_panel.py` | 监控面板 | 低（部分已测） |
| `gui/log_panel.py` | 日志面板 | 低（部分已测） |
| `utils/douyin_im_sync.py` | 三级缓存同步 | **高** — 最复杂的抖音逻辑，0 测试 |
| `utils/douyin_msg_sync.py` | 消息同步 | 中 |
| `utils/douyin_msg_parser.py` | 消息解析 | 中 |
| `utils/douyin_ws.py` | WebSocket 接收器 | 中 |
| `utils/console_log.py` | 终端日志 | 低 |

### 4.3 测试类型覆盖

| 测试类型 | 状态 | 说明 |
|----------|------|------|
| 单元测试 | ✅ 充足 | 222+ 个，核心逻辑覆盖良好 |
| 集成测试 | ⚠️ 极少 | 仅 1 个 Message→DB 全链路测试 |
| GUI 组件测试 | ⚠️ 部分 | 只测了小组件，主窗口零测试 |
| 端到端测试 | ❌ 无 | 无完整的"收消息→AI回复→发消息"流程测试 |
| 性能测试 | ❌ 无 | 无并发/背压/内存测试 |
| 回归/截图测试 | 🟡 有 | test_screenshot.py 提供视觉回归 |

## 五、测试质量分析

### 5.1 做得好的方面

1. **数据库测试隔离性好** — 所有 DB 测试使用临时文件 + `DB_PATH` monkey-patch，测试后清理，真实测试了 SQLite 行为
2. **测试命名清晰** — `test_message_from_douyin_text` / `test_adapter_parse_self_message` 等，一目了然
3. **AI 模块覆盖深入** — 提示词热更新、上下文管理、双提示词拼接、`MAX_CONTEXT` 限制都覆盖到位
4. **XHS 边界测试** — `_parse_timestamp` 覆盖了毫秒/秒/字符串/零/负数/无效字符串/极小数字 8 种情况
5. **protobuf varint 覆盖** — 单字节/双字节/三字节/保护位/最大值都有验证
6. **退出码机制** — `exit(0)` / `exit(1)` 可集成到 CI

### 5.2 做得不好的方面

1. **大量重复代码** — 5 个测试文件各自复制了 `ok()`/`fail()`/`check()` 函数，以及数据库临时文件模板代码
2. **断言信息不足** — `check("xxx", cond)` 失败时看不到期望值 vs 实际值
3. **无参数化** — 同一函数测多组输入需要写 N 个 check 行，无法自动展开
4. **异常类型不验证** — 只看 `return None` / `return []` / `return 0`，不检查抛出的异常类型
5. **Mock 策略粗糙** — `asyncio.run = lambda coro: original_run(fake_login(""))` 直接替换整个 `asyncio.run`，一旦协程不同就失效
6. **测试文件间有重复** — 插件注册、数据库配置往返等测试在多个文件中重复出现
7. **缺少测试文档** — 没有说明如何运行测试、依赖什么环境
8. **6 个过期测试未清理** — `test_dmshoot_douyin.py` 中有 6 个测试已过期但仍留在测试文件中

## 六、已知 Bug 与测试的关系

根据 `docs/STATUS_2026-05-30.md`，当前有 4 个已知 bug：

| Bug | 严重度 | 是否有测试覆盖 | 说明 |
|-----|--------|---------------|------|
| `_get_peer_uid_for_conv` 映射混乱 | P0 | ❌ 无 | 三缓同步逻辑缺少测试 |
| `_cached_messages` 未赋值 | P0 | ❌ 无 | 历史同步代码死路径 |
| AI 回复后 session 不更新 | P1 | ❌ 无 | 集成测试缺失 |
| `chat_view` 时间戳掩盖 | P1 | ❌ 无 | GUI 组件边界测试不足 |

**这 4 个 bug 全部发生在缺少测试覆盖的区域。** 如果当时有对应的测试，这些问题会在开发阶段就被发现。

## 七、改进建议

### P0（立即）— 堵漏洞

1. **补上关键缺失的测试**
   - `douyin_im_sync.py` 历史同步逻辑 → 这是 2 个 P0 bug 所在的模块
   - `main_window.py` 中 `_on_ai_response` → P1 bug 所在位置
   - `chat_view.py` 时间戳处理边界 → P1 bug 所在位置

2. **清理 6 个过期测试**
   - 或更新使之通过，或标注 skip 并注明原因

### P1（短期）— 提升效率

3. **引入 pytest**
   - 迁移成本低（`check(name, cond)` → `assert cond` 几乎 1:1 映射）
   - 立即获得：参数化（`@pytest.mark.parametrize`）、夹具（`@pytest.fixture`）、标记、覆盖率报告
   - 建议分两步：先安装 pytest + pytest-cov，保持原测试不改，新测试用 pytest；后续逐步迁移

4. **提取共享测试工具**
   - 创建 `tests/conftest.py`，统一 `temp_db` / `temp_config` 夹具
   - 消除 5 个文件中重复的 `ok/fail/check` 和临时 DB 代码

5. **增加参数化**
   ```python
   # 现在：N 个 check 行
   # 改后：一个参数化测试
   @pytest.mark.parametrize("input,expected", [
       (1714500000000, 1714500000),
       (1714500000, 1714500000),
       ("1714500000000", 1714500000),
       (0, 0), (-1, 0), ("abc", 0), (100, 0),
   ])
   def test_parse_timestamp(input, expected):
       assert abs(_parse_timestamp(input) - expected) < 60
   ```

### P2（中期）— 完善体系

6. **补充集成测试**
   - "收到消息 → 入 DB → AI 回复 → 发消息" 全链路
   - 使用真实 SQLite（已有的模式）但 mock AI 和平台 API

7. **补充性能测试**
   - `ConcurrencyManager` 背压行为（队列满 200 时）
   - 批量写入 1000 条消息的性能
   - 多平台并发轮询的资源使用

8. **加入 CI 能力**
   - `python -m pytest --cov=dmshoot --cov-report=term`
   - GitHub Actions / 本地 pre-commit hook
   - 至少保证 `test_dmshoot.py` 全绿才能提交

9. **GUI 集成测试**
   - 主窗口完整生命周期：启动 → 加载配置 → 连接平台 → 收消息 → 显示在 ChatView
   - 用 `pytest-qt` 或保持现有 QApplication 方案

### 建议的测试目录结构

```
H:\DMShoot\
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # 共享夹具 (temp_db, qapp, mock_bus)
│   ├── unit/
│   │   ├── test_message.py
│   │   ├── test_bus.py
│   │   ├── test_ai.py
│   │   ├── test_database.py
│   │   ├── test_proto_parser.py
│   │   ├── test_douyin_sdk.py
│   │   └── ...
│   ├── integration/
│   │   ├── test_message_flow.py  # 全链路
│   │   └── test_adapter_lifecycle.py
│   └── gui/
│       ├── test_main_window.py
│       ├── test_chat_view.py
│       └── test_login_flow.py
├── pytest.ini                    # pytest 配置
└── test_screenshot.py            # 保留为截图诊断工具
```

## 八、总结

DMShoot 的测试体系是**典型的单人项目风格**：轻量、够用、专注核心逻辑。222 个测试用例覆盖了消息模型、AI 后端、数据库、SDK 工具等关键模块，且测试隔离做得到位（临时 DB、mock 合理）。

但短板也很明显：

- **最复杂的逻辑零测试**：`douyin_im_sync.py`（三级缓存同步）和 `ConcurrencyManager`（背压调度）完全没有测试，而这里恰好是已知 P0 bug 的源头
- **GUI 主窗口零测试**：684 行的 God Object `MainWindow` 没有一行测试覆盖
- **自研框架是双刃剑**：省了 pytest 的学习成本，但失去了参数化、夹具、覆盖率等所有现代测试基础设施

**建议策略**：不用重写测试体系，渐进式改进。先补上最危险的 3 个测试缺口（三缓同步、AI 回复更新 session、时间戳边界），再逐步引入 pytest 提升效率。当前 222 个自研测试完全可以和新的 pytest 测试并存。
