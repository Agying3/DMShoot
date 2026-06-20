# DMShoot 创作历程

> 基于 Git 提交记录整理，2026年5月26日 — 6月16日，历时三周。

---

## 第一周：从零到原型（5/26 — 5/29）

### Day 1 · 骨架诞生（5/26）
整个项目从零起步，第一天就搭完了核心骨架：
- 玻璃透明主题 + 无边框圆角窗口 + 自定义标题栏
- MessageBus 单例事件总线
- AI 后端（DeepSeek API）
- SQLite 持久化存储
- 多页面架构：首页监控 / 登录 / DeepSeek 设置 / 提示词

一个晚上完成了从框架到 UI 的全部搭建。

### Day 2 · Cookie 与登录（5/27）
- Playwright 浏览器自动扫码登录
- Cookie 提取 → 持久化到 SQLite → 启动时自动验证
- 平台连接验证（用 Cookie 发 HTTP 请求验证抖音/B站登录态）
- 扫码后自动登录，无需手动操作

### Day 3 · 下拉菜单攻坚战（5/28）
- 从 DeepSeek V3 切换到 V4 官方 API
- 模型选择从输入框改为下拉菜单，经历 **12 次迭代** 才实现真透明玻璃效果
- 最终方案：QPushButton + QFrame 自定义弹窗 + setMask 裁剪圆角

### Day 4 · B站适配器 + 首页大改（5/29）
- **B站私信适配器**：轮询新消息 → AI 自动回复 → 自动发送
- 首页大改版：刻度尺 + 通讯录 + 对话气泡 + SQLite 持久化
- 消息去重、头像本地缓存、长期记忆上下文
- **插件化架构重构**：plugins/ 动态发现，刻度尺/适配器/验证全走注册表
- 行为提示词系统、消息滚动优化

第一周结束，B站平台已可正常收发私信 + AI 自动回复。

---

## 第二周：抖音深水区（5/29 晚 — 6/5）

### 抖音适配器（5/29 晚 — 5/30）
- 纯 HTTP 实现创作者后台 API
- Node.js subprocess 调用 `dy_ab.js` 生成签名
- WebSocket 实时消息接收 + 心跳保活
- Playwright 截获 IM protobuf 数据，同步历史消息
- 从 protobuf + API 补全昵称和头像
- 子进程架构消除 asyncio 冲突

### 架构升级（6/4 — 6/5）
- 安全漏洞修复
- ConcurrencyManager 共享线程池 + 优先级调度 + 背压控制
- Cookie 过期检测 + UI 提示
- 启动验证并行化
- 设置对话 UI 优化

---

## 第三周：性能与重构（6/13 — 6/16）

### 性能监控体系（6/13 — 6/15）
- QPainter 手写性能图表（替代 QtCharts，解决 segfault）
- Go msg-service 后端（HTTP + WebSocket）
- WAL 五层防御体系
- B站异步重写 + 抖音异步优化
- 二维码 GUI 内嵌

### P0/P1/P2 全面重构（6/15 — 6/16）
- **P0**：拆分 MainWindow → AdapterManager + AuthController + SignalWiring（1093→827 行）
- **P0**：消灭匿名 QThread → AIWorker + LoginWorker
- **P0**：统一配置（删 YAML，SQLite 单源）
- **P1**：封装抖音 SDK → DouyinClient 门面类，adapter 零直接 SDK 导入
- **P1**：去冗余依赖（aiosqlite/PyYAML）
- **P1**：重连机制 → ReconnectBackoff 指数退避
- **P2**：依赖注入 → 构造函数注入替代单例
- **P2**：错误处理标准 → ErrorCategory 枚举（NETWORK/AUTH/PLATFORM/INTERNAL）
- **P2**：模型统一化 → Message.to_dict()

### 开源发布（6/16）
- 清理全部敏感数据（Cookie、DB、头像缓存、逆向工具、自定义角色提示词）
- 重建 DMShoot-share 可分发版本
- 撰写 README（含架构图、技术细节、截图）
- 推送到 GitHub：https://github.com/Agying3/DMShoot

### 图表真实化（6/16 晚）
- 性能图表从随机假数据改为读取 PerfMonitor 真实指标
- 甘特图/折线图/面积图/环形图/柱状图全部接入真实数据
- 标签颜色与图表线条颜色一致
- 指标卡就地更新，解决滚动复位问题

---

## 数据统计

| 指标 | 数值 |
|------|------|
| 开发周期 | 21 天（5/26 — 6/16） |
| Git 提交 | 150+ |
| 核心代码 | ~8,000 行 Python + ~400 行 Go |
| 支持平台 | 抖音、B站 |
| 重构后评分 | 6.7 → 8.0+ |

---

## 技术演进路线

```
Day 1-4         Day 5-12        Day 13-21
   │               │               │
   ▼               ▼               ▼
 GUI 骨架      B站适配器      性能监控
 消息总线      抖音适配器      WAL 防御
 AI 后端       签名系统       全面重构
 扫码登录      插件架构       开源发布
               IM protobuf    图表真实化
```

---

_本文件由 git log 自动整理生成，记录 DMShoot 从第一行代码到开源发布的完整历程。_
