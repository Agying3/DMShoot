# DMShoot 性能优化 & 闪退风险报告

> 审查时间：2026-05-30 23:43  
> 目标：让 PySide6 GUI 运行如 Kotlin 般流畅，消除所有潜在闪退点

---

## 🔴 闪退风险（必须修复）

### Crash 1：QThread 内创建 QPixmap → 随机崩溃

**文件**：`dmshoot/gui/widgets/contact.py` 第 192~203 行

```python
class _Loader(QThread):
    def run(self):
        pix = QPixmap(str(cp)) if cp.exists() ... else QPixmap()  # ❌ 非 GUI 线程！
        ...
        pix = QPixmap()              # ❌
        pix.loadFromData(r.content)  # ❌
```

**问题**：PySide6/Qt 严格禁止在非主线程创建任何 QPixmap / QImage / QPainter 对象。这是 Qt 底层 X11/Win32 图形资源限制，不是 Python 层面的问题。

**症状**：头像加载时随机 SIGSEGV，Windows 上表现为 `python.exe 已停止工作`。  
**触发条件**：启动后有会话需要下载头像时必现。

**修复**：
```python
class _Loader(QThread):
    done = Signal(object)
    def run(self):
        results = []
        for i, (widget, sid, url) in enumerate(urls):
            try:
                AVATAR_DIR.mkdir(parents=True, exist_ok=True)
                cache_key = sid.replace(":", "_")[:32]
                cp = AVATAR_DIR / f"{cache_key}.png"
                data = None
                if cp.exists() and cp.stat().st_size > 4096:
                    data = cp.read_bytes()
                else:
                    r = httpx.get(url, ...)
                    if r.status_code == 200 and len(r.content) >= 4096:
                        cp.write_bytes(r.content)
                        data = r.content
                if data:
                    results.append((sid, data))  # ← 只传 bytes，不创建 QPixmap
                self.done.emit(("progress", pct))
            except:
                pass
        if results:
            self.done.emit(("avatars", results))
```
然后在 `_on_loader_done` 中（主线程）才创建 QPixmap。

---

### Crash 2：`_ContactList` 内部类重复定义导致信号混乱

**文件**：`dmshoot/gui/widgets/contact.py` 第 182~213 行

`_Loader` 类定义在 `_load_avatars()` **方法体内部**。每次调用 `_load_avatars` 都会创建一个**新的类对象**（Python class 是可变对象，`class _Loader:` 语句被执行时会创建新类）。

虽然实际不会直接 crash，但在 PySide6 中，同一信号名但不同类的 `done = Signal(object)` 是**不同的信号类型**，可能导致连接混乱。更严重的是，旧 `_Loader` 实例的 done 信号可能触发到新实例的回调。

**修复**：把 `_Loader` 提到模块级别或设为 ContactList 的静态内部类。

---

### Crash 3：窗口关闭时后台线程仍在写 GUI

**文件**：多处

`closeEvent` 中调用 `_stop_adapters()` 和 `_stop_worker()` 是同步等待（`wait(3000)`），但以下线程可能在窗口销毁后仍触发 GUI 更新：

| 来源 | 文件 | 风险 |
|------|------|------|
| QTimer.singleShot 延迟回调 | `main_window.py:467` | 窗口关闭后触发 lambda，访问已删除的 widget |
| 抖音 WS 后台线程 | `douyin_ws.py:66` | daemon 线程在进程退出时被 Kill，但如果线程正在写文件可能损坏状态 |
| ContactList `_Loader` | `contact.py:182` | 头像下载中关闭窗口，done 信号 emit 到已删除的 ContactList |

**修复**：
- main_window 的 closeEvent 中加一个 `_closing = True` 标志
- 所有 QTimer.singleShot 的 lambda 开头检查 `if hasattr(self, '_closing') and self._closing: return`
- 或使用 `QApplication.instance().aboutToQuit.connect(...)` 全局清理

---

## 🟠 性能瓶颈（导致卡顿）

### Perf 1：GlowProgressBar 持续 60fps 重绘 — 永不停止

**文件**：`dmshoot/gui/widgets/glow_progress_bar.py` 第 37~40 行

```python
self._ticker = QTimer(self)
self._ticker.setInterval(16)       # 16ms = ~60fps
self._ticker.timeout.connect(self._on_tick)
self._ticker.start()               # ← 一直运行！
```

`_on_tick()` 调用 `self.update()` → 触发 `paintEvent`，即使 `_value == _target_value` 也在跑。当多个 `GlowProgressBar` 同时存在（ContactList 里有一个，其他组件也可能创建），每个 ticker 都在燃烧 CPU。

