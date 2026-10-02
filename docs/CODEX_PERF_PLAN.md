# DMShoot 聊天性能优化计划（基于 2026-09-03 代码现状）

> **本文基于 2026-09-03 最新代码重新评估。** 此前 8/31 的「虚拟化 + GPU 后端」路线
> **已过时**——`chat_view.py` 已被重构，原分析中的瓶颈（几千 widget 全常驻、无分组、
> 无字体管理）均已解决。本计划只针对当前代码剩的真实瓶颈。
> AI 未改动任何源码，文档供 codex 实现。

---

## 〇、现状确认（已读 `dmshoot/gui/widgets/chat_view.py`，1281 行）

### ✅ 已实现（说明"虚拟化"不再是重点）
| 能力 | 位置 |
|---|---|
| 消息分组 `MessageGroupWidget` | 577 |
| 气泡圆角状态机 `BubbleWidget.set_position()` | 346 |
| 头像粘底吸附 `update_avatar_position` | 771 |
| `FontManager` 集成 `set_font_mode` / `chat_families` | 894 |
| 窗口裁剪 `MAX_VISIBLE=50`，超量 `pop(0)` | 1142 |
| 批量加载时 `setUpdatesEnabled(False)` 防中间态 | 1036 |

**关键常量**（ChatView 类变量）：
```python
MAX_VISIBLE = 50          # 同时保留的最近消息数
MAX_READING_BUFFER = 20   # 用户向上翻看历史时额外的缓冲条数
HISTORY_CHUNK = 4         # 已废弃：注释写明"打开会话已不再启动历史分批加载"
```

### 🔴 真实剩余瓶颈
1. **`_render_message_items`（1045）每次全量重排**
   ```python
   while self.bubble_layout.count():
       item = self.bubble_layout.takeAt(0)      # ← 清空整个布局
       ...
   for widget in target_items:
       self.bubble_layout.addWidget(widget)      # ← 重新加回所有
   ```
   O(n) 拆装布局 + 一次完整 relayout + 全量重绘。
2. **`append_message`（1138）稳态下每条新消息全量重排**
   ```python
   elif (was_at_bottom and len >= MAX_VISIBLE) or len >= MAX_VISIBLE + MAX_READING_BUFFER:
       self._display_messages.pop(0)
       self._render_message_items(...)          # ← 触发上面的全量重排
   ```
   连续收消息时，每来一条都 pop+重排一次 → **O(n) 每次**。这是当前最大的卡顿源。
3. **无法向上加载历史**：`_load_history_chunk`（1111）机制完整但**未被启动**（注释确认）。
   用户只能看到最近 50 条，无法回看更早消息——这是**功能缺失**，不只是性能问题。
4. **气泡绘制无缓存**：`BubbleWidget.paintEvent`（530）每帧重算 `_bubble_path()`
   （贝塞尔尾巴曲线），未缓存路径对象。

---

## 一、优化项（按优先级）

### P0-1：增量移除，替代全量重排  ★★★★★
**目标**：稳态收消息时，只移除最老的 1 个（或几个）widget，不动其余。

**改法（`append_message` 的"需丢弃"分支）**：
```python
# 现在：
self._display_messages.pop(0)
self._render_message_items(self._display_messages, preserve_scroll=not was_at_bottom)

# 改为：只摘掉最老的 widget，不重排
self.setUpdatesEnabled(False)
try:
    # 找到最老的内容项并移除；注意可能以 DateSeparatorWidget 开头
    while self._content_items and isinstance(self._content_items[0], DateSeparatorWidget) \
            and len(self._content_items) > 1 and self._content_items[1] is to_remove:
        sep = self._content_items.pop(0)
        idx = self.bubble_layout.indexOf(sep)
        if idx >= 0: self.bubble_layout.takeAt(idx)
        sep.deleteLater()
    old = self._content_items.pop(0)
    idx = self.bubble_layout.indexOf(old)
    if idx >= 0: self.bubble_layout.takeAt(idx)
    old.deleteLater()
    self._display_messages.pop(0)
finally:
    self.setUpdatesEnabled(True)
```

⚠️ **日期分隔符边界**：若最老组上方有 `DateSeparatorWidget`，且移除该组后其上方相邻组不同天，
分隔符需一并移除；若仍同天则保留。建议封装一个 `_remove_oldest_group()` 方法集中处理这层逻辑。

**验证点**：连续收 100 条消息，观察 CPU 占用与滚动跟随是否平滑（对比改前）。

---

### P0-2：恢复向上滚动加载历史  ★★★★（兼功能修复）
**目标**：滚到顶部时，从 DB 分批拉取更早消息并**保持滚动锚点**。机制 `_load_history_chunk` 已现成，只需接通触发。

**改法**：
1. 在 `_on_scroll_value_changed`（1214）中检测：
   ```python
   if value <= 40 and self._history_pending:
       self._history_timer.start()
   ```
