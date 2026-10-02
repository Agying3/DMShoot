# DMShoot 交互质感规格（参照 cc-switch 提取）

> **来源**：`H:\toos\cc-switch`（用户提供的参考项目，只读分析，未改动）
> **技术栈**：Tauri 2.8 + React 18 + TypeScript + TailwindCSS 3.4 + Radix UI + shadcn/ui
> + framer-motion 12 + @tanstack/react-virtual 3 + dnd-kit + TanStack Query 5
> **目标**：把其中 **Qt Widgets 能实现** 的交互细节提取出来，迁移到 DMShoot。
> 本文件是**规格文档**，供 codex 实现，AI 未改动任何 DMShoot 源码。

---

## 〇、三个反直觉的关键结论

1. **它没有用任何 spring（弹簧物理）动画。**
   全项目 `framer-motion` 用法里搜不到 `type: "spring"` / `stiffness` / `damping`。
   全部是 **固定时长 + 缓动曲线**。→ `QPropertyAnimation` 天然匹配，不需要物理模拟。

2. **它真的做了列表虚拟化**（推翻我此前的猜测）。
   `@tanstack/react-virtual` 用在会话消息页，参数完整可抄（见第四节）。

3. **按钮 hover 只是"换颜色"，没有缩放、没有位移。**
   `transition-colors` 而不是 `transition-all`，这是有意的**性能决策**——
   只动颜色不触发重排。→ Qt 里成本极低，最该先抄的一条。

---

## 一、动效数值总表（直接抄）

### 1.1 缓动曲线

| 用途 | 曲线 | Qt 对应 |
|---|---|---|
| **面板/页面级**（主力） | `cubic-bezier(0.22, 1, 0.36, 1)` | `QEasingCurve.OutQuint`（近似）或自定义 BezierSpline（精确，见下） |
| 微交互过渡 | `cubic-bezier(0.4, 0, 0.2, 1)`（Tailwind 默认） | `QEasingCurve.InOutQuad` |
| Popover 进入 | `cubic-bezier(0.16, 1, 0.3, 1)` | `QEasingCurve.OutExpo` |
| Popover 退出 | `cubic-bezier(0.4, 0, 1, 1)` | `QEasingCurve.InQuad` |

**精确复现 cubic-bezier 的 Qt 写法**（推荐，比内置曲线更还原）：

```python
from PySide6.QtCore import QEasingCurve, QPointF

def cubic_bezier(x1, y1, x2, y2):
    """CSS cubic-bezier(x1,y1,x2,y2) → QEasingCurve"""
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(
        QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0)
    )
    return curve

EASE_PANEL   = cubic_bezier(0.22, 1.0, 0.36, 1.0)   # 面板主力曲线
EASE_MICRO   = cubic_bezier(0.4,  0.0, 0.2,  1.0)   # 微交互
EASE_ENTER   = cubic_bezier(0.16, 1.0, 0.3,  1.0)   # 进入（带轻微过冲感）
EASE_EXIT    = cubic_bezier(0.4,  0.0, 1.0,  1.0)   # 退出（快速收走）
```

### 1.2 时长谱系

| 场景 | 时长 | 曲线 | 位移/缩放 |
|---|---|---|---|
| 微反馈（显示/隐藏、小切换） | **150 ms** | EASE_MICRO | 无 |
| 小浮层入场（搜索框等） | **180 ms** | easeOut | `y: -8px → 0`，`scale: .98 → 1` |
| 淡入淡出（Dialog 无位移时） | **200 ms** | 线性 | opacity 0→1 |
| 操作按钮 hover 浮现 | **200 ms** | — | opacity 0→1 |
| 面板/页面切换（**从右滑入**） | **260 ms** | EASE_PANEL | `x: 100% → 0` |
| 品牌/状态条展开 | **280 ms** | EASE_PANEL | — |
| 卡片 hover 全属性过渡 | **300 ms** | — | border + shadow |
| 卡片内图标 hover 放大 | **300 ms** | — | `scale: 1 → 1.05` |
| Popover 进入 | **260 ms** | EASE_ENTER | `x: 22px→0`，`scale: .94→1`（68% 处过冲 -2px / 1.008） |
| Popover 退出 | **150 ms** | EASE_EXIT | `x: 0→12px`，`scale: 1→.97` |
| 数据图表演示 | **400 / 800 ms** | easeOut | — |
| Toast 停留 | 2000 ms（错误 3000–5000） | — | — |

