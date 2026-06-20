# 抖音连接失败修复报告

**日期**: 2026-05-29
**Commit**: `aab17ec` (cookie fix) + `c1b9544` (docs)

## 问题
抖音扫码后显示"连接失败"，`connect()` 返回 False，适配器无法启动。

## 根因
Playwright 扫码登录流程只在 `creator.douyin.com` 操作，提取的 cookie 字符串（4164字符，38 个键）缺少 `s_v_web_id`。

SDK 多处硬依赖此 cookie：
- `get_my_uid()` → `auth.cookie['s_v_web_id']` → **KeyError 崩溃**
- `get_notice_list()` → 同上
- `send_msg()` → 同上
- `proto.py build_normal_request()` → 同上

`s_v_web_id` 只在访问 `www.douyin.com` 时由服务端设置。

## 修复（双重保护）

### Layer 1: cookie_reader.py
登录成功后补充访问 `www.douyin.com`，等待 2 秒后提取完整 cookie：
```python
await page.goto("https://www.douyin.com/", timeout=30000)
await asyncio.sleep(2)
```

### Layer 2: douyin_sdk.py create_auth()
如果 cookie 仍缺 `s_v_web_id`（如历史存储的旧 cookie），自动生成伪值兜底：
```python
if "s_v_web_id" not in cookie_str:
    fake_id = f"verify_{generate_fake_webid()}_{generate_fake_webid(19)}"
    cookie_str += f"; s_v_web_id={fake_id}"
```

## 验证结果
- `create_auth()` → ✅ auth 创建成功（cookie keys: 40）
- `get_uid()` → ✅ UID = 7581349050324026405
- `get_notice_list()` → ✅ 返回 10 条通知
- `DouyinAdapter.connect()` → ✅ 返回 True

## 建议
用户应**重新扫码一次**以获取真正由服务端签发的 `s_v_web_id`（自动生成的伪值功能正常但不如真实值可靠）。
