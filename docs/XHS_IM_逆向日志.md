# XHS & 快手 IM 逆向工程日志

> 项目: DMShoot | 目标: 小红书 + 快手 IM 私信收发  
> 周期: 2026-06-09 ~ 2026-06-12 | 状态: **暂停——需 root 设备**

---

## 〇、用户可见功能进度

### 小红书

| 功能 | 状态 |
|------|------|
| 登录后显示昵称 | ✅ |
| 登录后显示头像 | ✅ |
| 首页私信通讯录 | ❌ |
| 通讯录显示对方昵称 | ✅ 代码就绪（API 通，无数据） |
| 通讯录显示对方头像 | ✅ 代码就绪 |
| 聊天历史记录 | ❌ |
| 发送私信 | ❌ |
| 接收新消息 | ❌ |
| 消息时间戳 | ✅ |

### 快手

| 功能 | 状态 |
|------|------|
| 登录后显示昵称 | ✅ |
| 登录后显示头像 | ❌ |
| 首页私信通讯录 | ❌ |
| 聊天历史记录 | ❌ |
| 发送私信 | ❌ |
| 接收新消息 | ❌ |

---

## 一、14 种方法 & 失败原因

### 第 1 类：直接 API 调用（HTTP）

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 1 | IM API 端点测试 | 向 14 个已知/推测端点发请求 | ❌ | Web Cookie 无 IM 权限（全 404/406） |
| 2 | Galaxy 创作者 API | `creator/api/galaxy/message/list` | ✅ 200 | 返回空数组（仅创作者通知，非 IM 私信） |
| 3 | edith V3 IM | `edith/api/im/v3/chats` | ❌ | 406 code=0，data 为空——需要移动端 token |
| 4 | Web 收件箱 | `api/sns/web/v1/inbox/list` | ❌ | 404，Web 端无收件箱功能 |

### 第 2 类：SSL Pinning 绕过（APK 层）

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 5 | DEX CertificatePinner 修补 | 搜索 `CertificatePinner.check()` → return-void | ✅ 修补成功 | 仅 Java 层；XHS 有 native libshield.so 多层防护 |
| 6 | Smali 全量修补 | 修补 8 个 TrustManager/Verifier/Pinner | ✅ 修补成功 | APK 重打包后 XhsApplication 类丢失，闪退 |
| 7 | network_security_config | 替换 AXML 为信任 user+system CA | ✅ 替换成功 | OkHttp CertificatePinner 不受 NSC 影响 |

### 第 3 类：MITM 代理（网络层）

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 8 | WSL2 + mitmdump | WSL 内 mitmproxy + LDPlayer iptables → 10.0.2.2 | ❌ | WSL2 端口转发仅限 localhost，网桥不通 |
| 9 | WSL2 镜像网络 | `.wslconfig` 设 `networkingMode=mirrored` | ❌ | Windows 10 19045 不兼容，WSL Ubuntu 直接挂 |
| 10 | Docker + LDPlayer | Docker mitmdump (0.0.0.0:8888) + 模拟器 iptables DNAT | ❌ | 模拟器网桥隔离，TCP SYN 发出但 SYN-ACK 永远不回 |
| 11 | Docker + MuMu | 同上，预期 NAT 模式通 10.0.2.2 | ❌ | PING 通但 TCP 被 Windows 防火墙拦截 |

### 第 4 类：Frida 动态注入

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 12 | Frida server x86_64 (LDPlayer) | push frida-server + 启动 | ❌ | LDPlayer 内核 5.15 拦截 ptrace |
| 13 | Frida server x86_64 (MuMu) | 同上 + Frida 17.x API 适配 | ✅ 连接成功 | ARM→x86 原生桥隔离——hook 的 write/read 只捕获到 x86 层的 app_process64 调用，真正的网络 I/O 在 ARM 翻译空间执行，不可见 |
| 14 | Frida Gadget arm64 | 注入 APK + LD_PRELOAD | ❌ | MuMu libhoudini 翻译层崩溃 (SIGSEGV 0xdead1044) |

### 第 5 类：旁路抓包

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 15 | strace + read/write | 拦截进程 syscall | ✅ 105MB 数据 | 99.9% 渲染代码；HTTPS write 是密文 |
| 16 | tcpdump 原版 APK | LDPlayer + ADB 点击 | ⚠️ 176KB | App 卡隐私弹窗，只有 JPush/GeTui 推送 SDK 流量 |

