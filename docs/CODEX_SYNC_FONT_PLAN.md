# 同步字体按钮 — Codex 实现计划

> 配套策略文档：`docs/FONT_STRATEGY.md`（默认 `ui-aacute`，UI 控件用 AaCute 可爱体子集，聊天区强制系统字体，UI 子集锁死打包）。
> 本计划专门讲「在设置→主题页加一个『同步字体』按钮」如何实现。AI 不写业务代码，按此文档落地由 codex 执行。

---

## 一、目标

在**设置页**新增一个独立的 **字体** tab，内含一个 **同步字体** 按钮：

- 点击 → 重新扫描 **UI 源码（`dmshoot/`）**、**提示词（`prompts/` 下的 `.txt`）** 和应用内展示的 **`docs/XHS_IM_逆向日志.md`** 里出现的中文
- 用 `fontTools` 重新生成 UI 子集 `AaCute-UI.ttf`（覆盖旧文件）
- **热重载**进 `QFontDatabase`，即时应用到当前字体模式
- 给用户一个明确的结果反馈（成功重建 N 字 / 不需要同步 / 失败原因）

> 本质：把命令行 `python tools/subset_aacute.py` 变成 GUI 一键操作，省去开发态改了 UI 文案后手动跑脚本。

---

## 二、现状与前置依赖

| 现状 | 说明 | 本计划如何处理 |
|------|------|----------------|
| `FontManager` **未实现** | `dmshoot/gui/` 里只有散落的 `QFont()`/`setFont()`，无统一字体管理 | **Step 0 先实现** `dmshoot/gui/font_manager.py`（含 `apply()` + 新增 `rebuild_ui_subset()`） |
| `subset_aacute.py` 写死 `H:/DMShoot` | 开发机绝对路径，运行时/打包后失效 | 核心逻辑**抽成** `dmshoot/core/font_builder.py`，路径运行时解析，CLI 脚本改为调用它 |
| 字体模式下拉未做 | `FONT_STRATEGY.md` 4.4 已规划但未落地 | 顺手在新建的「字体」tab 里一起做（见 Step 4） |
| `AppConfig` 无 `font_mode` | 配置系统自动遍历 dataclass 字段 | 在 `AppConfig` 定义处加 `font_mode: str = "ui-aacute"` 即可（load/save 自动生效） |

---

## 三、文件改动清单

| 文件 | 动作 | 说明 |
|------|------|------|
| `dmshoot/gui/font_manager.py` | **新建** | 字体加载单例 + `apply(mode)` + `rebuild_ui_subset()` |
| `dmshoot/core/font_builder.py` | **新建** | 可运行时调用的子集生成核心（替换 `subset_aacute.py` 的硬路径） |
| `tools/subset_aacute.py` | **改造** | 改为 `from dmshoot.core.font_builder import build_ui_subset` 的薄 CLI 壳，保持命令行可用 |
| `dmshoot/gui/settings_dialog.py` | **修改** | 新建 `_create_font_tab()` 并在 `__init__` 的 tabs 列表 addTab「字体」（模式下拉 + 同步按钮 + 状态 label） |
| `AppConfig` 定义文件 | **修改** | 加 `font_mode: str = "ui-aacute"` 字段 |
| `dmshoot/gui/main_window.py` | **修改** | 启动时初始化 `FontManager` 单例并 `apply(config.font_mode)` |
| 打包配置（`.spec` / `build.bat` / Nuitka 参数） | **修改** | 内置字体、完整版字体、`prompts/*.txt` 与 fontTools 都要进包；用户生成字体写入可持久化目录（见 Step 5） |

---

## 四、分步实现

### Step 0 — 实现 `FontManager`

新建 `dmshoot/gui/font_manager.py`，内容基于 `FONT_STRATEGY.md` 4.2，并补全同步所需方法：

