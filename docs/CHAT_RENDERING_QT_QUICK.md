# 聊天渲染与虚拟化实现说明

## 结论

DMShoot 的聊天区默认使用 Qt Quick，QWidget 保留为兼容和异常降级后端：

| 后端 | 用途 | 渲染方式 |
| --- | --- | --- |
| `quick` | 默认生产后端 | `QQuickWidget` + QML `ListView` + Qt Quick Scene Graph，透明覆盖 QWidget 壁纸 |
| `widgets` | 显式兼容/降级后端 | 原有 QWidget 气泡实现，与主窗口壁纸共享 QWidget 合成链路 |

Quick 聊天区使用透明 FBO 覆盖在现有 QWidget 聊天容器上，壁纸仍由主窗口的 `WallpaperBody` 统一绘制。Quick 不绘制聊天底板，因此空白区域和消息气泡之间不会切断壁纸。Windows 下保留 `WA_AlwaysStackOnTop`，确保透明 FBO 透出的是 DMShoot 父级壁纸，而不是窗口外的桌面或其他应用。Windows 通常使用实际可用的图形后端，例如 `Direct3D11`。

## 运行时选择

默认值是 `auto`，启动时优先使用 Quick；以下环境变量可用于兼容和诊断：

```text
DMSHOOT_CHAT_RENDERER=auto       # 默认生产模式：Quick 透明聊天区
DMSHOOT_CHAT_RENDERER=quick      # 显式启用 Quick
DMSHOOT_CHAT_RENDERER=widgets    # 强制旧版 QWidget 聊天区
DMSHOOT_SOFTWARE_RENDER=1        # 强制兼容后端
```

`ChatView.renderer_name` 返回当前使用的 `quick` 或 `widgets`，`ChatView.renderer_backend` 返回 `Direct3D11`、`OpenGL`、`Software` 或 `Unknown`。Quick 初始化、QML 解析和 Scene Graph 初始化失败都只影响聊天渲染器，不阻止主窗口启动。

## 虚拟列表与历史分页

- 首次进入会话读取最新 100 条消息。
- 滚动到顶部后，通过 `(timestamp, id)` 游标从 SQLite 读取更早的 100 条。
- 数据库查询按 `timestamp DESC, id DESC` 取页，再反转为聊天区需要的 oldest-first 顺序。
- 插入历史前记录当前最旧消息的可视偏移，模型重置后恢复该消息位置，避免阅读位置跳动。
- 新消息使用模型增量插入；如果仍在底部则自动跟随，否则显示新消息按钮。
- QWidget 回退模式仍由旧实现限制可见消息规模，不走无限控件累积路径。

QML `ListView` 设置了有限 `cacheBuffer` 和 `reuseItems`。消息正文、时间、方向、圆角、尾巴、头像和分组信息都作为轻量模型数据传入；气泡路径由 QML Shape 绘制，避免每条消息创建 QWidget、QLabel 和独立布局树。滚动路径还做了三项高频优化：

- 普通正文直接走 `TextEdit.PlainText`，只有包含 URL 的消息才走富文本解析；
- 分组消息通过模型原生数组传入，避免每个 delegate 重复 `JSON.stringify/parse`；
- `contentY` 滚动期间只在“接近底部”状态发生变化时通知 Python，头像吸附使用列表内容坐标计算，避免逐像素坐标映射和跨语言信号。

当前聊天列表缓存 320px，并使用 `pixelAligned: false`、较高的桌面滑动速度和较低的减速参数，让触控板/鼠标拖动更接近移动端的连续惯性；真实壁纸合成仍由透明 `QQuickWidget` 完成，因此不能绕过 Quick FBO 的一次合成成本。

## TG 分组兼容

Python 模型按相邻发送者、消息方向和日期分组。组内消息使用数字 `Repeater` 模型，通过索引读取 JSON 行数据，避免 Qt Quick 对 Python 嵌套 `QVariantList` 的不稳定处理。每组仍保留：

- 首条、中间、末条和单条消息的不同圆角；
- 最后一条消息的尾巴方向；
- 非本人头像在消息组底部吸附并随滚动上移；
- 发送者名称、时间、双勾、头像缓存和可选链接。

正文使用 `TextEdit`，保持鼠标选择、键盘选择和复制能力。URL 在 Python 侧先转义，再转换成可点击富文本链接。

## 现场验证结果

在当前 Windows 环境中，Qt Quick 探针确认：

- 图形后端：`Direct3D11`；
- 5000 条消息全部保留在模型中；
- 长列表 `contentHeight` 正确计算；
- 实际 Quick 可视树约 281 个 item，未随 5000 条消息线性增长；
- 混合收发消息、三条连续消息、日期分隔、头像和 URL 均可正常渲染；
- Quick 专项测试和 QWidget 默认生产路径测试通过。

## 打包要求

`DMShoot.spec` 已加入 Qt QML、Qt Quick、Qt Quick Widgets 隐式依赖，并将 `dmshoot/gui/qml/` 作为数据资源打包。发布版如果无法初始化 Scene Graph，会自动切换到 QWidget 后端，保持登录、通讯录和消息收发功能可用。
