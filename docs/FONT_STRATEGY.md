# DMShoot 字体策略（AaCute 方案）

> 参考 NapCat WebUI 的字体处理思路，结合 DMShoot 是**本地桌面 App**（不是 Web）的实际情况。
> 配套脚本：`tools/subset_aacute.py`，已产出的字体在 `tools/fonts/`。

---

## 一、核心结论

| 层 | 字体 | 是否随包 | 体积 | 缺字风险 |
|----|------|---------|------|---------|
| **UI 控件层**（按钮/标题/菜单/状态栏） | AaCute **UI 子集** `AaCute-UI.ttf` | **必须锁死打包**（构建时生成，进依赖） | 0.50 MB | 无（扫源码生成） |
| **聊天内容层**（气泡/私信正文） | 可选：系统字体 / 完整 AaCute | 系统默认；完整版可选按需加载 | 系统 0 / 完整 11 MB | 系统无；完整版无 |

**用户原话**：「像 NapCat 锁死的一样，UI 字体必须随依赖一起下载，聊天区可选，就算打包后也要这样。」

---

## 二、为什么 UI 用子集、聊天用可选

- 中文字体天生巨大：AaCute 完整版 **11.06 MB / 20902 汉字**；子集（只含 UI 用到的 889 字）**0.33 MB**。
- UI 文案是**写死的**：构建时扫描 `dmshoot/` 源码、`prompts/` 提示词和应用内直接展示的 `docs/XHS_IM_逆向日志.md`，缺字的字根本不会出现在界面上 → 子集零风险。
- 聊天内容是**动态的**：用户昵称、私信正文不可预测，子集必然缺字 → 所以聊天区不能锁死可爱体，必须**可选项**（默认系统字体，勾选才用完整版）。

### 字体文件清单（已下载到 `tools/fonts/`）

| 文件 | 大小 | 汉字 | 用途 |
|------|------|------|------|
| `full/AaCute-full.ttf` | 11.06 MB | 20902 | 完整版，聊天区"可爱体"选项用 |
| `AaCute-UI.ttf` | 0.50 MB | 1317 | **UI 控件层**，锁死打包 |
| `AaCute-UI.woff` | 0.37 MB | 1317 | 同上的网页格式（预览用） |
| `AaCute.woff` | 291 KB | 750 | NapCat 打包的原子集（参考，勿直接用） |
| `JetBrainsMono.ttf` / `-Italic.ttf` | 296/302 KB | 无中文 | 日志 / 代码块 |

---

## 三、三种字体模式（设置项）

> **用户已拍板：默认 `ui-aacute`**（2026-09-01）。UI 控件用可爱体子集，聊天区用系统字体。

```python
FONTMODE = {
    "system":      "系统默认（Segoe UI + 微软雅黑）",
    "ui-aacute":   "UI 用可爱体，聊天用系统字体",   # 默认推荐
    "full-aacute": "全站可爱体（含聊天区）",
}
```

| 模式 | app 全局字体 | ChatView 覆盖 | 加载的字 | 体积代价 |
|------|------------|--------------|---------|---------|
| `system` | 系统栈 | 无（也系统） | 0 | 0 |
| `ui-aacute` | UI 子集 AaCute | **聊天气泡强制系统字体** | 0.33 MB（启动即载） | 0.33 MB |
| `full-aacute` | 完整 AaCute | 无（也完整） | 0.33 + 11 MB（懒加载） | 11.33 MB |

---

## 四、实现要点（给 codex）

### 4.0 ⚠️ 完整版与 UI 子集的 family 名必须不同
两者默认都叫 `Aa偷吃可爱长大的` → Qt 里 `QFont(family)` 会混淆。
`tools/subset_aacute.py` 已给 UI 子集改名内部 family 为 **`Aa偷吃可爱长大的 UI`**（PostScript 名 `AaCuteUI`）。
FontManager 一律用 `QFontDatabase.applicationFontFamilies(id)[0]` 取**实际加载到的名**，不要写死字符串。

### 4.1 ⚠️ Qt 不支持 WOFF
`QFontDatabase.addApplicationFont()` 只认 **TTF / OTF**。那些 `.woff` 只能给网页用。
DMShoot 全部走 TTF。

### 4.2 FontManager（启动时加载 UI 子集，锁死）

