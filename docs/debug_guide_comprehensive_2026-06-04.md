# DMShoot 综合调试文档（第三轮）

> 审查时间：2026-06-04 18:25
> 覆盖范围：GUI 操作层 + 第二轮发现的 36 个代码层 Bug
> 总计：**49 个问题**（操作层 13 + 代码层 36）

---

## 一、🔴 崩溃级（P0）— 4 个

### Bug 1：B站/小红书点击启动按钮 → AttributeError 闪退

**文件**：`dmshoot/gui/pages/login_page.py` 第 169、172 行

```python
if not self._has_bili:    # ← AttributeError
    return
if not self._has_xhs:     # ← AttributeError
    return
```

**根因**：`__init__` 只定义了 `_bili_running` / `_xhs_running`，没有 `_has_bili` / `_has_xhs`。

**触发条件**：用户扫码登录 B站或小红书后，点击"启动"按钮。

**修复方案**：
```python
# 方案 A：删掉这两行（用户能点到"启动"说明已经连上了）
# 方案 B：改为检查是否有 cookie
if not self.config.bilibili_sessdata:
    return
```
同时第 169-173 行整体建议删除——抖音没有对应的 `_has_douyin` 检查也能正常工作。

**验证**：登录 B站 → 点击"启动" → 不再崩溃，适配器正常启动。

---

### Bug 2：非 Administrator 用户 → Node.js 路径 FileNotFoundError

**文件**：`dmshoot/utils/douyin_signer.py` 第 19-21 行

```python
_NODE = shutil.which("node") or str(
    Path.home() / ".workbuddy" / "binaries" / "node" / "versions" / "22.12.0" / "node.exe"
)
```

**根因**：fallback 路径包含硬编码的 `Administrator` 用户名和 `.workbuddy` 目录。其他用户/机器上 PATH 无 node 时直接崩。

**修复方案**：
```python
_NODE = shutil.which("node")
if not _NODE:
    raise RuntimeError(
        "Node.js 未找到。请安装 Node.js 或将其加入系统 PATH。"
        "下载地址: https://nodejs.org/"
    )
```
去掉硬编码 fallback，改为清晰的报错。

**验证**：删除 PATH 中的 node → 启动 → 看到清晰的报错信息而非 FileNotFoundError。

---

### Bug 3：`delete_prompt` 路径遍历 → 可删除系统文件（安全漏洞）

**文件**：`dmshoot/ai/prompts.py` 第 42-46 行

```python
def delete_prompt(name: str):
    path = Path(__file__).parent.parent.parent / "prompts" / f"{name}.txt"
    if path.exists():
        path.unlink()
```

**根因**：`name` 未做路径清理，`"../../Windows/System32/drivers/etc/hosts"` 会逃逸出 `prompts/` 目录。`save_prompt` 第 34-39 行同样受影响。

**修复方案**：
```python
def delete_prompt(name: str):
    # 禁止路径分隔符和上级引用
    if any(c in name for c in ("/", "\\", "..")):
        raise ValueError(f"非法提示词名称: {name}")
    prompts_dir = Path(__file__).parent.parent.parent / "prompts"
    path = (prompts_dir / f"{name}.txt").resolve()
    if not str(path).startswith(str(prompts_dir.resolve())):
        raise ValueError(f"路径越界: {name}")
    if path.exists():
        path.unlink()
```

`safe_prompt_name(name)` 抽取为共用函数，`save_prompt` 和 `delete_prompt` 都调用。

**验证**：调用 `delete_prompt("../../test")` → 抛 ValueError 而非删除文件。

---

### Bug 4：`douyin_sdk.py` `sys.modules["utils"]` 全局污染

**文件**：`dmshoot/utils/douyin_sdk.py` 第 137-138 行

```python
sys.modules["utils.dy_util"] = fake_dy_util
sys.modules["utils"] = types.ModuleType("utils")  # ← 覆盖全局！
```

**根因**：替换 `sys.modules["utils"]` 为空模块。任何后续 `import utils` 的代码都会得到一个空壳。

**修复方案**：
```python
# 只在 "utils.dy_util" 做替换，不动 "utils" 本身
sys.modules["utils.dy_util"] = fake_dy_util

# 如果 SDK 内部需要 from utils import ... 才需要 fake_utils
# fake_utils = types.ModuleType("utils")
# fake_utils.dy_util = fake_dy_util
# sys.modules["utils"] = fake_utils  # 仅在确认无冲突时
```

**验证**：检查是否有其他库依赖 `import utils`（`grep -r "import utils" dmshoot/ external/`），确认无冲突。

