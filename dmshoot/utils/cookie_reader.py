"""Playwright 浏览器扫码登录 + Cookie 提取"""

import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent


def _dbg(msg: str):
    """写 debug 日志到文件 (确保可见)"""
    try:
        log_path = _PROJECT_ROOT / "data" / "adapter_debug.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [XHS-COOKIE] {msg}\n")
    except Exception:
        pass


async def _extract_ticket_from_cookies(page) -> Optional[str]:
    """从 cookie 中提取 web_protect ticket（certType=cookie 场景）"""
    cookies = await page.context.cookies()
    # 查找可能包含 ticket 的 cookie
    ticket_names = ["s_sdk_ticket", "sdk_ticket", "web_protect_ticket", "x-ss-stub"]
    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        if any(tn in name.lower() for tn in ticket_names):
            import logging
            logging.getLogger("cookie_reader").info(f"cookie ticket found: {name}")
            return value
    # 兜底：查找值包含 eyJ 或 ticket 特征的 cookie
    import json
    for c in cookies:
        value = c.get("value", "")
        if value and value.startswith("eyJ"):
            try:
                import base64
                decoded = base64.b64decode(value + "===").decode()
                if "ticket" in decoded.lower() or "expire" in decoded.lower():
                    import logging
                    logging.getLogger("cookie_reader").info(f"cookie ticket from base64: {c.get('name')}")
                    return value
            except Exception:
                pass
    return None