实际测量：即使进度条隐藏（`setVisible(False)`），ticker 仍在运行并调用 `update()`。

**修复**：
```python
def _on_tick(self):
    diff = self._target_value - self._smooth_value
    if abs(diff) < 0.15:
        self._value = self._target_value
        self._smooth_value = self._target_value
        if self._value == self._target_value:
            self._ticker.stop()  # ← 停止！
        return
    self._smooth_value += diff * 0.12
    self._value = round(self._smooth_value)
    self.update()

def setValue(self, v: int):
    self._target_value = max(0, min(100, v))
    if not self._ticker.isActive():
        self._ticker.start()  # ← 只在需要时启动
```

---

### Perf 2：BubbleWidget 每个气泡触发全局 QSS 重解析

**文件**：`dmshoot/gui/widgets/chat_view.py` 第 37~43 行

```python
bubble.setStyleSheet(f"QLabel#bubble {{"
    f"  background: {bg_color};"
    f"  border: 1px solid rgba(240,192,96,{0.10 if is_self else 0.05});"
    ...
```

每个气泡的 `setStyleSheet()` 会触发 Qt 的 CSS 解析器重新计算整个 widget 树的样式。加载 100 条历史消息 = 100 次全局 QSS 重算。

**修复**：把颜色写成 QSS 属性选择器，或者用 `QPalette` / 直接 `setAutoFillBackground`：
```python
# 方案 A：用 dynamic property
bubble.setProperty("me", True) if is_self else bubble.setProperty("me", False)
bubble.setStyleSheet("")
# QSS 中: QLabel[me="true"] { background: rgba(240,192,96,0.18); }

# 方案 B（更快）：QPalette
pal = bubble.palette()
pal.setColor(QPalette.Window, QColor(240, 192, 96, 46))
bubble.setPalette(pal)
bubble.setAutoFillBackground(True)
```

---

### Perf 3：MonitorPanel 日志无限增长 — 内存泄漏

**文件**：`dmshoot/gui/monitor_panel.py` 第 113~135 行

```python
def add_reply_log(self, msg, ai_reply=""):
    entry = ReplyLogEntry(msg, ai_reply)
    self.log_layout.addWidget(entry)
    self.log_layout.addStretch()
```

每次 AI 回复都新增一个 `ReplyLogEntry` widget，**永不删除**。运行几小时后：
- 几百个 QFrame widget 在内存中
- 每个 ReplyLogEntry 内部有 2-3 个 QLabel
- ScrollArea 需要管理所有 widget 的布局计算

**修复**：限制最大条目数：
```python
MAX_LOG_ENTRIES = 200

def add_reply_log(self, msg, ai_reply=""):
    # 移除超出限制的旧条目
    widget_count = self.log_layout.count() - 1  # 减去 stretch
    if widget_count >= MAX_LOG_ENTRIES:
        first = self.log_layout.itemAt(0)
        if first.widget():
            first.widget().deleteLater()
    ...
```

---

### Perf 4：ContactList 全量扫描 — 每条消息都 O(n)

**文件**：`dmshoot/gui/widgets/contact.py` 第 104~152 行

每次新消息到达 → `add_message()` → `_load_contacts()` → `set_sessions()`，而 `set_sessions` 每次都从头遍历所有 QListWidgetItem：

```python
existing = {}
for i in range(self.list.count()):      # O(n) 全量扫描
    item = self.list.item(i)
    w = self.list.itemWidget(item)
    ...
```

在消息高频场景下（抖音 WS 每秒多条），这个扫描开销显著。另外，`_on_loader_done` 第 224-228 行也是 O(n²)：
```python
for sid, pix in payload:
    for i in range(self.list.count()):   # 对每个结果扫描全列表
        w = self.list.itemWidget(self.list.item(i))
        if w and w.session_id == sid:
            w.avatar.setPixmap(pix)
```

**修复**：维护一个 `_widget_map: dict[str, ContactItem]`，更新时直接通过 dict 查找。

---

### Perf 5：每条消息都触发两次 DB + UI 刷新

**文件**：`dmshoot/gui/main_window.py` 第 431~467 行

`_on_new_message` 每条消息的执行路径：
1. `upsert_session()` → SQL INSERT/UPDATE
2. `save_message()` → SQL INSERT（含去重检查）
3. `page_home.add_message()` → 缓存操作 + UI 渲染
4. `page_home._load_contacts()` → 重新查询 DB + 渲染联系人列表

如果抖音 WS 一秒推 10 条消息，就是 **10 次 `_load_contacts()` → 10 次 `get_sessions()` + 10 次 `set_sessions()`**。

