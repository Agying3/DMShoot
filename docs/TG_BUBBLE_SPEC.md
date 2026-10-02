# TG 风格聊天气泡实现规格（v6 已确认）

> 依据用户提供的真实 Telegram 截图逐像素校正，经 6 轮预览迭代确认。
> 参考预览：`reports/tg_bubble_preview.html`（浏览器打开，可切 10 套配色 + 混搭、看头像吸附动画）
> 本文档交给 codex 实现时**不需要再看预览**，规格以本文为准。

---

## 一、核心结构改动（chat_view.py）

**现状**：一条消息 = 一个 `BubbleWidget`，时间戳在气泡外，头像不存在。

**目标**：一个人连续发的消息 = 一个 `MessageGroupWidget`：

```
MessageGroupWidget (QWidget)
├─ avatar_slot (QWidget, 宽 52px, 固定)
│    └─ avatar (QLabel 36×36 圆形)
└─ stack (QVBoxLayout)
     ├─ sender_name (QLabel, 仅对方且非 self 时显示)
     ├─ bubble 1  (BubbleWidget, pos="first")
     ├─ bubble 2  (BubbleWidget, pos="middle")
     └─ bubble N  (BubbleWidget, pos="last")
```

分组规则：**相邻两条消息满足「同一发送者 && 同一方向」即归入同一组**。
方向翻转、换人、或中间插入日期分隔线 → 断组。

## 二、圆角状态机（最关键，三轮迭代才定稿）

每条气泡根据组内位置设置四角圆角，顺序 **左上 右上 右下 左下**：

| 位置 | border-radius | 说明 |
|------|--------------|------|
| single（组只有一条） | `13 13 13 13` | 四角全圆，尾巴独立绘制 |
| first（自己/右侧） | `13 13 4 13` | 左侧（尾巴对侧）全圆；右下为 4px 接缝角 |
| middle（自己/右侧） | `13 4 4 13` | 左侧全圆；右侧上下均为 4px 接缝角 |
| last（自己/右侧） | `13 4 4 13` + 右下尾巴 | 右上保持接缝角，右下由尾巴替代 |
| first（对方/左侧） | `13 13 13 4` | 右侧（尾巴对侧）全圆；左下为 4px 接缝角 |
| middle（对方/左侧） | `4 13 13 4` | 右侧全圆；左侧上下均为 4px 接缝角 |
| last（对方/左侧） | `4 13 13 4` + 左下尾巴 | 左上保持接缝角，左下由尾巴替代 |

说明：尾巴在右侧消息中朝右，在左侧消息中朝左；尾巴对侧始终保留大圆角。三连消息的首条、中条、末条必须分别使用上表，不能把它们都画成完整胶囊。

⚠️ **实现约束**：尾巴不能占用正文主体的对齐宽度。首条/中条要预留尾巴宽度，使主体边缘和末条主体对齐，再让末条尾巴向头像侧外伸。

## 三、头像吸附（粘底上挤）

### 行为定义
- 平时：头像贴**组的最后一条**（最新那条旁边），组底部对齐
- 上滑时：视口底碰到头像 → 头像**钉在视口底**不动
- 组继续上移：头像相对组**从下往上**被挤
- 撞上组的第一条消息（组顶）→ 停住，之后跟着组滚出视口

### 公式（PySide6 直接照搬）

```python
AV = 36            # 头像尺寸
STICK_BOTTOM = 4   # 距视口底留白
R = 13             # 大圆角
RT = 4             # 接缝圆角

def update_avatars(scroll, groups):
    scroll_top = scroll.verticalScrollBar().value()
    vh = scroll.viewport().height()
    stick_vp = vh - AV - STICK_BOTTOM          # 头像被钉住的视口 y
    for g in groups:                            # 只需遍历可见组
        group_top = g.y()                       # 组在 scroll content 内的 y
        max_off = max(0, g.height() - AV)       # y=max_off 是组底(自然位)，y=0 是组顶
        target = scroll_top + stick_vp - group_top
        y = max(0, min(target, max_off))        # clamp(target, 0, max_off)
        g.avatar.move(g.avatar.x(), y)
```

- 触发点：`verticalScrollBar().valueChanged` + `viewport resizeEvent`
- 性能：MAX_VISIBLE=50 内遍历无压力，无需虚拟化
- ⚠️ 历史踩坑：
  - ~~粘视口顶~~ —— 反了，用户三次纠正：头像钉**视口底**，从下往上挤
  - ~~演示组比视口矮~~ —— 组高必须 > 视口高才看得到挤压过程，测试用例要造 14+ 条长组
  - 每次换会话/窗口 resize 后要重算