---

## 二、🟠 功能异常（P1）— 14 个

### Bug 5：清理平台 → UI 冻结 3 秒

**文件**：`dmshoot/gui/main_window.py` 第 419-423 行 → `adapter.py` 第 91 行

**用户路径**：登录页 → 点"清理"按钮

**根因**：`_clear_cookie` → `clear_platform.emit` → `_on_clear_platform` → `_stop_adapter_from_ui` → `adapter.stop()` → `self.wait(3000)`。

**修复方案**：`_stop_adapter_from_ui` 改为异步停止：
```python
def _stop_adapter_from_ui(self, platform: str):
    adapter = self._adapters.pop(platform, None)
    if adapter and hasattr(adapter, "stop"):
        adapter.stop()  # 已在 stop() 里做了 quit+wait+terminate
    # 不阻塞 UI，让 adapter 在后台线程自行结束
```

**验证**：清理平台 → UI 不卡顿。

---

### Bug 6：设置页保存 → AI 上下文全清

**文件**：`dmshoot/gui/settings_dialog.py` 第 346-353 行

**根因**：`_on_save` 无论改了什么字段都调 `init_ai()`，重建全局 AI 实例。

**修复方案**：
```python
def _on_save(self):
    # ... 保存 config ...
    # 只在 AI 关键字段有变化时才重建
    needs_ai_reinit = (
        self.config.api_key != old_api_key or
        self.config.model != old_model or
        self.config.prompt_preset != old_prompt
    )
    if needs_ai_reinit and self.config.api_key:
        init_ai(...)
```
在 `__init__` 中保存旧值做对比。

**验证**：改延迟时间 → 保存 → AI 上下文不丢失。

---

### Bug 7：提示词取消选择 → 空提示词发送

**文件**：`dmshoot/gui/pages/prompt_page.py` 第 81-89 行

**根因**：`_on_char_select` 无条件 `prompt_changed.emit(name)`，包括 name="" 时。

**修复方案**：
```python
def _on_char_select(self, name: str):
    if not name:
        return  # 取消选择时不发送
    if name in self._char_prompts:
        self.editor.setPlainText(self._char_prompts[name])
        self.prompt_changed.emit(name)
```
`_on_behavior_select` 同样处理。

**验证**：提示词页 Ctrl+Click 取消 → AI 不触发。

---

### Bug 8：设置页输入框改了值 → 点取消没取消

**文件**：`dmshoot/gui/settings_dialog.py` 第 186-194 行

**根因**：`QLineEdit(self.config.api_key)` 直接绑定到 config 对象。用户在输入框改值 → config 对象同步被修改 → 点取消 → `reject()` 关窗口但 config 已脏。

**修复方案**：用副本做隔离：
```python
self._original_config = config  # 保留原始引用
# 输入框绑定到副本
self.api_key_input = QLineEdit(config.api_key)  # 字符串副本，不会反向修改
```
或在 `reject()` 中恢复：`database.load_config()` 回读。

**验证**：改 API Key → 点取消 → 重新打开设置 → API Key 没变。

---

### Bug 9："登录后自动监听"只对 B站生效

**文件**：`dmshoot/gui/main_window.py` 第 398 行 + `login_page.py` 第 132 行

**根因**：`auto_monitor` 绑的是 `config.bilibili_auto_monitor`，抖音和小红书没有这个自动启动逻辑。hint 说"每 3 秒轮询"但抖音用 WS 实时，小红书也是 3 秒轮询——文案不准确。

**修复方案**（最小改动）：
```python
# hint 改为
self.auto_hint = QLabel("勾选后登录即自动开始监听（当前仅支持B站）")
```
或扩展为每个平台单独的 auto_monitor 开关。

**验证**：未勾选时登录抖音 → 不自动启动。勾选后登录 B站 → 自动启动。

---

### Bug 10：扫码时连点两次 → 两个浏览器窗口

**文件**：`dmshoot/gui/pages/login_page.py` 第 219-233 行

**根因**：`_auto_fetch` 调 `_stop_worker()` → `wait(2000)`，但 worker 的 `run()` 在 `asyncio.run()` 阻塞中，`quit()` 无法中断。2 秒超时后 `_stop_worker()` 直接返回，新 worker 启动。

**修复方案**：加个防重复标志：
```python
def _auto_fetch(self, platform: str):
    if self._worker and self._worker.isRunning():
        self.dy_status.setText("已有浏览器在扫码，请完成当前操作")
        return
    ...
```
或在按钮点击时 `btn_dy.setEnabled(False)`，扫码完成后恢复。