### 第 6 类：APK 工具链

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 17 | arm64-v8a APK 下载 | 谷歌 Play/APKPure/华为/小米/OPPO/酷安等 7 个镜像 | ❌ | 全部超时或反爬阻断 |
| 18 | 从 iQOO 手机提取 | `pm path` + `adb pull` | ✅ 成功 | 抽出 arm64-v8a 版 XHS APK（167MB），但模拟器 ARM 翻译仍不可靠 |

### 第 7 类：本地数据提取

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 19 | 本地 SharedPreferences | root ADB 读 `/data/data/com.xingin.xhs/` | ❌ | 模拟器没登过小红书，数据为空 |
| 20 | 进程内存扫描 | Frida + `Process.enumerateRanges()` | ❌ | 翻译层隔离，读取到的内存片段不含 token |
| 21 | debuggerd 内存 dump | `debuggerd -b PID` | ❌ | 进程被 kill（这是 crash handler 的正常行为） |

### 第 8 类：模拟器环境

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 22 | AVD ARM 模拟器 | Android SDK + ARM64 系统镜像 | ❌ | 沙箱封锁 H 盘，5.7GB SDK 所有文件无法访问 |

### 快手特有

| # | 方法 | 详情 | 结果 | 死因 |
|---|------|------|------|------|
| 23 | 快手 Web API 探测 | 测试 13 种 API 路径模式 | ❌ | 全部 404；快手 Web 端和 XHS 一样无 IM |
| 24 | live.kuaishou.com 消息页 | Playwright 导航 | ❌ | 登录页有消息入口但触发登出——live 域需要独立认证 |

---

## 二、根本原因

```
                   ┌──────────────┐
                   │  XHS/快手 IM  │
                   │  (移动端专属)  │
                   └──────┬───────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
     ┌──────────┐  ┌──────────┐  ┌──────────┐
     │ ARM 架构  │  │ SSL 防护 │  │ 移动 Token │
     │ (仅arm)  │  │ (多层)   │  │ (Cookie无) │
     └────┬─────┘  └────┬─────┘  └────┬─────┘
          │             │             │
     ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
     │模拟器    │   │DEX修补   │   │Web Cookie│
     │ARM翻译   │   │不够用    │   │权限不足   │
     │不可靠    │   │native层  │   │          │
     └─────────┘   │仍在防护   │   └─────────┘
                   └─────────┘
```

三个堡垒相互保护：要抓移动端 token → 必须绕过 SSL Pinning → 必须在 ARM 环境下运行。而我们在 x86 模拟器上同时攻克三个，每个单独都是硬仗。

---

## 三、可能成功的方法（前提：root 设备）

| 方案 | 设备要求 | 时间 | 成功率 |
|------|---------|------|--------|
| 真机 Magisk + LSPosed + Frida | 任何 root 后的 Android 手机 | ~4 小时 | 95% |
| iQOO U3x 售后降级 | 跑一趟 Vivo 售后降级到 1.9.0 | 半天 | 85% |
| Android Studio AVD ARM | 沙箱可访问的磁盘 + 2GB 下载 | ~1 天 | 85% |
| 二手 root 手机 | 淘宝/闲鱼买已 root 的旧机 | 2 天 | 95% |

**最快出结果**：买一台已 root 的二手 Android 手机（Pixel、一加、小米等开放机型），插上 ADB 即可。

---

## 四、当前可用资产

| 资产 | 路径 | 用途 |
|------|------|------|
| 签名系统 | `dmshoot/plugins/xiaohongshu/` | x-s/x-t 签名（可用） |
| IM Adapter 代码 | `adapter.py`, `im_client.py` | 完整实现（缺 token） |
| 快手 Adapter | `dmshoot/plugins/kuaishou/adapter.py` | 登录已通（IM 不可用） |
| arm64-v8a XHS APK | `tools/xhs_arm64.apk` (167MB) | Google Play 版 |
| Frida server arm64 | `tools/frida-gadget-arm64.so` (25MB) | ARM64 gadget |
| Frida Hook 脚本 | `tools/xhs_hook.js` | OkHttp 截获脚本 |
| mitmproxy Docker | `docker/` | MITM 代理已就绪 |
| Kuaishou Cookie | `dmshoot/data/kuaishou_cookie.json` | 17 个 Cookie（已登录） |