### 自己消息是否显示头像
群聊模式私聊：**对方和自己都显示头像**。若嫌自己头像多余，可加配置项，默认先都显示。

## 四、视觉参数（TG 暗色原值）

| 项 | 值 |
|----|-----|
| 聊天区背景 | `#17212B`（dmshoot 暂维持现有背景，见配色节） |
| 对方气泡 | `#182533` 实色 |
| 自己气泡 | 渐变（见配色节 A/B） |
| 正文 | 15px `#FFFFFF` |
| 时间戳 | 11px `#7D8B99`，内嵌气泡右下 |
| 发送者名 | 13px 加粗 `#6AC5E8`（仅对方组顶部显示一次） |
| 气泡 padding | `6px 10px` |
| 组内接缝 | 1px |
| 组间距 | 9px |
| 气泡最大宽 | `min(65% 视口宽, 480px)` |
| 时间格式 | `%H:%M`（跨天用日期分隔线，不再显示完整年月日） |

### 时间戳行为
- 文字短：与文字**同一行**，贴气泡右侧
- 文字长：换行后时间戳**掉到新行末尾右对齐**
- 实现：Qt 里用 `QHBoxLayout(text, meta)` + `alignment: AlignBottom`，text 设 `sizePolicy: Expanding`；或富文本 `<table width=100%>` 右下角放时间戳
- ⚠️ 删除现有"时间戳在气泡外下方独立一行"的布局

### 双勾已读 ✓✓
dmshoot 消息模型无送达状态。**第一版不画勾**，只显示时间；后续有回执再加（画的话颜色 `#A0B9FF`）。

### 日期分隔线
- 样式：居中胶囊 `background: rgba(0,0,0,.28)`、圆角 14px、文字 12.5px `#7D8B99`
- 逻辑：加载消息时相邻两条日期不同 → 插入分隔线，**并切断消息组**

## 五、配色方案（10 套候选，可混搭）

**玩法**：
- 预设：从 A-J 里点一个一键换全套。
- 混搭：底色系 + 气泡系分别选。例如 A 的灰蓝底配 E 的品红气泡。

### 完整参数表

| 编号 | 名称 | 背景 / 侧栏 / 顶栏 | 对方气泡 | 自己气泡渐变 | 时间戳 / 发送者名 | 气质 |
|------|------|-------------------|----------|--------------|-------------------|------|
| A | 冷蓝原味 | `#17212B` / `#0F1620` / `rgba(15,22,32,.92)` | `#182533` | `#6C5CE7 → #8B7BFF` | `#7D8B99` / `#6AC5E8` | TG 官方暗色 |
| B | 暖金适配 | `#1C1710` / `#161109` / `rgba(22,17,9,.92)` | `#2A2418` | `#7A4A1A → #A06B2C` | `rgba(201,154,85,.85)` / `#E0B870` | 配现有橙金 UI |
| C | 石墨极简 | `#16181C` / `#101215` / `rgba(16,18,21,.92)` | `#202226` | `#2E3138 → #43474F` | `#7C828C` / `#B8C0CC` | 无彩中性，内容优先 |
| D | 薄荷青 | `#14201F` / `#0E1716` / `rgba(14,23,22,.92)` | `#17322E` | `#0E7C6B → #19A08C` | `#6F9490` / `#4FD1C5` | 清爽青绿 |
| E | 品红骚粉 | `#1C1420` / `#150E19` / `rgba(21,14,25,.92)` | `#2E1B29` | `#A63A6E → #D1588F` | `#A67C95` / `#F07FB6` | 高饱和，最扎眼 |
| F | 深海蓝 | `#0D1117` / `#010409` / `rgba(1,4,9,.92)` | `#16202E` | `#1F6FEB → #4C8DFF` | `#7D8590` / `#58A6FF` | 开发者蓝 |
| G | 日落橙 | `#1A1414` / `#140F0F` / `rgba(20,15,15,.92)` | `#2E1C1C` | `#D1495B → #F08A5D` | `#A98577` / `#FF9A76` | 强暖烈焰 |
| H | 紫罗兰夜 | `#12101A` / `#0C0A13` / `rgba(12,10,19,.92)` | `#221A33` | `#5B2C9E → #8E4EC6` | `#8B7BA6` / `#B685E8` | 深紫神秘 |
| I | 军绿橄榄 | `#171A15` / `#101310` / `rgba(16,19,16,.92)` | `#232A1C` | `#4B6B2E → #7A9B4B` | `#8A9678` / `#A8C66E` | 低饱和军绿 |
| J | 赛博青紫 | `#0F0F1A` / `#08080F` / `rgba(8,8,15,.92)` | `#1A1730` | `#00D2FF → #7B2FF7` | `#7E7BA8` / `#22E0FF` | 霓虹撞色 |