**验证**：快速双击扫码 → 只有一个浏览器窗口。

---

### Bug 11：清理 Cookie 后侧边栏状态灯不更新

**文件**：`dmshoot/gui/pages/login_page.py` 第 265-286 行

**根因**：`_clear_cookie` 把 `_dy_running` 置为 False，但没有发信号通知 `main_window.sidebar` 更新状态灯。侧边栏仍显示 ●。

**修复方案**：`_clear_cookie` 末尾加：
```python
self.bus.set_platform_status(platform, "离线", "")
# 或
self.sidebar.update_status(platform, "✕")
```
但从 LoginPage 到 Sidebar 没有直接引用。走 bus 比较干净：
```python
# _clear_cookie 末尾
self.clear_platform.emit(platform)  # 已存在
# main_window._on_clear_platform 已经有 sidebar.update_status("✕")
```
实际上 `_on_clear_platform` 确实会更新侧边栏（`main_window.py:387`），需要确认 `clear_platform` 信号确实触发到了。

**验证**：清理抖音 Cookie → 侧边栏抖音从 ● 变 ✕。

---

### Bug 12："启用平台"复选框无效

**文件**：`dmshoot/gui/settings_dialog.py` 第 237、257 行

**根因**：`dy_enabled` / `bili_enabled` 存进了 config，但全项目没有任何代码检查 `config.douyin_enabled` / `config.bilibili_enabled`。

**修复方案**：二选一：
- 在 `_start_adapter` 中检查：`if platform == "douyin" and not self.config.douyin_enabled: return`
- 或者直接删掉这两个无用的复选框

**验证**：取消勾选"启用抖音" → 保存 → 抖音适配器不再启动。

---

### Bug 13：小红书配置入口缺失

**文件**：`dmshoot/gui/settings_dialog.py` 第 230-273 行

**根因**：`_create_platform_tab()` 只有抖音和 B站的分组，没有小红书。LoginPage 有小红书扫码，但设置页没有对应管理。

**修复方案**：在平台标签页加小红书分组：
```python
xhs_group = QGroupBox("小红书")
xhs_form = QFormLayout()
self.xhs_cookie_input = QLineEdit(self.config.xhs_cookie)
xhs_form.addRow("Cookie:", self.xhs_cookie_input)
xhs_group.setLayout(xhs_form)
layout.addWidget(xhs_group)
```

**验证**：设置 → 平台标签页 → 能看到小红书配置。

---

### Bug 14：`console_log.py` `setLoggerClass` 全局副作用

**文件**：`dmshoot/utils/console_log.py` 第 115 行

```python
logging.setLoggerClass(ModuleLogger)
```

**根因**：所有 logger（包括第三方库的）都变成 `ModuleLogger` 实例。如果某库在 `extra` 字典中用 `thinking` 键名，会意外触发思考日志格式。

**修复方案**：只对 DMShoot 的 logger 设置类：
```python
# 不用 setLoggerClass，改在 get_logger 中手动设置
def get_logger(name: str) -> ModuleLogger:
    logger = logging.getLogger(name)
    logger.__class__ = ModuleLogger  # 只管当前实例
    return logger
```

**验证**：检查 `httpx`、`bilibili_api` 等第三方库的日志输出是否正常。

---

### Bug 15：MessageBus 单例非线程安全

**文件**：`dmshoot/core/bus.py` 第 43-48 行

**根因**：`if cls._instance is None: cls._instance = cls()` 无锁保护。

**修复方案**：
```python
import threading
_lock = threading.Lock()

@classmethod
def instance(cls):
    if cls._instance is None:
        with _lock:
            if cls._instance is None:
                cls._instance = cls()
    return cls._instance
```

**验证**：多线程场景下不会出现多个 bus 实例。

---

### Bug 16：B站 `_debug()` 相对路径

**文件**：`dmshoot/plugins/bilibili/adapter.py` 第 35-40 行

```python
with open("dmshoot/data/adapter_debug.txt", "a") as f:
```

**根因**：相对路径，依赖 cwd。与之前修的 Bug 3 同类问题。

**修复方案**：
```python
_DEBUG_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "adapter_debug.txt"

def _debug(msg: str):
    try:
        with open(_DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    except:
        pass
```

**验证**：从不同目录启动 → debug 文件仍在项目目录下。

---

### Bug 17：`_on_cookie_ready` 信号泄漏

**文件**：`dmshoot/gui/pages/login_page.py` 第 236-237 行

**根因**：第 237 行 `self._worker = None`，但没有断开 `result` 信号。如果同一个页面生命周期内有多次扫码，旧连接残留。