```python
# dmshoot/gui/font_manager.py
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from dataclasses import dataclass

@dataclass
class RebuildResult:
    status: str          # "ok" | "skipped" | "error"
    chars: int = 0
    reason: str = ""

class FontManager:
    _instance = None

    def __init__(self, font_dir: str):
        self.font_dir = font_dir
        # UI 子集：启动即加载，必须成功（构建时已锁死打包）
        self.ui_id = QFontDatabase.addApplicationFont(f"{font_dir}/AaCute-UI.ttf")
        if self.ui_id < 0:
            sys.stderr.write("警告: AaCute-UI.ttf 加载失败，回退系统字体\n")
        self.ui_family = QFontDatabase.applicationFontFamilies(self.ui_id)[0] \
            if self.ui_id >= 0 else "Microsoft YaHei"
        # 完整版：懒加载
        self.full_id = None
        self.full_family = self.ui_family
        self.current_mode = "ui-aacute"

    @classmethod
    def instance(cls, font_dir=None):
        if cls._instance is None:
            cls._instance = cls(font_dir)
        return cls._instance

    def _ensure_full(self):
        if self.full_id is None:
            self.full_id = QFontDatabase.addApplicationFont(
                f"{self.font_dir}/full/AaCute-full.ttf")
            self.full_family = QFontDatabase.applicationFontFamilies(self.full_id)[0]

    def apply(self, mode: str):
        self.current_mode = mode
        if mode == "system":
            QApplication.setFont(QFont("Segoe UI"))
        elif mode == "full-aacute":
            self._ensure_full()
            QApplication.setFont(QFont(self.full_family))
        else:  # ui-aacute（默认）
            QApplication.setFont(QFont(self.ui_family))

    def rebuild_ui_subset(self, progress_cb=None) -> RebuildResult:
        """同步字体核心：重新生成 UI 子集并热重载。"""
        from dmshoot.core.font_builder import build_ui_subset
        try:
            out = build_ui_subset(self.font_dir, progress_cb)
        except RuntimeError as e:
            return RebuildResult("skipped", reason=str(e))
        except Exception as e:
            return RebuildResult("error", reason=str(e))
        # 热重载：先移除旧 id，再重新加载新文件（同 family 名"Aa偷吃可爱长大的 UI"）
        if self.ui_id >= 0:
            QFontDatabase.removeApplicationFont(self.ui_id)
        self.ui_id = QFontDatabase.addApplicationFont(f"{self.font_dir}/AaCute-UI.ttf")
        if self.ui_id >= 0:
            self.ui_family = QFontDatabase.applicationFontFamilies(self.ui_id)[0]
        self.apply(self.current_mode)   # 重新应用当前模式
        return RebuildResult("ok", chars=out["chars"])
```

> ⚠️ **单例红线**：`FontManager` 必须是单例（进程内一个实例），**绝不能**在 `paintEvent` / 每次重建时 new，否则每次滚动重绘都触发子集分配/加载。

### Step 1 — 抽子集核心到 `font_builder`

新建 `dmshoot/core/font_builder.py`，把 `subset_aacute.py` 的逻辑搬过来，**路径全部运行时解析**：