**规律：进入慢（260ms）、退出快（150ms）**。这是现代 UI 的标准手感，务必照做。

### 1.3 尺寸与视觉常量

| 项 | 值 |
|---|---|
| 圆角 | `sm` 6px / `md` 8px / `lg` 12px / `xl` 14px（卡片用 `rounded-xl` = 14px） |
| 按钮高度 | 默认 36px / sm 32px / lg 40px；图标按钮 36×36 |
| Switch | 轨道 44×24px，thumb 20px 圆，**位移 20px** |
| 阴影 sm | `0 1px 2px rgba(0,0,0,.05)` |
| 阴影 lg | `0 10px 15px -3px rgba(0,0,0,.1), 0 4px 6px -4px rgba(0,0,0,.1)` |
| 卡片暗色阴影 | `0 8px 32px rgba(0,0,0,.37)` |
| 焦点环 | `outline: 2px solid #0A84FF; outline-offset: 2px` |
| 列表项间距 | `space-y-3` = 12px |
| 暗色主题 | 背景 `240 5% 12%`、卡片 `240 5% 16%`、主色 `210 100% 54%`、边框 `240 5% 24%` |

---

## 二、交互模式清单（每条给 Web 原文 + Qt 实现）

### 模式 1：按钮只过渡颜色（**最该先抄**）

```tsx
// button.tsx
"inline-flex items-center ... rounded-lg transition-colors
 focus-visible:ring-1 disabled:opacity-50"
// hover 仅换色：bg-blue-500 → hover:bg-blue-600
```

**Qt 实现**：
```python
# ⚠️ Qt 的 QSS 没有 transition！:hover 是瞬间切换，不会渐变。
# 要渐变必须自己在 enterEvent/leaveEvent 里驱动动画：
class HoverButton(QPushButton):
    def __init__(self, base, hover, ...):
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(EASE_MICRO)
        self._anim.valueChanged.connect(self._apply_color)

    def enterEvent(self, e):
        self._run(self._base, self._hover); super().enterEvent(e)

    def leaveEvent(self, e):
        self._run(self._hover, self._base); super().leaveEvent(e)
```
> 若嫌逐个控件改造成本高，**退而求其次**：QSS `:hover` 瞬间换色（无动画）。
> 视觉损失小（150ms 的差异），但能立刻获得"有反馈"的观感。

### 模式 2：卡片 hover —— 边框变色 + 阴影浮现 + 图标微放大

```tsx
// ProviderCard.tsx
"rounded-xl border border-border p-4 transition-all duration-300 group
  hover:border-border-active hover:shadow-sm"
// 子元素（图标）：
"group-hover:scale-105 transition-transform duration-300"
```

**Qt 实现要点**：
- 边框 + 阴影：hover 时改 QSS（可接受瞬间切换，或配 300ms 动画）
- `group-hover` = **父控件 hover 触发子控件动画** → 父控件 `enterEvent/leaveEvent` 里
  向子控件发信号（Qt 无 `:hover` 影响子选择器的能力）
- `scale-105` → Qt Widgets 无 transform。替代方案：动画改图标 `fixedSize`
  （36→38px，300ms，EASE_MICRO）。**不建议**用 `QPainter.scale`，因为命中区域不跟着变。

### 模式 3：操作按钮默认隐藏，hover 才浮现

```tsx
// ProviderCard.tsx:683
"opacity-0 pointer-events-none
 group-hover:opacity-100 group-focus-within:opacity-100
 group-hover:pointer-events-auto
 transition-opacity duration-200"
```

这是减少视觉噪音的关键手法（TG、Notion 都这么干）。

**Qt 实现**：
```python
self._eff = QGraphicsOpacityEffect(self._actions_row)
self._actions_row.setGraphicsEffect(self._eff)
self._anim = QPropertyAnimation(self._eff, b"opacity")
self._anim.setDuration(200)
# hover 时: 0.0 → 1.0；离开时: 1.0 → 0.0
# 注意：opacity=0 时控件仍能接收事件 → 需手动 setEnabled(False) 配合
```

### 模式 4：焦点可见性

```css
*:focus-visible { @apply outline-2 outline-blue-500 outline-offset-2; }
```

**Qt**：`QSS` 写 `*:focus { border: 2px solid #0A84FF; }`。
Qt 默认有焦点框（虚线），**建议统一覆盖成实线蓝框**，比原生虚线好看得多，成本极低。