**默认推荐**：A（最 TG）、B（最融现有界面）、C（最克制耐看）。

预览页左上角 10 套色卡 + 两个混搭下拉，可实时对比。

### 5.2 随机分配逻辑（已确认：10 套全保留，按会话随机，重启重随机）

**规则**：
1. 10 套配色**全部保留**在代码里（`CHAT_THEMES` 常量表，数据见 5.1）
2. 每个**会话（conversation）**随机分到一套
3. **同一次运行内**：同一会话颜色必须稳定 —— 切走再切回来还是那套，滚动/重绘都不能变
4. **每次重启 App**：重新洗牌，所有会话重新随机

**实现（新增 `dmshoot/gui/chat_theme.py`）**：

```python
import os, zlib

CHAT_THEMES = [...]   # 10 套，字段见 5.1 表

class ChatThemeAllocator:
    """按会话随机分配配色。salt 每次进程启动重新生成 → 重启即重洗。"""

    def __init__(self, themes=None, salt=None):
        self.themes = themes or CHAT_THEMES
        # 关键：salt 只在进程启动时生成一次，进程内恒定
        self._salt = salt if salt is not None else int.from_bytes(os.urandom(4), 'big')
        self._cache: dict[str, dict] = {}

    def theme_for(self, conv_id: str) -> dict:
        if conv_id not in self._cache:
            h = zlib.crc32(f"{self._salt}:{conv_id}".encode('utf-8')) & 0xFFFFFFFF
            self._cache[conv_id] = self.themes[h % len(self.themes)]
        return self._cache[conv_id]

    def reshuffle(self):
        """手动重排（设置里可加"重新随机配色"按钮）"""
        self._salt = int.from_bytes(os.urandom(4), 'big')
        self._cache.clear()
```

**接入要点**：
- 分配器做成**单例**（挂在 App 或 ChatView 上，`_theme_allocator`）。⚠️ 绝不能在 `paintEvent` / 每次渲染里 new 一个，否则滚动一下就变色
- 取色时机：`ChatView.set_conversation(conv_id)` 时取一次，缓存在当前会话对象里
- 应用方式：把该套色值注入当前会话的 QSS 变量（或直接 setStyleSheet 到会话容器）
- 可选：设置里加「重新随机配色」→ `reshuffle()` + 重绘所有已加载会话

**作用范围（待定，二选一）**：

| 方案 | 说明 | 优 | 劣 |
|------|------|----|----|
| α 只换自己气泡色 | 背景/对方气泡全局统一，**只有自己气泡**随会话变色 | 切会话不刺眼，能区分"我在不同对话里" | 变化幅度小 |
| β 整套换 | 背景 + 双方气泡 + 顶栏全部随会话换 | 每个会话像换皮肤，辨识度强 | 切会话整屏闪，久看累 |

**不要做**：把盐持久化进配置 —— 用户明确要"每次重启重随机"。日后想固定再加 `theme_pin_<conv_id>` 配置项。

## 六、涉及文件与改动量预估

| 文件 | 改动 |
|------|------|
| `dmshoot/gui/widgets/chat_view.py` | 重写 `BubbleWidget`（时间戳内嵌+圆角状态机），新增 `MessageGroupWidget`（组容器+头像+吸附），`ChatView.load_messages/append_message` 改为按组装配 |
| 消息模型 | 无需改（分组在 UI 层由相邻比较得出） |
| 其他文件 | 不动 |

### 保留的现有机制（勿破坏）
- 气泡复用 `rebind()` 机制 → 组级复用（同方向组复用）
- MAX_VISIBLE=50 上限 + `_trim_bubbles` 滚动裁剪
- 智能滚动 `_smart_scroll` + 新消息浮标按钮
- 历史消息分块加载 `_load_history_chunk`（注意：顶部插入新组后要重算头像吸附）
- Markdown 视图 `show_markdown` 分支不受影响

### 测试要点
1. 连续同人多条（2/3/5 条）圆角状态正确，last 尾巴角方向随 self/other 翻转
2. 组高 > 视口高时上滑，头像钉视口底并相对组上移，卡在组顶
3. 组高 < 视口高时无跳变
4. resize 后吸附位置重算
5. 顶部插入历史消息（`_load_history_chunk`）后头像不残留错误位置
