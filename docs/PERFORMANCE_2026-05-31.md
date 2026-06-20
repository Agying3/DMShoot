# DMShoot 性能瓶颈分析与优化建议

**日期**：2026-05-31 00:02
**场景**：每平台 500+ 会话，消息高峰 10 条/秒

---

## 一、瓶颈总览

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| 1 | `home_page.py` | 每条消息都触发 DB 查询刷新通讯录 | 消息多时卡顿 |
| 2 | `chat_view.py` | 切会话全量重建气泡 | 切换卡 200ms+ |
| 3 | `MonitorPanel` | O(n²) 条目计数 + 逐条删除 | 日志区到 200 条后每次添加卡 |
| 4 | `_on_session_select` | 反复 `get_sessions()` 查会话名 | 点联系人时有延迟 |
| 5 | `_get_or_create_context` | 首条消息全量读 DB 重建上下文 | AI 首次响应慢 |
| 6 | `add_reply_log` | 每次创建 `QTimer.singleShot(50)` | 微小内存泄漏 |
| 7 | `douyin_msg_sync.py` | protobuf 正则扫描整块 raw 多次 | 历史同步慢 |
| 8 | `B站 _sync_history` | `self._get_user_name(tid)` 在 ThreadPool 内阻塞 HTTP | 启动慢 |

---

## 二、逐项分析与修复

### 瓶颈 1：每条消息都刷新通讯录 🔴

```
新消息 → _on_new_message() → add_message() → _load_contacts()
                                                    ↓ (500ms throttle)
                                             get_sessions(platform)  ← DB 查询
                                                    ↓
                                         set_sessions(sessions)     ← 重建 QListWidget
```

**当前**：即使有 500ms 节流，10 条消息/秒时仍然每 500ms 跑一次 DB + 重建。通讯录有 500 人时，`set_sessions()` 的增量对比逻辑（`contact.py` L103-155）遍历所有 item。

**优化**：

```python
# home_page.py — add_message() 末尾
# 不再每次都 _load_contacts()，改为仅更新有变化的 session
self._load_contacts()  # ← 删掉这行

# 在 _on_new_message() 里直接更新通讯录项
def _on_new_message(self, msg):
    # ... 现有逻辑 ...
    if not msg.is_self:
        # 直接通知通讯录更新这一项，不查全量 DB
        self.page_home.contacts.update_one_session(session_id)
```

`ContactList` 新增：

```python
def update_one_session(self, session_id: str):
    """只更新指定的一个联系人项"""
    for i in range(self.list.count()):
        w = self.list.itemWidget(self.list.item(i))
        if w and w.session_id == session_id:
            # 只更新文字，不重建 widget
            self._update_item_text(w, session_id)
            return
    # 不存在则查 DB 后追加
    self._load_contacts()
```

**收益**：消息洪水时通讯录刷新从 DB 查询降为 0。

---

### 瓶颈 2：切会话全量重建气泡 🔴

```python
# chat_view.py L92-116
def load_messages(self, title, messages):
    while self.bubble_layout.count() > 1:
        item = self.bubble_layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()      # ← 删除所有旧气泡
    for msg in messages:
        self.bubble_layout.insertWidget(...)  # ← 新建所有气泡
```

100 条消息 = 100 次 `deleteLater()` + 100 次 `BubbleWidget.__init__()` + 100 次 CSS 字符串拼接。切换会话时肉眼可见的白屏。

**优化**：增量加载，不复用就复用：

```python
def load_messages(self, title, messages):
    self.title_label.setText(title)
    needed = len(messages)
    existing_widgets = []
    # 收集现有气泡
    for i in range(self.bubble_layout.count() - 1):
        w = self.bubble_layout.itemAt(i).widget()
        if w:
            existing_widgets.append(w)
    
    # 复用前面的 widget，只改内容
    for i, msg in enumerate(messages):
        if i < len(existing_widgets):
            BubbleWidget.rebind(existing_widgets[i], msg)  # 原地更新
        else:
            self.bubble_layout.insertWidget(i, BubbleWidget(msg))
    
    # 删除多余的
    for w in existing_widgets[len(messages):]:
        w.deleteLater()
```

`BubbleWidget.rebind()` 只更新 name/bubble/time 三个 QLabel 的文字。

**收益**：切会话从 O(n) widget 创建降为 O(1) 属性更新。

---

### 瓶颈 3：MonitorPanel O(n²) 条目管理 🔴

```python
# monitor_panel.py L123-131
widget_count = sum(1 for i in range(self.log_layout.count())
                   if self.log_layout.itemAt(i).widget())  # O(n)
while widget_count >= self.MAX_LOG_ENTRIES:                 # O(n)
    for i in range(self.log_layout.count()):
        w = self.log_layout.itemAt(i).widget()
        if w and hasattr(w, 'deleteLater'):
            w.deleteLater()
            widget_count -= 1
            break                                            # 每次删 1 个
```

**优化**：

```python
MAX_LOG_ENTRIES = 200

def add_reply_log(self, msg, ai_reply=""):
    # 维护一个计数器，不要每次遍历
    if self._entry_count >= self.MAX_LOG_ENTRIES:
        # 直接删第一个（不是 stretch 的）
        for i in range(self.log_layout.count()):
            w = self.log_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
                self._entry_count -= 1
                break
    # ... 添加新条目 ...
    self._entry_count += 1
```

