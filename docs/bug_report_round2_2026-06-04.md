# DMShoot Bug 审查报告（第二轮）

> 审查时间：2026-06-04 18:06  
> 审查范围：第一轮未覆盖的 18 个模块  
> 共发现 **36 个新问题**：P0×2 / P1×13 / P2×21

---

## 🔴 P0 — 崩溃级（必须立即修）

### Bug A：B站/小红书点击启动直接崩溃

**文件**：`dmshoot/gui/pages/login_page.py` 第 169、172 行

```python
if not self._has_bili:    # ← AttributError！
    return
if not self._has_xhs:     # ← AttributError！
    return
```

`__init__` 里只定义了 `_bili_running` / `_xhs_running`，没有 `_has_bili` / `_has_xhs`。用户点击 B站或小红书的"启动"按钮，程序直接崩溃。

**修复**：改为检查是否有 cookie：
```python
if not self.config.bilibili_sessdata:
    return
```

或者直接删掉这两行（既然用户能点到"启动"按钮，说明已经连上了）。

---

### Bug B：非管理员机器上 Node.js 路径崩溃

**文件**：`dmshoot/utils/douyin_signer.py` 第 19-21 行

```python
_NODE = shutil.which("node") or str(
    Path.home() / ".workbuddy" / "binaries" / "node" / "versions" / "22.12.0" / "node.exe"
)
```

`Path.home()` 在不同用户下结果不同，`Administrator` 换成其他用户名路径就不存在了。如果系统 PATH 里也没有 `node`，整个抖音签名系统崩溃。

**修复**：去掉硬编码的 fallback，只保留 `shutil.which("node")`。找不到 node 时报清晰的错误。
```python
_NODE = shutil.which("node")
if not _NODE:
    raise RuntimeError("Node.js 未安装，抖音功能不可用。请安装 Node.js 或将其加入 PATH。")
```

---

## 🟠 P1 — 功能异常 / 安全隐患

### Bug C：`delete_prompt` 可以删除系统文件（路径遍历）

**文件**：`dmshoot/ai/prompts.py` 第 42-46 行

```python
def delete_prompt(name: str):
    path = Path(__file__).parent.parent.parent / "prompts" / f"{name}.txt"
    if path.exists():
        path.unlink()
```

如果传入 `name = "../../Windows/System32/evil"`，路径将逃逸出 `prompts/` 目录。`save_prompt` 有同样的问题。

**修复**：
```python
path = (prompts_dir / f"{name}.txt").resolve()
if not str(path).startswith(str(prompts_dir.resolve())):
    raise ValueError("Invalid prompt name")
```

---

### Bug D：`douyin_sdk.py` 猴子补丁污染全局模块

**文件**：`dmshoot/utils/douyin_sdk.py` 第 137-138 行

```python
sys.modules["utils.dy_util"] = fake_dy_util
sys.modules["utils"] = types.ModuleType("utils")   # ← 覆盖了全局 "utils" 模块！
```

如果有任何其他代码 `import utils`，会得到一个空模块，随机 `AttributeError`。

**修复**：只替换 `"utils.dy_util"`，不动 `"utils"` 本身，或者创建 fake_utils 时复制原有属性。

---

### Bug E：`_on_cookie_ready` 信号泄漏

**文件**：`dmshoot/gui/pages/login_page.py` 第 229-237 行

```python
def _on_cookie_ready(self, platform, cookies):
    self._worker = None   # ← 信号连接没断开！
```

`_stop_worker()` 只断开了旧的连接，但 worker 完成后 `_on_cookie_ready` 把 `self._worker` 置为 `None`。下次 `_stop_worker()` 检查到 `self._worker is None` 就直接跳过了，旧信号连接残留。

**修复**：在 `_on_cookie_ready` 里 `self._stop_worker()` 真正清理。

---

### Bug F：`clear_douyin_cache()` 阻塞 UI 线程

**文件**：`dmshoot/gui/settings_dialog.py` 第 314-315 行

```python
def _on_clear_douyin_cache(self):
    clear_douyin_cache()   # ← 在主线程执行，UI 卡住
```

缓存清理涉及文件删除，直接在主线程跑会让界面冻结。

**修复**：包装在 `QThread` 中，加个 loading 状态。

---