2. **需要一个历史数据源接口**：按 `(conversation_id, before_timestamp)` 分页拉取更早消息。
   - 确认 adapter / DB 层是否已有该方法（参考 `dmshoot-go` 的 `/api/db/sessions` 或现有
     `load_messages` 的调用方）；若没有，需先补一个 `fetch_older_messages(conv_id, before, limit)`。
3. 加载时复用已有 `keep_position()`（1124）保持锚点：`preserve_scroll=not was_at_bottom`。
4. **总量封顶**：加载到 500 条后停止（二次裁剪，防止无限增长把内存吃回来）。

⚠️ 此功能依赖历史接口，是 P0-2 的唯一外部前置依赖。若接口缺失，P0-2 应拆分为
「补历史接口」+「接通加载」两步。

---

### P0-3：气泡绘制路径缓存  ★★★
**目标**：`_bubble_path()` 只在尺寸/位置/色彩变化时重算，paintEvent 直接复用缓存对象。

**改法（`BubbleWidget`）**：
```python
def __init__(self, ...):
    self._cached_path: QPainterPath | None = None

def _invalidate_path(self):
    self._cached_path = None

def _bubble_path(self):
    if self._cached_path is not None:
        return self._cached_path
    path = self._compute_path()          # 现有绘制逻辑搬进来
    self._cached_path = path
    return path

# 在以下位置调用 self._invalidate_path()：resizeEvent、set_position、set_max_width、颜色变更
```
收益主要在窗口 resize 抖动和首次布局时；稳态滚动绘制成本本就低（纯色填充），此项是锦上添花。

---

### P3：滚动条美化（参照 `docs/UI_INTERACTION_SPEC.md` 第三节）
- cc-switch 是 `display:none`（完全隐藏），但 Qt 完全隐藏滚动条会让用户失去位置感。
- **建议自绘细条**而非完全隐藏：
  ```css
  QScrollArea#chatScroll QScrollBar:vertical {
      width: 7px; background: transparent; margin: 2px 0;
  }
  QScrollArea#chatScroll QScrollBar::handle:vertical {
      background: rgba(255,255,255,0.18); border-radius: 3px; min-height: 36px;
  }
  QScrollArea#chatScroll QScrollBar::handle:vertical:hover {
      background: rgba(255,255,255,0.32);
  }
  ```
- 此项纯视觉，可独立实施，不阻塞 P0。

---

## 二、实施红线（给 codex）

1. **`_content_items` 与 `_display_messages` 必须保持同步**：任何增删都两处一起动，
   否则 `set_font_mode`/`_update_avatar_positions` 遍历时会错位或崩溃。
2. **绝对不要在 `paintEvent` / 高频回调里 `new` 对象**（QPainterPath、QTimer、QPen 等）。
   路径缓存、定时器复用，避免 GC 抖动。
3. **批量 widget 增删必须用 `setUpdatesEnabled(False)` 包裹**，结束恢复 `True`，
   否则会出现半成品闪烁。
4. **保留并测试「底部自动跟随」**：`was_at_bottom` / `_is_near_bottom` / `_schedule_scroll`
   是现有正确行为——批量改动后务必回归测试"新消息自动滚到底"。
5. **历史锚点不漂移**：P0-2 加载后，滚回底部再向上，不能重复加载、不能顺序错乱、
   滚动位置不能跳变。用 `keep_position` 的 `preserve_scroll` 分支，且窗口裁剪与历史加载
   不能用同一份 `_display_messages` 互相覆盖——建议历史加载用独立缓冲，合并后再裁窗口。
6. **真实帧率验证**：`tools/fps_probe.py` 是独立 app，测不了现网；可在 `ChatView` 里临时加
   `QElapsedTimer` 统计 `paintEvent` 调用频率与 `_render_message_items` 耗时，定位回归。

---

## 三、验证清单
- [ ] 稳态连续收 100 条新消息：无卡顿、自动跟随底部、CPU 不飙
- [ ] 滚动到顶部：触发历史加载，无重复 / 错乱 / 锚点漂移
- [ ] 切换会话：正确清空并加载新会话，无残留 widget、无错位
- [ ] 向上累计加载到 500 条后封顶，不再增长
- [ ] 上滑时头像吸附正常（`update_avatar_position` 未受重排影响）
- [ ] `set_font_mode` 切换后布局正确（`_content_items` 索引一致）
- [ ] resize 窗口时气泡不闪烁（P0-3 命中）
- [ ] 回归：空闲态（不收发消息）CPU 接近 0

---

## 四、参考文件
| 文件 | 用途 |
|---|---|
| `dmshoot/gui/widgets/chat_view.py` | 本次优化唯一目标文件（ChatView / MessageGroupWidget / BubbleWidget） |
| `docs/UI_INTERACTION_SPEC.md` | 交互质感规格（含滚动条美化参数） |
| `docs/TG_BUBBLE_SPEC.md` | 气泡视觉规格（**已实现**，勿重复造） |
| `docs/FONT_STRATEGY.md` | 字体管理规格（**已实现**，勿重复造） |