### 模式 5：面板/页面切换（从右滑入）

```tsx
// FullScreenPanel.tsx
initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
```

**Qt 实现**：`QPropertyAnimation(widget, b"pos")`，260ms + EASE_PANEL。
适用于：设置对话框、会话详情、全屏子页面。这是**提升"高级感"性价比最高的一条**。

### 模式 6：Popover 过冲回弹

```css
@keyframes pi-thinking-popover-in {
  0%   { opacity:0; transform: translate3d(22px,0,0) scale(.94); }
  68%  { opacity:1; transform: translate3d(-2px,0,0) scale(1.008); }  /* 过冲 */
  100% { opacity:1; transform: translate3d(0,0,0) scale(1); }
}
/* 260ms cubic-bezier(0.16,1,0.3,1) 进 / 150ms cubic-bezier(0.4,0,1,1) 出 */
```

**Qt 实现**：单条 `QPropertyAnimation` 做不出"先过冲再回弹"，
用 `QSequentialAnimationGroup` 两段（0→68%→100%），或直接用 `QEasingCurve.OutBack`
（自带过冲，参数 `setOvershoot(1.2)` 左右调到接近 1.008 的观感）。

### 模式 7：开关（Switch）

```tsx
// switch.tsx
轨道：h-6 w-11 rounded-full transition-colors
     checked → emerald-500 / unchecked → gray-200（暗色 gray-900）
拇指：h-5 w-5 rounded-full bg-white transition-transform
     translate-x-0  ⇄  translate-x-5（20px）
```

**Qt**：`QPropertyAnimation(thumb, b"pos")`，**150ms + EASE_MICRO**，位移 20px。
轨道色也可用 `QVariantAnimation` 插值（150ms）。

### 模式 8：骨架屏（加载态）

```tsx
// ProviderList.tsx:404 —— 3 个虚线占位块
"w-full border border-dashed rounded-lg h-28
 border-muted-foreground/40 bg-muted/40"
```

**Qt**：加载时先插 3 个固定高度的 `QFrame`（虚线边框 + 半透明底色），
数据到位后替换为真实控件。**比转圈 spinner 高级得多，且实现极简单。**

### 模式 9：Toast 时长

默认 **2000ms**，错误类 3000–5000ms，需用户操作的（带关闭按钮）10000ms。
→ DMShoot 的通知/提示统一按这个梯度。

---

## 三、滚动条：完全隐藏

```css
/* index.css */
::-webkit-scrollbar { display: none; }
* { scrollbar-width: none; -ms-overflow-style: none; }
html { overscroll-behavior: none; }   /* 禁橡皮筋 */
```

它同时装了 Radix `ScrollArea`（自绘 10px 宽圆角 thumb），但实际主滚动条是隐藏的。

**Qt 建议**：
- **激进**：`QScrollBar { width: 0px; height: 0px; }` 彻底隐藏（与 cc-switch 一致）
- **稳妥**：自绘细条 —— `QScrollBar::handle { background: rgba(255,255,255,.15);
  border-radius: 3px; min-height: 40px; }` + `QScrollBar { width: 8px; background: transparent; }`
- `overscroll-behavior: none` → Qt 对应 `QAbstractScrollArea` 关闭 overscroll
  （或用 `QScroller` 时设 `QScrollerProperties.OvershootScrollRate = 0`）

---

## 四、虚拟列表规格（**可直接抄，本节最有价值**）

它**确实做了虚拟化**，在会话消息页（`SessionManagerPage.tsx`）：

```tsx
const virtualizer = useVirtualizer({
  count: messages.length,
  getScrollElement: () => scrollContainerRef.current,
  estimateSize: () => 120,   // 预估行高
  overscan: 5,               // 视口上下各多渲染 5 项作缓冲
  gap: 12,                   // 项间距
});

// 容器：撑出总高度，产生真实滚动条
<div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
  {virtualizer.getVirtualItems().map((virtualRow) => (
    <div
      key={virtualRow.key}
      data-index={virtualRow.index}
      ref={virtualizer.measureElement}          // ← 动态测量真实高度
      style={{
        position: "absolute", top: 0, left: 0, width: "100%",
        transform: `translateY(${virtualRow.start}px)`,
      }}
    >
      <SessionMessageItem message={messages[virtualRow.index]} ... />
    </div>
  ))}
</div>
```