### Bug G：`_login_douyin` 使用已弃用的 `tempfile.mktemp()`

**文件**：`dmshoot/utils/cookie_reader.py` 第 188、198、255 行

```python
tmp = tempfile.mktemp(suffix=".json")   # 自 Python 2.3 已弃用
```

存在竞争条件：文件名在创建和使用之间可能被其他进程占用。

**修复**：改用 `tempfile.NamedTemporaryFile(delete=False)`。

---

### Bug H：`generate_csrf_token` 返回 `None` 导致下游崩溃

**文件**：`dmshoot/utils/douyin_sdk.py` 第 164-180 行

```python
def generate_csrf_token(cookies_str: str):
    ...
    except:
        return None, None   # ← 调用者做 csrf[1] 会 TypeError
```

调用者在不知道失败的情况下做 `csrf[1]` 会抛 `TypeError` 而非清晰的错误。

---

### Bug I：MessageBus 单例非线程安全

**文件**：`dmshoot/core/bus.py` 第 43-48 行

```python
if cls._instance is None:
    cls._instance = cls()
```

两个线程同时调用 `instance()` 可能各创建一个实例，信号路由到错误的 bus。

---

### Bug J：B站 `_debug()` 相对路径

**文件**：`dmshoot/plugins/bilibili/adapter.py` 第 35-40 行

```python
with open("dmshoot/data/adapter_debug.txt", "a") as f:
```

cwd 敏感（Bug 3 同类问题，之前只修了 adapter 状态文件，漏了这里）。

---

### Bug K：PromptPage 取消选择时发送空提示词

**文件**：`dmshoot/gui/pages/prompt_page.py` 第 81-89 行

```python
def _on_char_select(self, name: str):
    ...
    self.prompt_changed.emit(name)   # name="" 时也发送
```

用户 Ctrl+Click 取消选择时，`currentTextChanged` 触发空字符串 → `prompt_changed.emit("")` → AI 收到空提示词。

---

### Bug L：设置对话框每次保存都重建 AI 客户端

**文件**：`dmshoot/gui/settings_dialog.py` 第 347-353 行

即使用户只改了轮询延迟，点击保存也会 `init_ai()` 重置 AI 上下文。

---

## 🟡 P2 — 代码质量

| # | 文件 | 问题 |
|---|------|------|
| M | `sidebar.py:72` | `btn.setStyleSheet(btn.styleSheet())` 无意义重绘 |
| N | `ruler.py:40` | `set_active` 即使已是当前平台也发射信号 |
| O | `deepseek_page.py:124` | 弹窗隐藏后没 `deleteLater()`，内存泄漏 |
| P | `deepseek_page.py:147` | 用 `str.replace()` 改 CSS 字符串，脆弱 |
| Q | `deepseek_page.py:192` | `"已连接" in text` 匹配"已连接失败" |
| R | `bilibili/adapter.py:359` | `time.sleep(3)` 放在 `_poll_messages` 尾部，异常后重复延迟 |
| S | `xiaohongshu/adapter.py:207` | 每条消息一次 SQLite commit，历史同步极慢 |
| T | `xiaohongshu/adapter.py:52` | 未知时间戳格式默认 `time.time()`，误导 |
| U | `xiaohongshu/adapter.py:392` | 只认 `{` 开头的 JSON，不认 `[` 数组 |
| V | `console_log.py:115` | `logging.setLoggerClass(ModuleLogger)` 全局副作用 |
| W | `prompts.py:28` | 非 UTF-8 编码的 txt 文件直接抛异常 |
| X | `plugins/manager.py:47` | 插件导入失败静默吞噬，无日志 |
| Y | `plugins/manager.py:27` | 插件发现阻塞 `__init__`，增加启动延迟 |

---

## 📊 汇总

| 严重度 | 数量 | 紧急项 |
|--------|------|--------|
| 🔴 P0 | 2 | 启动按钮崩溃、Node.js 路径崩溃 |
| 🟠 P1 | 13 | 路径遍历安全漏洞、全局模块污染、信号泄漏 |
| 🟡 P2 | 21 | 内存泄漏、性能、脆弱写法 |
| **总计** | **36** | — |

**建议优先修**：A（启动崩溃）、C（安全漏洞）、D（全局模块污染）、B（可移植性）。