```python
# dmshoot/core/font_builder.py
import re, sys, pathlib
from fontTools import subset as ftsubset
from fontTools.ttLib import TTFont

def _resolve_paths(font_dir: str):
    """返回 (源码根, 完整版字体路径)。开发态与打包态分别解析。"""
    here = pathlib.Path(__file__).resolve()
    # 开发态: font_builder 在 dmshoot/core/ -> 源码根 = parents[1], tools = parents[2]/tools
    dev_root = here.parents[1]
    dev_tools = here.parents[2] / "tools"
    if (dev_tools / "fonts" / "full" / "AaCute-full.ttf").exists():
        src_root = dev_root
        full = dev_tools / "fonts" / "full" / "AaCute-full.ttf"
        return src_root, full
    # 打包态: 字体在 applicationDirPath()/fonts，源码/提示词若打包则在同目录
    from PySide6.QtWidgets import QApplication
    app_dir = pathlib.Path(QApplication.applicationDirPath())
    full = app_dir / "fonts" / "full" / "AaCute-full.ttf"
    return app_dir, full   # 打包态源码根用 app_dir（prompts 需已打进 datas）

def build_ui_subset(font_dir: str, progress_cb=None) -> dict:
    src_root, full = _resolve_paths(font_dir)
    if not full.exists():
        raise RuntimeError("缺少完整字体 AaCute-full.ttf，无法重建（请先放置完整版）")
    try:
        import fontTools  # noqa
    except ImportError:
        raise RuntimeError("缺少依赖 fontTools，请 pip install fonttools brotli")

    chars, files = _collect_ui_chars(src_root)
    if not chars:
        raise RuntimeError("未找到可扫描的 UI 源码/提示词（打包环境且未含源码，无需同步）")

    text = _build_text(chars)
    if progress_cb: progress_cb(0.3, "扫描完成，生成子集…")

    opts = ftsubset.Options(); opts.glyph_names = False
    opts.notdef_outline = True; opts.recalc_bounds = True
    font = ftsubset.load_font(str(full), opts)
    sub = ftsubset.Subsetter(options=opts)
    sub.populate(text=text)
    sub.subset(font)

    out_ttf = pathlib.Path(font_dir) / "AaCute-UI.ttf"
    tmp = out_ttf.with_suffix(".ttf.tmp")
    ftsubset.save_font(font, str(tmp), opts)     # 先写临时文件，成功再原子替换
    _rename_family(str(tmp))
    tmp.replace(out_ttf)                          # 原子替换，避免覆盖损坏
    if progress_cb: progress_cb(1.0, "完成")
    cmap = TTFont(str(out_ttf)).getBestCmap()
    return {"chars": sum(1 for c in cmap if 0x4E00 <= c <= 0x9FFF),
            "total": len(cmap)}

def _collect_ui_chars(src_root):
    """扫 dmshoot/**/*.{py,json,ui,qss,md} + prompts/**/*.txt 里的汉字。
    逻辑同 tools/subset_aacute.py 的 collect_ui_chars，但用传入的 src_root。"""
    ...
```

要点：
- **临时文件 + 原子替换**：子集化失败绝不能损坏现有 `AaCute-UI.ttf`（打包后那是唯一可用字体）。
- `subset_aacute.py` 改造为薄壳：`build_ui_subset(str(Path(__file__).parent.parent / "tools" / "fonts"))`，保持命令行可用。
- 扫描范围为 `dmshoot/` + `prompts/`，并额外包含首页会直接展示的 `docs/XHS_IM_逆向日志.md`；其余 `docs/` 内容仍排除，避免把开发文档和历史报告全部纳入字体。

### Step 2 — `AppConfig` 加 `font_mode`

定位 `class AppConfig`（Grep `^class AppConfig`）所在文件，加字段：

```python
font_mode: str = "ui-aacute"   # system | ui-aacute | full-aacute
```

`load_config`/`save_config` 自动遍历 dataclass 字段，无需改配置读写逻辑。

### Step 3 — `MainWindow` 启动加载

在 `main_window.py` 初始化 GUI 之后、展示之前：

```python
from dmshoot.gui.font_manager import FontManager
from dmshoot.storage.database import load_config
cfg = load_config()
font_dir = <运行时字体目录>   # 见 Step 5 的 font_dir 解析
fm = FontManager.instance(font_dir)
fm.apply(cfg.font_mode)
```

把 `fm` 通过构造参数或属性传给 `SettingsDialog`，避免对话框内再 new 一个实例。

### Step 4 — 在设置页新建「字体」tab

> 纠正：不要放进「主题」tab。「主题」tab 当前是**空占位**（`self._theme_placeholder = QWidget()`），只承载壁纸概念；字体同步是功能性操作，按用户要求放在**设置对话框（SettingsDialog）内**的独立 tab。

在 `settings_dialog.py` 的 `__init__` 里，`tabs` 的 addTab 列表（约 176-183 行，现有：回复 / 主题 / 数据 / 性能 / 调试）新增一项，建议放在「数据」之后、「调试」之前：