### 4.1 关键参数（照抄）

| 参数 | 值 | 说明 |
|---|---|---|
| `estimateSize` | **120 px** | 首屏未测量前的估算行高 |
| `overscan` | **5** | 上下各缓冲 5 项 —— 太少会闪白，太多浪费 |
| `gap` | **12 px** | 项间距 |
| `measureElement` | 有 | **真实高度渲染后回填**，修正估算误差（聊天消息高度不定，这一步必须有） |
| 切换会话 | `scrollTop = 0` | 且 `scrollToIndex(i, {align:"center", behavior:"smooth"})` 平滑定位 |

### 4.2 Qt 映射方案

| Web 概念 | Qt Widgets 实现 |
|---|---|
| `getTotalSize()` 撑高容器 | 容器内 widget `setFixedHeight(total)`，让 QScrollArea 产生真实滚动范围 |
| `position:absolute` + `translateY(start)` | item widget `setParent(container)` 后 `move(0, start)`，**不用 QVBoxLayout** |
| 只渲染 `getVirtualItems()` | 维护一个 widget 池，滚动时回收 + 重绑数据（**不要 delete/new**） |
| `measureElement` 回填真实高度 | item 布局完成后取 `sizeHint().height()` 写回 heights 数组，**并修正后续所有 start** |
| `overscan: 5` | 可见区间 `[first-5, last+5]` |
| 平滑滚动到索引 | `QPropertyAnimation(scrollBar, b"value")`，时长 260ms + EASE_PANEL |

> ⚠️ **高度回填是难点**：聊天消息高度不定，测量后要重排后续项。
> 建议用"前缀和数组 + 二分查找"定位，避免 O(n) 重算。
> 或者退一步：**固定行高估算 + 懒修正**（滚动停止时才批量修正），优先保证滚动中不卡。

---

## 五、Qt Widgets 做不到 / 代价高的部分（**不要硬抄**）

| Web 特性 | 为什么 Qt Widgets 难 | 建议降级方案 |
|---|---|---|
| `backdrop-filter: blur()` 毛玻璃 | 无原生支持。硬做要"截背景 → `QGraphicsBlurEffect` → 贴回"，滚动时每帧重算 | **cc-switch 暗色主题自己就是降级方案**：用 `linear-gradient(145deg, rgba(255,255,255,.05), rgba(255,255,255,.01))` + `1px rgba(255,255,255,.05)` 边框 + `0 8px 32px rgba(0,0,0,.37)` 阴影。**零 blur 成本，视觉 8 成像** |
| GPU 图层化合成 / compositor 线程 | Widgets 全部主线程 CPU 绘制，无此概念 | 无解。这是 cc-switch 丝滑的**根因**，也是 DMShoot 60Hz 以上无望的根因 |
| `transform: scale()` | 无 widget 级 transform；改 geometry 触发 relayout，paintEvent 里 scale 又不改命中区 | 用"动画改尺寸"或"按下变暗"替代"按下缩小" |
| `will-change: transform` | 无对应 | 无 |
| CSS `transition`（QSS 无 transition） | QSS 状态切换是**瞬间**的，不会渐变 | 需要动画的地方必须手写 `QPropertyAnimation`（模式 1 已给写法） |

---

## 六、cc-switch 暗色"伪毛玻璃"配方（**建议直接采用**）

它在暗色模式下用渐变 + 微边框 + 大阴影替代纯 blur，这是**Qt 能 100% 复刻**的：

```css
/* .dark .glass-card */
background: linear-gradient(145deg,
            rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.01) 100%);
border: 1px solid rgba(255,255,255,0.05);
box-shadow: 0 8px 32px 0 rgba(0,0,0,0.37);
```

**Qt 实现**（`paintEvent` 画，比 QSS 更可控且更快）：
```python
grad = QLinearGradient(rect.topLeft(), rect.bottomRight())   # 145° 近似对角
grad.setColorAt(0.0, QColor(255, 255, 255, 13))    # 0.05 * 255
grad.setColorAt(1.0, QColor(255, 255, 255, 3))     # 0.01 * 255
p.setBrush(grad); p.setPen(QColor(255, 255, 255, 13))
p.drawRoundedRect(rect, 14, 14)
# 阴影：QGraphicsDropShadowEffect(blurRadius=32, offset=(0,8), color=rgba(0,0,0,.37))
```