async def _login_douyin(account_file: str, on_qr_callback=None) -> Optional[dict]:
    """
    抖音扫码登录，返回 {cookie, web_protect, keys} 或 None。
    account_file: 用于保存二维码图片的路径
    on_qr_callback(b64_data_url): 收到二维码时调用
    """
    import base64, logging
    _clog = logging.getLogger("cookie_reader")
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()

            await page.goto("https://creator.douyin.com/", timeout=60000, wait_until="domcontentloaded")

            # 点击扫码登录tab
            _qr_sent = False
            try:
                scan_tab = page.get_by_text("扫码登录", exact=True).first
                await scan_tab.wait_for(timeout=10000)
                await scan_tab.click()
                _clog.info("Waiting for QR code...")
                qr_selectors = [
                    'img[aria-label="二维码"]',
                    'img[alt*="二维码"]',
                    'img[alt*="QR"]',
                    '.qrcode img',
                    '[class*="qrcode"] img',
                    '[class*="QR"] img',
                ]
                for _qr_retry in range(15):
                    await asyncio.sleep(1)
                    for sel in qr_selectors:
                        try:
                            qr_img = page.locator(sel).first
                            if await qr_img.count() > 0:
                                qr_src = await qr_img.get_attribute("src") or ""
                                if qr_src and qr_src.startswith("data:image/"):
                                    if on_qr_callback:
                                        on_qr_callback(qr_src)
                                    _clog.info(f"QR sent to GUI from [{sel}]")
                                    _qr_sent = True
                                    break
                        except Exception:
                            continue
                    if _qr_sent:
                        break
                if not _qr_sent:
                    _clog.warning("QR not found after 15s")
            except Exception:
                pass  # 可能已在扫码页

            # ── QR 已发给 GUI，现在最小化浏览器 ──
            if _qr_sent:
                try:
                    cdp = await page.context.new_cdp_session(page)
                    win_info = await cdp.send("Browser.getWindowForTarget")
                    wid = win_info.get("windowId")
                    if wid:
                        await cdp.send("Browser.setWindowBounds", {
                            "windowId": wid,
                            "bounds": {"windowState": "minimized"}
                        })
                except Exception:
                    pass

            # 等待登录完成（轮询检测，每秒检查）
            _verify_restored = False
            for _ in range(160):
                await asyncio.sleep(1)
                current_url = page.url

                # 二维码消失 + 没登录成功 = 需要验证 → 恢复浏览器
                if not _verify_restored:
                    qr_still = False
                    try:
                        qr_still = await page.locator('img[aria-label="二维码"]').first.count() > 0
                    except Exception:
                        pass
                    if not qr_still and not current_url.startswith("https://creator.douyin.com/creator-micro/home"):
                        _clog.info(f"验证/跳转页，恢复浏览器: {current_url}")
                        try:
                            cdp = await page.context.new_cdp_session(page)
                            win_info = await cdp.send("Browser.getWindowForTarget")
                            wid = win_info.get("windowId")
                            if wid:
                                await cdp.send("Browser.setWindowBounds", {
                                    "windowId": wid,
                                    "bounds": {"windowState": "normal"}
                                })
                        except Exception:
                            pass
                        _verify_restored = True

                # 判断是否登录成功：URL 变成创作者中心首页，且没有登录元素
                if current_url.startswith("https://creator.douyin.com/creator-micro/home"):
                    # 进一步确认没有登录表单
                    try:
                        still_login = await page.get_by_text("扫码登录", exact=True).first.is_visible()
                    except Exception:
                        still_login = False
                    if not still_login:
                        # 在 creator.douyin.com 提取 localStorage (IM protobuf 必需)
                        import logging
                        _clog = logging.getLogger("cookie_reader")
                        web_protect = ""
                        keys_val = ""
                        try:
                            # keys: 从 security-sdk 获取 ec_privateKey
                            crypt_raw = await page.evaluate(
                                "() => localStorage.getItem('security-sdk/s_sdk_crypt_sdk')"
                            ) or ""
                            if crypt_raw:
                                keys_val = crypt_raw  # 格式: {"data": "{\"ec_privateKey\": \"...\"}"}

                            # web_protect: 扫描 localStorage security-sdk key
                            all_keys = await page.evaluate("() => Object.keys(localStorage)")
                            _clog.debug(f"localStorage keys: {all_keys}")
                            web_protect = ""
                            keys_val = ""
                            # 方法1: dump 所有 security-sdk 系 key 的值（诊断用）
                            for k in all_keys:
                                if "security-sdk" in k or "sdk_sign" in k:
                                    v = await page.evaluate(f"() => localStorage.getItem('{k}')") or ""
                                    _clog.info(f"[{k}] len={len(v)}, preview={v[:300]}")
                                    if v and '"ticket"' in v:
                                        web_protect = v
                                        _clog.info(f"web_protect found in {k}")
                                        break
                            # 方法2: 扫描所有 key
                            if not web_protect:
                                for k in all_keys:
                                    v = await page.evaluate(f"() => localStorage.getItem('{k}')") or ""
                                    if v and '"ticket"' in v and '"ts_sign"' in v:
                                        web_protect = v
                                        _clog.info(f"web_protect found in key: {k}")
                                        break
                            # 方法3: 从 ztsdk_tcc_config 构建
                            if not web_protect:
                                tcc_raw = await page.evaluate(
                                    "() => localStorage.getItem('ztsdk_tcc_config')"
                                ) or ""
                                if tcc_raw:
                                    _clog.info(f"ztsdk_tcc_config: {tcc_raw[:300]}")
                                    import json
                                    try:
                                        tcc = json.loads(tcc_raw)
                                        cfg = tcc.get("value", {}).get("ztsdk_config", {})
                                        _clog.info(f"ztsdk_config keys: {list(cfg.keys())}")
                                        for items in cfg.values():
                                            for item in items if isinstance(items, list) else []:
                                                scene = item.get("scene", "")
                                                _clog.info(f"ztsdk scene: {scene}")
                                                if scene == "web_protect":
                                                    # certType=cookie → ticket 在 cookie 里，稍后在 douyin.com 提取
                                                    wp_data = {
                                                        "ticket": item.get("ticket", item.get("token", "")),
                                                        "ts_sign": item.get("ts_sign", ""),
                                                        "client_cert": item.get("client_cert", item.get("cert", "")),
                                                    }
                                                    if wp_data["ticket"]:
                                                        web_protect = json.dumps({"data": json.dumps(wp_data)})
                                                    break
                                    except Exception:
                                        pass
                            if not web_protect:
                                _clog.info("web_protect 未在 localStorage，将尝试 cookie 提取")
                        except Exception:
                            pass

                        # 补充访问 www.douyin.com 获取 s_v_web_id + ticket cookie
                        try:
                            await page.goto("https://www.douyin.com/", timeout=30000, wait_until="domcontentloaded")
                            await asyncio.sleep(3)  # 等 SDK 初始化完
                        except Exception:
                            pass
                        cookies = await context.cookies()
                        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

                        # douyin 新版将 web_protect 数据存于 _bd_ticket_crypt_cookie
                        if not web_protect:
                            import json as _json
                            for c in cookies:
                                if c.get("name") == "_bd_ticket_crypt_cookie" and c.get("value"):
                                    wp_data = {"ticket": c["value"], "ts_sign": "", "client_cert": ""}
                                    web_protect = _json.dumps({"data": _json.dumps(wp_data)})
                                    _clog.info("web_protect extracted from _bd_ticket_crypt_cookie")
                                    break
                                    break
                        if not web_protect:
                            _clog.warning("ticket 仍为空，所有来源均未找到")

                        await browser.close()
                        return {
                            "cookie": cookie_str,
                            "web_protect": web_protect,
                            "keys": keys_val,
                        }

                # 二维码过期 → 刷新
                try:
                    expired = page.get_by_text("二维码失效", exact=True).locator("..").first
                    if await expired.count() and await expired.is_visible():
                        await expired.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass

            await browser.close()
            return None
    except Exception:
        return None