```python
# 在 __init__ 的 tabs 列表里加一行：
tabs.addTab(self._create_font_tab(), "字体")

# 新建方法（与 _create_data_tab() / _create_reply_tab() / _create_debug_tab() 同级）：
def _create_font_tab(self) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setSpacing(10)

    font_group = QGroupBox("字体")
    font_layout = QVBoxLayout(); font_layout.setSpacing(8)

    # 模式下拉（FONT_STRATEGY 4.4）
    mode_row = QHBoxLayout()
    mode_label = QLabel("字体模式"); mode_row.addWidget(mode_label)
    self._font_mode_combo = QComboBox()
    self._font_mode_combo.addItems(["系统默认", "UI 可爱体（默认）", "全站可爱体"])
    mode_row.addWidget(self._font_mode_combo, 1)
    font_layout.addLayout(mode_row)

    # 同步按钮 + 状态
    sync_row = QHBoxLayout()
    self._sync_font_btn = QPushButton("同步字体")
    self._sync_font_btn.setCursor(Qt.PointingHandCursor)
    self._sync_font_btn.clicked.connect(self._on_sync_font)
    sync_row.addWidget(self._sync_font_btn)
    self._font_status_label = QLabel()
    self._font_status_label.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px;")
    sync_row.addWidget(self._font_status_label, 1)
    font_layout.addLayout(sync_row)

    font_group.setLayout(font_layout)
    layout.addWidget(font_group)
    layout.addStretch()
    return w
```

按钮回调（**子集化耗时几百 ms~数秒，必须放后台线程，否则卡死 UI**）：

```python
def _on_sync_font(self):
    from PySide6.QtCore import QThread, QRunnable, QThreadPool, pyqtSignal
    self._sync_font_btn.setEnabled(False)
    self._sync_font_btn.setText("同步中…")
    # 用 QThread 跑 build，结束回主线程弹反馈
    class _Worker(QThread):
        done = pyqtSignal(object)
        def run(self):
            fm = FontManager.instance()
            self.done.emit(fm.rebuild_ui_subset())
    w = _Worker()
    w.done.connect(self._on_sync_done)
    w.start()
    self._sync_worker = w   # 防止被 GC

def _on_sync_done(self, result: RebuildResult):
    self._sync_font_btn.setEnabled(True)
    self._sync_font_btn.setText("同步字体")
    if result.status == "ok":
        self._font_status_label.setText(f"已重建 {result.chars} 字，重启后最稳")
        GlassPopup(self, "字体已同步", f"UI 子集已重建，覆盖 {result.chars} 个汉字。\n"
                    "部分已渲染控件可能需要重启应用才完全刷新。", "info").exec()
    elif result.status == "skipped":
        GlassPopup(self, "无需同步", result.reason, "info").exec()
    else:
        GlassPopup(self, "同步失败", result.reason, "error").exec()
```

`GlassPopup` 是现有对话框（settings_dialog.py:17 已定义），直接复用。

> 下拉切换模式也接 `fm.apply(mode)` + 写 `config.font_mode` + `save_config`（见 `FONT_STRATEGY.md` 4.4）。

### Step 5 — 打包 datas 与用户字体覆盖目录（同步按钮可用的前提）

`FONT_STRATEGY.md` 五节已要求锁死 `AaCute-UI.ttf`。本按钮要**在打包后也能用**，还必须满足：

| 资源 | 是否必打包 | 原因 |
|------|-----------|------|
| `fonts/AaCute-UI.ttf` | **必须** | UI 字体本体 |
| `fonts/full/AaCute-full.ttf` | 必须（若开同步/全站可爱体） | 子集化/完整版的源 |
| `prompts/*.txt` | **必须（同步按钮依赖）** | 扫描源；不打则打包态无法重建子集 |
| `fontTools` | 必须（同步按钮依赖） | 运行时子集化需要 |