**修复方案**：在 `_on_cookie_ready` 开头就清理：
```python
def _on_cookie_ready(self, platform: str, cookies):
    if self._worker:
        try: self._worker.result.disconnect(self._on_cookie_ready)
        except: pass
    self._worker = None
    ...
```

**验证**：扫码 → 完成 → 再扫码 → 不触发两次回调。

---

### Bug 18：`clear_douyin_cache()` 阻塞 UI 线程

**文件**：`dmshoot/gui/settings_dialog.py` 第 311-319 行

**根因**：直接在按钮点击回调中执行文件删除操作。

**修复方案**：包装在 QThread：
```python
def _on_clear_douyin_cache(self):
    self.clear_cache_btn.setEnabled(False)
    self.clear_cache_btn.setText("清除中...")
    worker = _ClearCacheWorker()
    worker.done.connect(self._on_cache_cleared)
    worker.start()
```

**验证**：点清除缓存 → UI 不卡顿。

---

## 三、🟡 代码质量（P2）— 操作影响 5 个 + 次要 12 个

### Bug 19：首页空状态无引导

**文件**：`dmshoot/gui/pages/home_page.py` 第 57 行 → `chat_view.py` 第 85 行

**用户视角**：刚启动时通讯录为空，右边显示"选择会话"。用户不知道下一步要干什么。

**修复方案**：空状态时显示引导文字 + 快捷按钮：
```python
# 通讯录为空时
if not sessions:
    empty_label = QLabel("暂无会话\n\n请前往「登录」页面扫码连接平台")
    empty_label.setAlignment(Qt.AlignCenter)
```
或直接显示"去登录"按钮跳转。

---

### Bug 20：监控面板不显示平台信息

**文件**：`dmshoot/gui/monitor_panel.py` 第 25-42 行

**用户视角**：看到"小明 说：你好"，但不知道这来自抖音还是 B站。

**修复方案**：在 `ReplyLogEntry` 中显示平台图标或标签。`ChatMessage` 没有存储 platform，需要从外面的 context 传入：
```python
# main_window.py _on_ai_response 中
platform = session_id.split(":")[0]
self.monitor.add_reply_log(...)  # 传 platform 参数
```

---

### Bug 21：平台切换时联系人列表闪烁

**文件**：`dmshoot/gui/pages/home_page.py` 第 72-77 行

**根因**：`_do_load_contacts` → `set_sessions` 先删旧列表、再加新列表，中间有短暂空白状态。

**修复方案**：用 `setUpdatesEnabled(False/True)` 包裹更新：
```python
def _do_load_contacts(self):
    sessions = database.get_sessions(self._current_platform)
    ...
    self.contacts.list.setUpdatesEnabled(False)
    self.contacts.set_sessions(sessions)
    self.contacts.list.setUpdatesEnabled(True)
```

---

### Bug 22：三个平台"启动"按钮逻辑不一致

**文件**：`dmshoot/gui/pages/login_page.py` 第 166-188 行

**根因**：抖音检查 `_dy_running`，B站和小红书检查不存在的 `_has_bili` / `_has_xhs`。

**修复方案**：统一为检查 `_running` 标志：
```python
def _toggle_monitor(self, platform: str):
    running = {"douyin": self._dy_running,
               "bilibili": self._bili_running,
               "xiaohongshu": self._xhs_running}.get(platform, False)
    if running:
        self.stop_monitor.emit(platform)
    else:
        self.start_monitor.emit(platform)
```

---

### Bug 23：设置页弹窗关闭 → 内存泄漏

**文件**：`dmshoot/gui/deepseek_page.py` 第 123-126 行 / `settings_dialog.py` 第 16-85 行

`DeepSeekPage._toggle_popup` 中 `self._popup.hide()` 后没有 `deleteLater()`。`GlassPopup` 在 `show_glass_popup` 中创建但从未 delete。

**修复方案**：弹窗 close/hide 后 setAttribute(Qt.WA_DeleteOnClose)。

---

### 次要 P2（12 个）