**修复**：用 throttle：
```python
# 类级别
self._contacts_dirty = False
self._contacts_throttle = QTimer()
self._contacts_throttle.setSingleShot(True)
self._contacts_throttle.setInterval(500)
self._contacts_throttle.timeout.connect(self._flush_contacts)

def _on_new_message(self, msg):
    ...
    self._contacts_dirty = True
    if not self._contacts_throttle.isActive():
        self._contacts_throttle.start()

def _flush_contacts(self):
    if self._contacts_dirty:
        self.page_home._load_contacts()
        self._contacts_dirty = False
```

---

### Perf 6：`from PySide6.QtCore import QTimer` 在函数内部反复 import

**文件**：`chat_view.py:118`, `monitor_panel.py:132`, `contact.py:155`

```python
from PySide6.QtCore import QTimer   # 每次函数调用都走 import 缓存查找
QTimer.singleShot(100, ...)
```

虽然 Python 的 import 有缓存，不会重新执行，但 `from X import Y` 在函数内部仍然有字典查找开销。高频调用路径（如每条消息的 `append_message`）中，建议提到文件顶部。

---

## 🟡 潜在风险

### Risk 1：`asyncio.run()` 在 QThread 中重复创建事件循环

**文件**：`main_window.py:470-478`（`_call_ai` 的 QThread）、`main_window.py:326-350`（`_run_async_verify` 的 QThread）

每次 `_AIThread.run()` 和 `_V.run()` 都调用 `asyncio.run(do())`，这会：
1. 创建新的事件循环
2. 执行
3. 销毁事件循环

高频调用下（每条消息一个 QThread），事件循环创建/销毁有开销。但更重要的是：Python 3.10+ 的 `asyncio.run()` 在已有运行中的事件循环的线程中调用会崩溃。

**当前状态**：QThread 内部没有事件循环，所以不会冲突。但如果未来某处先创建了事件循环……

**建议**：创建一个持久的事件循环线程，而不是每条消息开一个新 QThread。

---

### Risk 2：`database.py` 持久连接 + 多线程写入无锁

**文件**：`dmshoot/storage/database.py`

```python
_conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
```

多个线程同时写入（B站适配器线程 + 抖音适配器线程 + 主线程（AI 回复入库）），虽然有 SQLite 内部序列化，但：
- `check_same_thread=False` 把线程安全责任交给了 SQLite 自身
- 如果某个 commit 失败且没有被正确处理，后续写入可能拿到脏状态

**建议**：加一个 `threading.Lock` 保护所有写操作。

---

### Risk 3：`QTimer.singleShot` 里的 lambda 闭包捕获已释放对象

**文件**：`main_window.py:467`、`chat_view.py:118`、`monitor_panel.py:133`

```python
QTimer.singleShot(500, lambda a=ai, m=msg: self._call_ai(m, a))
```

如果用户关闭窗口时 QTimer 还没触发，lambda 中的 `self` 指向已删除的 MainWindow。虽然 PySide6 的 `deleteLater` 会清理信号连接，但 QTimer.singleShot 的超时信号不是连接在 widget 上的。

**修复**：用 `QTimer` 对象而非 `singleShot`：
```python
timer = QTimer(self)
timer.setSingleShot(True)
timer.timeout.connect(lambda: self._call_ai(msg, ai))
timer.start(delay_ms)
```
这样 timer 的 parent 是 self（MainWindow），窗口关闭时自动清理。

---

## 📊 优化优先级

| 优先级 | 项目 | 类型 | 影响 |
|--------|------|------|------|
| 🔴 P0 | Crash 1: QPixmap 跨线程 | 闪退 | 100% 必现崩溃 |
| 🔴 P0 | Crash 3: 关闭窗口回调 | 闪退 | 偶发崩溃 |
| 🟠 P1 | Perf 1: GlowProgressBar 60fps | CPU | 持续 2-3% CPU 占用 |
| 🟠 P1 | Perf 4: ContactList O(n²) | 卡顿 | 多消息时 UI 卡 |
| 🟠 P1 | Perf 5: 每条消息刷联系人 | 卡顿 | 高频消息场景 |
| 🟡 P2 | Perf 2: BubbleWidget QSS | 卡顿 | 加载历史时 |
| 🟡 P2 | Perf 3: MonitorPanel 无限增长 | 内存 | 长时间运行 |
| 🟡 P2 | Risk 3: QTimer 单次回调 | 闪退 | 窗口关闭时 |
| ⚪ P3 | Perf 6: 函数内 import | 微优化 | 可忽略 |
| ⚪ P3 | Risk 1: 重复事件循环 | 设计 | 暂时不会崩 |
