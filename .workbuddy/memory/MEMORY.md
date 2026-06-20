# DMShoot 项目长期记忆

## 项目定位
多平台私信聚合桌面应用（抖音/B站/小红书），支持 AI 自动回复（DeepSeek API）。

## 技术栈
- Python 3.x + PySide6 GUI
- SQLite (WAL 模式) 持久化
- DeepSeek API (OpenAI 兼容) AI 回复
- Playwright 浏览器扫码登录
- 平台: DouYin_Spider (monkey-patch) / bilibili-api / 纯 HTTP
- **小红书: Spider_XHS 签名 JS (cv-cat) + HTTP 直连，无 Playwright 依赖**

## 架构核心
- MessageBus 单例事件中枢 (6 个 Signal)
- BaseAdapter (QThread) + PluginManager 插件系统
- ConcurrencyManager 共享线程池 (8 workers + 背压控制)
- 双防线去重 (DB 唯一索引 + 内存 set)

## 已知技术债务 (2026-06-05 评审)
- MainWindow 是 God Object (684行)，需提取 AdapterManager
- 配置双轨制 (YAML + SQLite)，需统一
- DouYin SDK monkey-patch 导入脆弱
- 匿名内部类 QThread，需提取为独立 Worker 类
- aiosqlite 声明但未使用，冗余依赖
- 缺少 GUI 集成测试

## 重构优先级
P0: 提取 AdapterManager + 统一配置 → P1: DouYin 封装 + 重连 → P2: 代码质量
综合评分 6.7/10，不需要重写，渐进式重构即可。

## AI 禁止事项
- ⚠️ 绝不私自修改项目代码，所有改动由用户手动执行

## SQLite WAL 管理 (2026-06-14)
- WAL 五层防御已部署: Python atexit + Go 60s 定期 + 紧急恢复脚本
- `wal_autocheckpoint=200` (800KB), `synchronous=NORMAL`
- 紧急恢复: `python tools/wal_checkpoint.py` (支持 --force / --watch)
- 详细方案文档: `docs/WAL_CHECKPOINT_SOLUTION.md`
- **注意**: SQLite PRAGMA 是 per-connection，Python 和 Go 各有独立设置

## 小红书 (XHS) 模块 (2026-06-09 更新)
- **登录**: Playwright → www.xiaohongshu.com (普通用户，获取 IM Cookie) → 再导航 creator 补全
- API: Spider_XHS 签名 JS (Node.js subprocess) + HTTP 直连
- 签名文件: `dmshoot/plugins/xiaohongshu/static/` (5 JS, ~4.5MB + node_modules/crypto-js)

## 小红书 DM API 逆向进展 (2026-06-11 更新)

### API 状态
| 端点 | 状态 | 说明 |
|------|------|------|
| `edith` V3 IM (`/api/im/v3/chats`) | 200 `-100 登录已过期` | 需要移动端 token |
| `edith` V3 IM POST | 406 `code=0 成功` | 空数据，Web Cookie 无 IM 权限 |
| `edith` user/me | 200 ✓ | 获取用户ID正常 |
| Galaxy message/list | 200 ✓ | 仅创作者通知，非 IM 私信 |
| Galaxy DM send | 404 | 无发送端点 |

### SSL Pinning 抓包尝试（全部失败）
- ❌ Frida: LDPlayer 内核 5.15 拦截 ptrace
- ❌ Magisk + LSPosed: 系统盘只读，安装失败
- ❌ LSPatch v0.6: DEX 合并错误，XhsApplication 丢失致 crash
- ❌ DEX CertificatePinner 修补: XHS 有多层 SSL 防护（自定义 Platform + libshield.so）
- ❌ network_security_config 修改: 对 OkHttp CertificatePinner 无效
- ❌ 手机抓包: Android 14 + SSL Pinning 双重阻挡

### 代码变更
- **新建 `im_client.py`**: XHSIMClient 封装 V3 API（待未来启用）
- **更新 `adapter.py`**: 集成 IM client，V3 API 优先 + Galaxy 回退

### 核心结论
**Web Cookie 无法访问 XHS IM 私信 API**。需要移动端 app token (user_token/idToken) 转换机制。