| # | 文件 | 行 | 问题 |
|---|------|----|------|
| 24 | `sidebar.py` | 72 | `btn.setStyleSheet(btn.styleSheet())` 空操作重绘 |
| 25 | `ruler.py` | 40 | `set_active` 即使已是当前平台也发射信号 |
| 26 | `deepseek_page.py` | 192 | `"已连接" in text` 会匹配"已连接失败" |
| 27 | `deepseek_page.py` | 147 | `str.replace()` 操作 CSS，脆弱 |
| 28 | `prompts.py` | 28 | 非 UTF-8 txt 直接 `UnicodeDecodeError` |
| 29 | `plugins/manager.py` | 47 | 插件导入失败静默无日志 |
| 30 | `plugins/manager.py` | 27 | 插件发现阻塞 `__init__` |
| 31 | `bilibili/adapter.py` | 359 | `time.sleep(3)` 在 `_poll_messages` 尾部，与 `_poll_loop` 重复 |
| 32 | `xiaohongshu/adapter.py` | 207 | 每条消息一次 SQLite commit，历史同步极慢 |
| 33 | `xiaohongshu/adapter.py` | 52 | 未知时间戳回退 `time.time()` |
| 34 | `xiaohongshu/adapter.py` | 392 | 只认 `{` 不认 `[` JSON 数组 |
| 35 | `cookie_reader.py` | 188 | `tempfile.mktemp()` 已弃用 |
| 36 | `cookie_reader.py` | 190 | `asyncio.run()` 在 QThread 中 |
| 37 | `douyin_sdk.py` | 63 | `verify=False` 禁用 SSL |
| 38 | `douyin_sdk.py` | 180 | `generate_csrf_token` 失败返回 `None,None` |
| 39 | `douyin_signer.py` | 33 | JS 文件读取无 `FileNotFoundError` 保护 |
| 40 | `platform_connector.py` | 6 | `verify_douyin` async 函数可能被同步调用 |

---

## 四、性能类（跨文件）— 3 个

### Bug 41：设置页"启用平台"导致的额外 adapter 重启

用户勾选"启用抖音" → 保存 → `_on_save` 无条件 `init_ai()` → 但不会重启 adapter。如果 adapter 之前是停止的，这个复选框不能用来启动它——功能断裂。

### Bug 42：`_auto_login` 三个平台串行验证

```python
# main_window.py:296-301
if self.config.bilibili_sessdata:
    self._verify_saved("bilibili")
if self.config.douyin_cookie:
    self._verify_saved("douyin")
if self.config.xhs_cookie:
    self._verify_saved("xiaohongshu")
```

三个平台串行验证，每个可能耗时 15 秒（网络超时）。三个都有 cookie 时启动延迟可达 45 秒。改为并行启动。

### Bug 43：历史消息加载时 100 条全量创建 BubbleWidget

`ChatView.load_messages` 虽有 `rebind()` 复用逻辑，但如果切换到一个有 500 条消息的会话，仍会创建 500 个 BubbleWidget。长会话应做虚拟滚动或分页加载。

---

## 五、修复优先级矩阵

| 优先级 | Bug # | 影响 | 修复难度 |
|--------|-------|------|----------|
| 🔴 即刻 | 1 | 点击按钮崩溃 | 删 2 行 |
| 🔴 即刻 | 3 | 安全漏洞 | 加 5 行校验 |
| 🔴 即刻 | 4 | 随机 AttributeError | 改 2 行 |
| 🟠 今天 | 2 | 换机器崩溃 | 改 3 行 |
| 🟠 今天 | 11 | 状态灯误导 | 确认信号链路 |
| 🟠 本周 | 5 | UI 冻结 | 改 adapter.stop |
| 🟠 本周 | 6 | AI 上下文丢失 | 加前后对比 |
| 🟠 本周 | 7 | 空提示词 | 加 1 行 guard |
| 🟡 有空 | 8 | 取消不生效 | 副本隔离 |
| 🟡 有空 | 19 | 新用户困惑 | 空状态引导 |

---

## 六、一次性批量修复建议

以下改动互不冲突，可一批提交：

### 改动组 1：login_page.py 一键修复 4 个 Bug

```python
# 1. 删掉 169-173 行（Bug 1: has_bili/has_xhs 不存在）
# 2. _auto_fetch 加防重复（Bug 10）
# 3. _on_cookie_ready 清理信号（Bug 17）
# 4. _toggle_monitor 统一逻辑（Bug 22）
```

### 改动组 2：安全相关 3 个 Bug

```python
# prompts.py: safe_prompt_name() 校验（Bug 3）
# douyin_sdk.py: 删掉 sys.modules["utils"] 覆盖（Bug 4）
# douyin_signer.py: 移除硬编码路径（Bug 2）
```

### 改动组 3：UX 体验 3 个 Bug

```python
# settings_dialog.py: 保存时只改 AI 时才 reinit（Bug 6）
# settings_dialog.py: 输入框用副本隔离（Bug 8）
# prompt_page.py: 空名不发送信号（Bug 7）
```
