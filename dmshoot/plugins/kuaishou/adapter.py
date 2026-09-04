"""快手私信适配器 — Playwright 扫码登录 + HTTP API 收发

快手 Web 端私信走标准 HTTP + Cookie，无需签名。
登录通过 Playwright 打开 live.kuaishou.com 扫码获取 Cookie。
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from dmshoot.core.adapter import BaseAdapter, ErrorCategory
from dmshoot.core.message import Message
from dmshoot.utils.console_log import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
STATE_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "kuaishou_state.json"
COOKIE_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "kuaishou_cookie.json"
DEBUG_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "kuaishou_debug.txt"

# ── 持久化 ──

def _debug(msg: str):
    try:
        with open(str(DEBUG_FILE), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] [KS] {msg}\n")
    except:
        pass


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"replied": []}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _load_cookie() -> dict[str, str]:
    """加载 Cookie"""
    if COOKIE_FILE.exists():
        try:
            return json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    # 兜底：数据库配置
    try:
        from dmshoot.storage import database
        cfg = database.load_config()
        if cfg.ks_cookie:
            return cfg.ks_cookie if isinstance(cfg.ks_cookie, dict) else {}
    except Exception:
        pass
    return {}


def _save_cookie(cookies: dict[str, str]):
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")


def _parse_timestamp(ts) -> float:
    if isinstance(ts, str):
        try: ts = float(ts)
        except: return 0
    if isinstance(ts, (int, float)):
        if ts > 1e12: return ts / 1000
        if ts > 1e9: return ts
    return 0


# ── Playwright 登录 ──

async def login_via_playwright(callback=None) -> dict[str, str]:
    """打开浏览器让用户扫码登录快手，返回 Cookie 字典。

    Returns:
        dict of cookie name -> value
    Raises:
        TimeoutError: 超时未登录
        RuntimeError: 其他错误
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            # 打开快手首页
            await page.goto("https://www.kuaishou.com", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            # 尝试自动点击登录按钮触发二维码
            try:
                login_btn = page.locator('span:has-text("登录")').first
                if not await login_btn.count():
                    login_btn = page.locator('button:has-text("登录")').first
                if await login_btn.count():
                    await login_btn.click()
                    await page.wait_for_timeout(3000)
            except:
                pass

            if callback:
                callback("请在浏览器中用快手 App 扫码登录")

            # 等待登录完成：检测 userId Cookie 出现
            logged_in = False
            for _ in range(180):
                await page.wait_for_timeout(1000)
                try:
                    cookies = await context.cookies()
                    names = {c["name"] for c in cookies}
                    # 登录成功的明确标志：出现 userId
                    if "userId" in names and len(cookies) >= 8:
                        if callback:
                            callback(f"检测到登录（{len(cookies)}个 Cookie）")
                        logged_in = True
                        break
                except:
                    pass

            if not logged_in:
                raise TimeoutError("登录超时（180 秒）")

            if callback:
                callback("登录成功，正在提取信息...")

            # 提取昵称
            user_name = ""
            try:
                await page.goto(f"https://www.kuaishou.com/profile/{cookies[0].get('value','')}", 
                               wait_until="domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)
                # 尝试从页面提取昵称
                name_el = await page.query_selector('[class*="profile-name"], [class*="userName"], [class*="name"], h1, h2')
                if name_el:
                    text = await name_el.text_content()
                    if text and len(text.strip()) < 50:
                        user_name = text.strip()
                avatar_el = await page.query_selector(
                    'meta[property="og:image"], img[class*="avatar"], img[class*="Avatar"]'
                )
                if avatar_el:
                    my_avatar = await avatar_el.get_attribute("content")
                    if not my_avatar:
                        my_avatar = await avatar_el.get_attribute("src")
                else:
                    my_avatar = ""
            except:
                my_avatar = ""

            # 同时访问 live.kuaishou.com 获取直播域 Cookie
            page2 = await context.new_page()
            try:
                await page2.goto("https://live.kuaishou.com", wait_until="domcontentloaded", timeout=15000)
                await page2.wait_for_timeout(3000)
            except:
                pass
            await page2.close()

            # 提取所有 Cookie
            cookies = await context.cookies()
            cookie_dict = {}
            for c in cookies:
                domain = c.get("domain", "")
                if "kuaishou.com" in domain or "yximgs.com" in domain:
                    cookie_dict[c["name"]] = c["value"]
            # 保存昵称
            cookie_dict["_user_name"] = user_name or ""
            cookie_dict["_user_avatar"] = my_avatar or ""

            _debug(f"login_via_playwright: {len(cookie_dict)} cookies")
            if not cookie_dict:
                raise RuntimeError("未找到快手域名 Cookie")

            _save_cookie(cookie_dict)
            return cookie_dict

        finally:
            await browser.close()


# ── 适配器 ──

class KuaishouAdapter(BaseAdapter):
    platform_name = "kuaishou"
    _im_unavailable = True  # Web 端不支持私信，跳过启动横幅

    BASE_URL = "https://www.kuaishou.com"

    def __init__(self, ks_cookie: dict = None, bus=None):
        super().__init__(bus)
        self._cookie = ks_cookie or _load_cookie()
        self._client: Optional[httpx.AsyncClient] = None
        self._my_uid: str = ""
        self._my_name: str = ""
        self._my_avatar: str = ""
        self._state = _load_state()
        self._replied: set[str] = set(self._state.get("replied", []))
        self._user_cache: dict[str, tuple[str, str]] = {}

    def _cookie_str(self) -> str:
        """Cookie dict → header string"""
        return "; ".join(f"{k}={v}" for k, v in self._cookie.items())

    async def _request(self, method: str, path: str,
                       json_data: dict = None, params: dict = None) -> Optional[dict]:
        """统一的 HTTP 请求"""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30, follow_redirects=False)
        url = f"{self.BASE_URL}{path}"
        headers = {
            "Cookie": self._cookie_str(),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.kuaishou.com/",
            "Origin": "https://www.kuaishou.com",
            "Content-Type": "application/json",
        }
        try:
            resp = await self._client.request(
                method, url, json=json_data, params=params, headers=headers,
            )
            # 302 表示未登录
            if resp.status_code in (302, 301):
                return {"error": "not_logged_in", "status": resp.status_code}
            return resp.json()
        except Exception as e:
            _debug(f"request {method} {path}: {e}")
            return None

    # ── 生命周期 ──

    def connect(self) -> bool:
        """同步入口——内部调异步"""
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self._connect_async())
        finally:
            loop.close()
        return result

    async def _connect_async(self) -> bool:
        _debug("connect: start")
        if not self._cookie:
            _debug("connect: no cookie")
            logger.warning("快手未登录，请先扫码获取 Cookie")
            return False

        # 从 Cookie 中直接读取 userId
        uid = self._cookie.get("userId", "")
        if not uid:
            _debug("connect: no userId in cookie")
            logger.error("快手 Cookie 中未找到 userId，请重新扫码")
            return False

        self._my_uid = uid
        self._my_name = self._cookie.get("_user_name", "") or f"快手用户{uid}"
        self._my_avatar = self._cookie.get("_user_avatar", "") or ""

        _debug(f"connect OK: uid={self._my_uid}")
        logger.success(f"快手已连接: {self._my_name}({self._my_uid})")
        logger.warning("快手 Web 端不支持私信收发（仅限移动端）")
        return True

    def disconnect(self):
        self._state["replied"] = list(self._replied)[-5000:]
        _save_state(self._state)

    # ── 发送（Web 端不支持）──

    def send_message(self, session_id: str, text: str) -> bool:
        return False

    # ── 轮询（Web 端不支持）──

    def _poll_messages(self):
        time.sleep(10)


# ── 简便函数 ──

def kuaishou_login() -> dict[str, str]:
    """打开浏览器扫码登录快手，返回 Cookie 字典。
    
    用法:
        cookies = kuaishou_login()
        adapter = KuaishouAdapter(ks_cookie=cookies)
        adapter.connect()
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(login_via_playwright())
    finally:
        loop.close()