async def _login_bilibili(account_file: str, on_qr_callback=None) -> Optional[str]:
    """B站扫码登录，返回 cookie 字符串。on_qr_callback(base64_data_url) 收到二维码时调用"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()

            await page.goto("https://www.bilibili.com/", timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            login_selectors = [
                ".header-login-entry",
                ".right-entry__outside .header-login-entry",
                "[class*='login-btn']",
                "text=登录",
            ]
            for sel in login_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=3000):
                        await btn.click()
                        await asyncio.sleep(3)
                        # ── 提取 B站登录弹窗中的二维码 ──
                        try:
                            qr_canvas = page.locator(".bili-mini-login-wrapper canvas, .login-qrcode canvas, .bili-mini-login-wrapper img, .login-qrcode img").first
                            if await qr_canvas.count() > 0:
                                qr_bytes = await qr_canvas.screenshot(type="png")
                                qr_b64 = "data:image/png;base64," + base64.b64encode(qr_bytes).decode()
                                if on_qr_callback:
                                    on_qr_callback(qr_b64)
                                # ── 二维码已显示在 GUI，现在最小化浏览器 ──
                                try:
                                    cdp = await page.context.new_cdp_session(page)
                                    win_info = await cdp.send("Browser.getWindowForTarget")
                                    wid = win_info.get("windowId")
                                    if wid:
                                        await cdp.send("Browser.setWindowBounds", {
                                            "windowId": wid,
                                            "bounds": {"windowState": "minimized"}
                                        })
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        break
                except Exception:
                    continue

            for _ in range(90):
                await asyncio.sleep(2)
                cookies = await context.cookies()
                sessdata_cookie = next((c for c in cookies if c.get("name") == "SESSDATA"), None)
                if sessdata_cookie and sessdata_cookie.get("value"):
                    await asyncio.sleep(1)
                    cookies = await context.cookies()
                    await browser.close()
                    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)

            await browser.close()
            return None
    except Exception:
        return None


def _run_async(coro):
    """在 QThread 中安全运行 async 函数（创建独立事件循环）"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_tempfile() -> str:
    """创建临时文件并返回路径（调用者负责清理）"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        return f.name


def _cleanup_tempfile(tmp: str):
    """安全删除临时文件"""
    try:
        Path(tmp).unlink(missing_ok=True)
    except Exception:
        pass


def extract_douyin_cookies_sync(on_qr_callback=None) -> dict:
    """同步封装：抖音扫码登录，返回 {cookie, web_protect, keys} 或 {}"""
    tmp = _make_tempfile()
    try:
        result = _run_async(_login_douyin(tmp, on_qr_callback=on_qr_callback))
        return result or {}
    except Exception:
        return {}
    finally:
        _cleanup_tempfile(tmp)


def extract_bilibili_cookies_sync(on_qr_callback=None) -> dict:
    """同步封装：B站扫码登录
    
    返回 {"SESSDATA", "bili_jct", "buvid3", "buvid4", "dedeuserid", "ac_time_value"}
    bilibili-api-python 17.4+ 需要这些额外字段，否则 API 返回 -400
    """
    tmp = _make_tempfile()
    try:
        raw = _run_async(_login_bilibili(tmp, on_qr_callback=on_qr_callback))
    except Exception:
        raw = ""
    finally:
        _cleanup_tempfile(tmp)
    # 需要提取的 cookie 字段。B站浏览器端大小写不一致（如 DedeUserID vs dedeuserid），
    # 统一用小写匹配再映射回原始 key。
    cookie_keys = ["SESSDATA", "bili_jct", "buvid3", "buvid4", "dedeuserid", "ac_time_value"]
    key_lower_map = {k.lower(): k for k in cookie_keys}
    result = {k: "" for k in cookie_keys}
    if raw:
        for part in raw.split("; "):
            if "=" in part:
                k, v = part.split("=", 1)
                key_lower = k.strip().lower()
                if key_lower in key_lower_map:
                    result[key_lower_map[key_lower]] = v
    return result


async def _login_xiaohongshu(account_file: str, on_qr_callback=None) -> Optional[str]:
    """小红书 Playwright 浏览器扫码登录

    1. Playwright 打开 creator.xiaohongshu.com/login（创作者登录页）
    2. 提取页面二维码 → GUI 弹窗显示
    3. 等用户扫码 → 检测登录 → 再导航 www 补全 cookie → 保存

    on_qr_callback(png_bytes): 收到二维码 PNG 字节数据用于 GUI 显示
    """
    _clog = logging.getLogger("cookie_reader")

    def _safe_callback(value):
        if on_qr_callback:
            try: on_qr_callback(value)
            except Exception: pass

    async def _minimize():
        try:
            bs = await browser.new_browser_cdp_session()
            t = await bs.send('Browser.getWindowForTarget', {
                'targetId': (await page.context.new_cdp_session(page)
                             .send('Target.getTargetInfo'))['targetInfo']['targetId']
            })
            await bs.send('Browser.setWindowBounds', {
                'windowId': t['windowId'],
                'bounds': {'windowState': 'minimized'}
            })
            bs.detach()
        except Exception: pass

    try:
        from playwright.async_api import async_playwright
        import base64 as _b64
    except ImportError:
        _clog.error("XHS login: Playwright not installed")
        return None

    try:
        async with async_playwright() as p:
            _clog.info("XHS login: launching browser...")
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()

            # ── 打开创作者登录页 ──
            await page.goto(
                "https://creator.xiaohongshu.com/login",
                timeout=60000, wait_until="domcontentloaded",
            )
            await asyncio.sleep(2)

            # ── 切换到扫码登录 ──
            try:
                login_box = page.locator("div[class*='login-box']").first
                if await login_box.count():
                    switch = login_box.locator("div:has-text('扫一扫')").first
                    if not await switch.count():
                        imgs = login_box.locator("img")
                        if await imgs.count() >= 2:
                            await imgs.nth(1).click()
                            await asyncio.sleep(1)
            except Exception:
                pass

            # ── 提取二维码 ──
            qrcode_src = ""
            try:
                container = page.locator("div[class*='login-box']").first
                imgs = (container if await container.count() else page).locator("img")
                for i in range(await imgs.count()):
                    src = (await imgs.nth(i).get_attribute("src")) or ""
                    if src.startswith("data:image/"):
                        qrcode_src = src; break
                if not qrcode_src:
                    for i in range(await page.locator("img").count()):
                        src = (await page.locator("img").nth(i).get_attribute("src")) or ""
                        if src.startswith("data:image/") and len(src) > 5000:
                            qrcode_src = src; break
            except Exception:
                pass

            qr_png = None
            if qrcode_src:
                try:
                    qr_png = _b64.b64decode(qrcode_src.split(",", 1)[1])
                except Exception: pass
            if qr_png:
                _clog.info(f"QR extracted ({len(qr_png)} bytes)")
                _safe_callback(qr_png)
            else:
                _clog.warning("QR extract failed")
                _safe_callback(None)

            # ── 等待登录 ──
            _clog.info("waiting for scan...")
            for _ in range(120):
                await asyncio.sleep(2)
                current_url = page.url
                if "creator.xiaohongshu.com" in current_url and "/login" not in current_url:
                    try:
                        avatar = page.locator("[class*=avatar]").first
                        if await avatar.count() and await avatar.is_visible():
                            _dbg("creator login OK")
                            # 导航 www 补全 Cookie
                            try:
                                await page.goto(
                                    "https://www.xiaohongshu.com/",
                                    timeout=20000, wait_until="domcontentloaded",
                                )
                                await asyncio.sleep(4)
                                await _minimize()
                            except Exception:
                                await _minimize()

                            all_cookies = await context.cookies()
                            cookie_str = "; ".join(
                                f"{c['name']}={c['value']}" for c in all_cookies
                            )
                            cookie_path = Path(__file__).parent.parent / "data" / "xhs_cookie.txt"
                            cookie_path.parent.mkdir(parents=True, exist_ok=True)
                            cookie_path.write_text(cookie_str, encoding="utf-8")
                            _clog.info(f"XHS done: {len(all_cookies)} cookies")
                            await browser.close()
                            return cookie_str
                    except Exception: pass

            await browser.close()
            _clog.warning("XHS login: timeout")
            return None
    except Exception as e:
        _clog.error(f"XHS login failed: {e}")
        return None


def extract_xiaohongshu_cookies_sync(on_qr_callback=None) -> str:
    """同步封装：小红书 Playwright 扫码登录，返回 cookie 字符串或空"""
    tmp = _make_tempfile()
    try:
        result = _run_async(_login_xiaohongshu(tmp, on_qr_callback=on_qr_callback))
        return result or ""
    except Exception:
        return ""
    finally:
        _cleanup_tempfile(tmp)