> 本项目选择保留打包态同步能力，因此 `fontTools`、完整版字体和 prompts 都随包提供。
> 同步结果不写入 `_MEIPASS`，而是写入 `%LOCALAPPDATA%/DMShoot/fonts`；启动时用户目录
> 中的 `AaCute-UI.ttf` 优先于内置版本。

`font_dir` 运行时解析（共用）：
```python
from PySide6.QtWidgets import QApplication
import os
import pathlib
import sys
if getattr(sys, "frozen", False):
    font_dir = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home() / "AppData" / "Local")) / "DMShoot" / "fonts"
else:
    font_dir = pathlib.Path(__file__).resolve().parents[2] / "tools" / "fonts"
```

### Step 6 — 路径/家族名红线（重申 FONT_STRATEGY 约束）

1. **Qt 不支持 WOFF**：全部走 TTF，`addApplicationFont` 只认 TTF/OTF。
2. **family 名区分**：UI 子集内部名已是 `Aa偷吃可爱长大的 UI`（PostScript `AaCuteUI`），与完整版 `Aa偷吃可爱长大的` 不同；`font_builder._rename_family` 必须保留此改名逻辑，FontManager 一律用 `applicationFontFamilies(id)[0]` 取实际名，**不写死字符串**。
3. **UI 子集锁死打包**：见 Step 5 datas。
4. **ui-aacute 下 ChatView 气泡强制系统字体**：同步只影响 UI 子集，聊天区仍走系统字体，无需在同步时动 ChatView（但 `apply()` 重绘时确保气泡未被全局字体污染）。

---

## 五、边界与降级（给 codex 的硬约束）

- **打包态无源码 / 无 tools 目录** → `build_ui_subset` 返回 `skipped`，原因「未找到可扫描的 UI 源码/提示词」。按钮可保留但点击只弹提示，不报错崩溃。
- **fontTools 未安装** → 返回 `skipped`，提示 `pip install fonttools brotli`。
- **完整版 `AaCute-full.ttf` 缺失** → 返回 `skipped`，提示需放置完整版。
- **子集化失败** → 绝不破坏现有 `AaCute-UI.ttf`（原子替换保证），返回 `error` 并保留旧字体。
- **热重载后已渲染控件** → `removeApplicationFont` + 重新 `add` + `apply` 后，部分已创建控件可能仍缓存旧字形；**成功反馈里明确提示"重启后最稳"**，不要假装 100% 即时。
- **绝对不要**把子集化逻辑写在 GUI 主线程（卡 UI），也不要每次 paint 都调 `rebuild`。

---

## 六、测试要点

1. 开发态启动：UI 控件是可爱体，聊天区是系统字体，无混排（即 `ui-aacute` 默认生效）。
2. 开发态点「同步字体」：弹「已重建 N 字」，UI 仍可爱体、聊天仍系统，不崩。
3. 故意在 UI 文案里加一个生僻字（如「龘」）→ 同步 → 该控件不再缺字（不再 fallback 系统字体）。
4. `font_mode` 下拉切换三种模式，即时生效，无需重启（模式切换本就是同 family 换量，应实时）。
5. `prompts/` 新增一条含生僻字的人格 → 同步 → 该提示词编辑框不缺字。
6. 打包态从 `dist/` 启动：字体生效；当前构建已包含 prompts、完整版字体和 fontTools，同步按钮可用。
7. 同步过程中狂点按钮：因禁用 + 单 worker，不会重入/崩溃。
8. 子集化中途模拟失败（删完整版）：旧 `AaCute-UI.ttf` 完好，应用仍能正常显示 UI 可爱体。

---

## 七、验收标准

- [x] 设置页独立「字体」tab 含模式下拉、同步字体按钮和状态 label
- [x] 点击同步重新生成 `AaCute-UI.ttf` 并热重载，UI 可爱体保留、聊天系统字体不变
- [x] 改 UI 文案/提示词后同步，新字不缺
- [x] 三种模式可切换且持久化（`font_mode` 写入配置）
- [x] 打包后字体生效，同步结果持久化到用户目录
- [x] 失败路径不崩溃、不损坏现有字体文件