卡片激活态另有规格：
```css
.dark .glass-card-active {
  background: rgba(59,130,246,0.12);
  border: 1px solid rgba(59,130,246,0.3);
}
```

---

## 七、建议实施顺序（按性价比）

| 优先级 | 项目 | 成本 | 收益 | 备注 |
|---|---|---|---|---|
| **P0** | 列表虚拟化（第四节） | 高 | ★★★★★ | 解决"卡"的根本，参数已给全 |
| **P0** | 隐藏/自绘滚动条（第三节） | 低 | ★★★★ | 几行 QSS，观感立刻变现代 |
| **P1** | 页面切换从右滑入 260ms（模式 5） | 中 | ★★★★★ | 高级感最强的一条 |
| **P1** | 卡片 hover 三件套（模式 2） | 中 | ★★★★ | 边框+阴影+图标放大 |
| **P1** | 焦点环统一（模式 4） | 低 | ★★★ | 几行 QSS |
| **P2** | 操作按钮 hover 浮现（模式 3） | 中 | ★★★★ | 需要 QGraphicsOpacityEffect |
| **P2** | 按钮 hover 颜色过渡 150ms（模式 1） | 中 | ★★★ | 需逐控件改造，或先用 QSS 瞬切 |
| **P2** | Switch 位移动画（模式 7） | 低 | ★★★ | 参数已给全 |
| **P3** | 骨架屏（模式 8） | 低 | ★★★ | 简单且高级 |
| **P3** | Toast 时长梯度（模式 9） | 低 | ★★ | 顺手 |
| **P3** | `prefers-reduced-motion` 对应开关 | 低 | ★★ | 无障碍，加个设置项即可 |

> **前置提醒**：先跑 `tools/fps_probe.py` 拿到基线帧率。
> 如果 500 条就掉到 30fps 以下，说明瓶颈在渲染而非交互——
> 此时加动画只会更卡，**必须先做完 P0 虚拟化再上 P1/P2 的动画**。

---

## 八、⚠️ 给 codex 的硬约束

1. **QSS 没有 transition**。所有"渐变"必须手写 `QPropertyAnimation` / `QVariantAnimation`，
   不要以为写了 `:hover` 就有过渡（不会有的）。
2. **`QPropertyAnimation` 不要 `new` 在 `paintEvent` / 高频回调里**，否则滚动时疯狂创建对象。
   控件持有一个实例，重复 `setStartValue/setEndValue/start()`。
3. **opacity 动画用 `QGraphicsOpacityEffect`**，但注意：
   - 它会强制控件走"离屏渲染"路径，对大控件有性能代价
   - opacity=0 时控件**仍能接收鼠标事件**，必须配合 `setEnabled(False)` 或 `hide()`
4. **毛玻璃不要用 `QGraphicsBlurEffect` 实时算**（见第五节），用渐变配方替代。
5. **虚拟化改造后**，DMShoot 现有的 `self._display_messages` 全量存储要保留（数据源），
   但**不再为每条消息常驻 widget**，改为 widget 池复用。
6. 动画总时长**不要超过 300ms**（面板级 260ms 已是上限）。超过会显得迟钝，
   反而失去"手机感"。
7. 所有动画**必须可关闭**：参考 cc-switch 的 `prefers-reduced-motion` 处理，
   在 DMShoot 设置里加一个「减少动画」开关，关闭时所有 duration 设 0。

---

## 附：本规格提取自以下文件（cc-switch）

| 文件 | 提取内容 |
|---|---|
| `tailwind.config.cjs` | 动画时长/曲线/keyframes、圆角、阴影、字体栈 |
| `src/index.css` | 主题变量、毛玻璃配方、滚动条隐藏、focus-visible、Popover 过冲 |
| `src/components/ui/button.tsx` | 按钮只过渡颜色、尺寸 |
| `src/components/ui/switch.tsx` | 开关 thumb 位移 20px |
| `src/components/ui/scroll-area.tsx` | 自绘滚动条规格 |
| `src/components/providers/ProviderCard.tsx` | 卡片 hover 三件套、操作按钮浮现 |
| `src/components/common/ListItemRow.tsx` | 列表行 hover（bg-muted/50） |
| `src/components/common/FullScreenPanel.tsx` | 面板滑入 260ms + EASE_PANEL |
| `src/components/sessions/SessionManagerPage.tsx` | **虚拟列表完整参数** |
| `package.json` | 技术栈版本（framer-motion 12、react-virtual 3 等） |
