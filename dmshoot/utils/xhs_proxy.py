"""小红书 API 代理 — 通过 Playwright 无头浏览器转发请求，绕过签名"""

import json
import asyncio
from pathlib import Path
from typing import Optional

from dmshoot.utils.console_log import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
STATE_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "xhs_browser_state.json"


class XHSProxy:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def is_logged_in(self) -> bool:
        return STATE_FILE.exists()

    def save_state_json(self, state_data: dict):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state_data), encoding="utf-8")

    async def start(self):
        try:
            from playwright.async_api import async_playwright

            logger.info("XHS代理: 启动无头浏览器...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=False,  # 有头模式避免检测
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                ],
            )

            if STATE_FILE.exists():
                state_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            else:
                state_data = {}
            # 兼容新旧格式
            if "storage_state" in state_data:
                storage_state = state_data["storage_state"]
                self._local_data = state_data.get("localStorage", {})
            else:
                storage_state = state_data
                self._local_data = {}

            self._context = await self._browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 720},
            )
            self._page = await self._context.new_page()

            # 注入 localStorage（先于导航，确保 JS 初始化时就能读到）
            if self._local_data:
                items_js = json.dumps(self._local_data)
                # 先用 about:blank 注入，再导航到目标页面
                await self._page.goto("about:blank")
                await self._page.evaluate(f"""
                    () => {{
                        const data = {items_js};
                        for (const [k, v] of Object.entries(data)) {{
                            try {{ localStorage.setItem(k, v); }} catch(e) {{}}
                        }}
                    }}
                """)
                logger.info(f"XHS代理: 注入 {len(self._local_data)} 个 localStorage key")

            # 导航到 creator 域，等 XHS JS 完全加载（含签名拦截器）
            await self._page.goto(
                "https://creator.xiaohongshu.com/",
                wait_until="networkidle",
                timeout=60000,
            )
            await asyncio.sleep(3)

            self._ready = True
            logger.success("XHS代理: 浏览器就绪")
        except Exception as e:
            logger.error(f"XHS代理启动失败: {e}")

    async def fetch(self, url: str, method: str = "GET",
                     json_data: dict = None, params: dict = None) -> Optional[dict]:
        if not self._ready or not self._page:
            logger.warning(f"XHS fetch 跳过: ready={self._ready}")
            return None

        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}" if params else url

        body_js = json.dumps(json_data) if json_data else "null"

        js = f"""
        async () => {{
            const body = {body_js};
            const opts = {{
                method: '{method}',
                credentials: 'include',
                headers: {{ 'Content-Type': 'application/json' }},
            }};
            if (body) opts.body = JSON.stringify(body);
            try {{
                const r = await fetch({json.dumps(full_url)}, opts);
                const t = await r.text();
                return JSON.stringify({{ s: r.status, b: t }});
            }} catch(e) {{
                return JSON.stringify({{ s: 0, e: String(e) }});
            }}
        }}
        """
        try:
            raw = await self._page.evaluate(js)
            data = json.loads(raw)
            if data.get("s") == 0:
                logger.warning(f"XHS fetch JS err: {data.get('e', '')}")
                return None
            try:
                body = json.loads(data["b"])
            except:
                body = data["b"]
            return {"status": data["s"], "body": body}
        except Exception as e:
            logger.error(f"XHS fetch异常: {e}")
            return None

    async def stop(self):
        self._ready = False
        try:
            if self._page:
                await self._page.close()
        except:
            pass
        try:
            if self._context:
                await self._context.close()
        except:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except:
            pass