去掉 `QTimer.singleShot(50)`，改用 `QScrollBar.rangeChanged` 信号一次性滚动。

**收益**：O(n²) → O(1)。

---

### 瓶颈 4：_on_session_select 重复查 DB 🟡

```python
# home_page.py L79-91
def _on_session_select(self, session_id):
    msgs = database.get_messages(session_id, limit=100)       # DB 查询 1
    sessions = database.get_sessions(self._current_platform)   # DB 查询 2 ← 只为找名字
    title = "会话"
    for s in sessions:
        if s.session_id == session_id:
            title = s.peer_name
            break
```

每次点击联系人触发 2 次 DB 查询。通讯录 QListWidget 里已经有 `ContactItem.session_id` 和名字了。

**优化**：`contacts.session_selected` 信号改成带名字一起 emit：

```python
# ContactList
session_selected = Signal(str, str)  # session_id, peer_name

# home_page.py
def _on_session_select(self, session_id, peer_name="会话"):
    msgs = database.get_messages(session_id, limit=100)
    self.chat.load_messages(peer_name, msgs)
```

**收益**：切会话从 2 次 DB 查询降为 1 次。

---

### 瓶颈 5：AI 上下文首次加载全量读 DB 🟡

```python
# ai/backend.py L79-88
def _get_or_create_context(self, session_id):
    if session_id not in self._contexts:
        msgs = database.get_messages(session_id, limit=40)  # 最多 40 条
        ctx = []
        for m in msgs:
            role = "assistant" if m.is_auto else "user"
            ctx.append({"role": role, "content": m.content})
        self._contexts[session_id] = ctx
```

每次新会话首条消息都全量读 40 条历史消息。

**优化**：上下文窗口改成只取最近 10 条，40 条对 DeepSeek 来说是浪费 token：

```python
msgs = database.get_messages(session_id, limit=10)
```

或者在 adapter `_sync_history` 时顺便预热 AI 上下文（内存常驻）。

---

### 瓶颈 6：B站历史同步 HTTP 阻塞 🟡

```python
# bilibili/adapter.py L141-147
if not peer_name or peer_name.startswith("用户"):
    n, f = self._get_user_name(tid)  # ← 同步 HTTP 请求
```

`_get_user_name` 在 ThreadPool 线程里调 `httpx.get()`，本身不阻塞主线程，但 5 个线程都发 HTTP → 用户服务器可能限流，且等待最慢的完成才继续。

**优化**：`_get_user_name` 加 2 秒超时，或先全量写入后再异步补全：

```python
resp = httpx.get(url, timeout=2)  # 现在是 timeout=10
```

---

### 瓶颈 7：douyin_msg_sync.py 正则重复扫描 🟡

```python
# douyin_msg_sync.py L66-67（per peer, per position）
window = raw[max(0, pos - 200):min(len(raw), pos + 2000)]
cn = re.findall(rb'(?:[\xe4-\xe9][\x80-\xbf][\x80-\xbf]){2,}', window)
```

每个会话最多 30 个 position，每个 position 扫 2KB 窗口。500 个会话 × 30 = 15000 次正则扫描。

不过这个已经被降级了——adapter 不再调用 `sync_messages_to_db`（因为假时间戳），而是改用 Playwright 拉取真实时间戳+批量写入。如果 Playwright 缓存有问题才会回退到这里，所以优先级低。

---

## 三、卡顿点清单（按影响排序）

| 优先级 | 修改点 | 文件 | 行数 | 难度 |
|--------|--------|------|------|------|
| 🔴 P0 | 通讯录刷新降频 | `home_page.py` | L122 | 低 |
| 🔴 P0 | 切会话重建气泡 | `chat_view.py` | L105-112 | 中 |
| 🔴 P0 | MonitorPanel 条目计数 | `monitor_panel.py` | L123-131 | 低 |
| 🟡 P1 | 切会话双 DB 查询 | `home_page.py` | L85 | 低 |
| 🟡 P1 | AI 上下文减到 10 条 | `ai/backend.py` | L83 | 低 |
| 🟡 P1 | B站 HTTP 超时 2s | `bilibili/adapter.py` | L91 | 低 |
| 🟢 P2 | QTimer.singleShot 换 rangeChanged | `monitor_panel.py` | L143 | 低 |
| 🟢 P2 | douyin protobuf 扫描优化 | `douyin_msg_sync.py` | L66 | 中 |

---

## 四、一键优化检查清单

```bash
# 1. 通讯录不卡：确认 add_message 不再调 _load_contacts
grep "_load_contacts" dmshoot/gui/pages/home_page.py

# 2. 气泡不闪烁：确认 load_messages 复用了 widget
grep "deleteLater" dmshoot/gui/widgets/chat_view.py

# 3. 日志区不卡：确认没有 O(n) 遍历计数
grep "widget_count" dmshoot/gui/monitor_panel.py

# 4. 切会话不查DB：确认 session_selected 带名字
grep "session_selected" dmshoot/gui/widgets/contact.py
```

---

*文档随性能优化持续更新*