```python
# dmshoot/gui/font_manager.py
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

class FontManager:
    def __init__(self, font_dir: str):
        # UI 子集：启动即加载，必须成功（构建时已锁死打包）
        self.ui_id = QFontDatabase.addApplicationFont(f"{font_dir}/AaCute-UI.ttf")
        self.ui_family = QFontDatabase.applicationFontFamilies(self.ui_id)[0]

        # 完整版：懒加载，只有选 full-aacute 才读
        self.full_id = None
        self.full_family = self.ui_family
        self.font_dir = font_dir

    def _ensure_full(self):
        if self.full_id is None:
            self.full_id = QFontDatabase.addApplicationFont(
                f"{self.font_dir}/full/AaCute-full.ttf")
            self.full_family = QFontDatabase.applicationFontFamilies(self.full_id)[0]

    def apply(self, mode: str):
        if mode == "system":
            QApplication.setFont(QFont("Segoe UI"))
            return "system"
        if mode == "full-aacute":
            self._ensure_full()
            QApplication.setFont(QFont(self.full_family))
            return self.full_family
        # ui-aacute（默认）
        QApplication.setFont(QFont(self.ui_family))
        return self.ui_family
```

### 4.3 ChatView 在 ui-aacute 下必须覆盖为系统字体

`app.setFont()` 是全局的，会渗透到气泡。UI 子集只有 889 字，聊天正文必有缺字 →
**ui-aacute 模式下，ChatView 给气泡显式 setFont 回系统字体**：

```python
# chat_view.py 加载时
if self.font_mode == "ui-aacute":
    sys_font = QFont("Microsoft YaHei")   # 或 Segoe UI
    for w in (self.bubble_widgets): w.setFont(sys_font)
```

`full-aacute` 模式则不动（气泡也用完整 AaCute，一个不缺）。

### 4.4 读取 / 持久化
- 模式存 `database.load_config()/save_config()` 的 `font_mode` 字段（复用现配置系统，勿新增 yaml）
- 设置页加一个下拉：`系统默认 / UI 可爱体 / 全站可爱体`
- 切换后调用 `FontManager.apply(mode)` + 重绘 ChatView

---

## 五、打包（关键：UI 子集必须进产物）

### PyInstaller（`DMShoot.spec` 或 build.bat）
```python
a.datas += [
    ('tools/fonts/AaCute-UI.ttf',        'fonts'),
    ('tools/fonts/full/AaCute-full.ttf', 'fonts/full'),   # 仅当 full-aacute 选项开启时必带
    ('tools/fonts/JetBrainsMono.ttf',    'fonts'),
]
```
运行时 `font_dir` 取 `QApplication.applicationDirPath() + "/fonts"`。

### Nuitka
```bash
--include-data-files=tools/fonts/AaCute-UI.ttf=fonts/AaCute-UI.ttf \
--include-data-files=tools/fonts/full/AaCute-full.ttf=fonts/full/AaCute-full.ttf
```

> 「就算打包后也要这样」= 这步必须做，否则打包后 `AaCute-UI.ttf` 找不到 → UI 字体回退系统字体。

### 5.1 打包版同步字体的持久化路径

PyInstaller 单文件程序的 `_MEIPASS` 是每次启动都会重新生成的临时解包目录，
不能把用户同步后的字体直接写回那里。运行时采用两层字体目录：

| 目录 | 用途 | 优先级 |
|------|------|--------|
| `_MEIPASS/fonts` | 程序内置的初始 UI 子集、完整版字体 | 低 |
| `%LOCALAPPDATA%/DMShoot/fonts` | 用户同步生成的 `AaCute-UI.ttf/.woff` | 高 |

打包版启动时优先加载用户目录中的 UI 子集；用户尚未同步时回退到内置字体。
同步操作始终写入用户目录，因此关闭程序并重新启动后仍然有效。完整版字体
继续从内置目录懒加载，不复制到用户目录，避免额外占用磁盘空间。

### 重新生成子集
UI 文案改了（新增中文按钮/弹窗）后重跑：
```bash
python tools/subset_aacute.py    # 重新扫 dmshoot/ + prompts/ + XHS_IM 逆向日志生成 AaCute-UI.ttf/.woff
```

---

## 六、与 NapCat 的差异

| 点 | NapCat WebUI | DMShoot |
|----|-------------|---------|
| 默认字体 | system（Segoe UI 栈） | ui-aacute（UI 控件用可爱体子集） |
| 子集用途 | 仅 `aacute` 模式，且是全站全局 | UI 控件层锁死，聊天层单独可选 |
| 缺字处理 | 逐字 fallback（混排） | ChatView 强制系统字体，杜绝混排 |
| 完整版 | 仓库里但不打包 | 可选按需懒加载（聊天区可爱体选项） |
| 打包 | Web 静态资源 | PyInstaller/Nuitka datas 锁死 UI 子集 |

---

## 七、测试要点
1. 启动即查 `AaCute-UI.ttf` 是否成功加载（加载失败应告警，并不崩溃）
2. ui-aacute 下：主窗口按钮/标题是可爱体，聊天气泡是系统字体，无混排
3. 聊天发一句含生僻字（如「龘」「靐」）在 ui-aacute 下仍正常（走系统字体）
4. full-aacute 下：聊天气泡也是可爱体，且生僻字不缺
5. 打包后从 `dist/` 启动，字体仍生效（验证 datas 包含）
6. 切换模式无需重启（实时 apply）
