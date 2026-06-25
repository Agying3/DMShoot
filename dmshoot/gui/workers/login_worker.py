"""登录 Cookie 提取工作线程 — 从 login_page._CookieWorker 提取"""

import os
import subprocess
import json

from PySide6.QtCore import QThread, Signal


class LoginWorker(QThread):
    """通过 Playwright 浏览器运行扫码登录流程，提取平台 Cookie。
    支持抖音、B站、快手、小红书四个平台。"""
    result = Signal(str, object)       # (platform, cookies_dict_or_None)
    xhs_qr_ready = Signal(object)      # 小红书二维码 PNG bytes
    dy_qr_ready = Signal(object)       # 抖音二维码 base64
    bili_qr_ready = Signal(object)     # B站二维码 base64

    def __init__(self, platform: str):
        super().__init__()
        self.platform = platform

    def run(self):
        try:
            from dmshoot.utils.cookie_reader import (
                extract_douyin_cookies_sync, extract_bilibili_cookies_sync,
                extract_xiaohongshu_cookies_sync
            )
            if self.platform == "douyin":
                result = extract_douyin_cookies_sync(
                    on_qr_callback=lambda b64: self.dy_qr_ready.emit(b64),
                )
                self.result.emit(self.platform, result if (result and result.get("cookie")) else None)
            elif self.platform == "bilibili":
                c = extract_bilibili_cookies_sync(
                    on_qr_callback=lambda b64: self.bili_qr_ready.emit(b64)
                )
                self.result.emit(self.platform, c if (c and c.get("SESSDATA")) else None)
            elif self.platform == "kuaishou":
                import asyncio
                output_file = os.path.join(
                    os.path.dirname(__file__), "..", "..", "data", "ks_cookie_tmp.json"
                )
                output_file = os.path.abspath(output_file)

                venv_python = r"H:\DMShoot\.venv\Scripts\python.exe"
                login_script = r"""
import asyncio, json, sys, traceback
sys.path.insert(0, "H:\\DMShoot")
try:
    from dmshoot.plugins.kuaishou.adapter import login_via_playwright
    async def main():
        cookies = await login_via_playwright()
        if cookies:
            with open(sys.argv[1], "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False)
    asyncio.run(main())
except Exception as e:
    print(f"LOGIN_ERROR: {e}", flush=True)
    traceback.print_exc()
"""

                proc = subprocess.run(
                    [venv_python, "-c", login_script, output_file],
                    capture_output=True, text=True, timeout=300,
                )
                if proc.stdout:
                    for line in proc.stdout.strip().split('\n')[-5:]:
                        print(f"[KS Login] {line}", flush=True)
                if proc.stderr:
                    for line in proc.stderr.strip().split('\n')[-10:]:
                        print(f"[KS Login ERR] {line}", flush=True)

                if os.path.exists(output_file) and os.path.getsize(output_file) > 100:
                    with open(output_file, "r", encoding="utf-8") as f:
                        cookies = json.load(f)
                    os.remove(output_file)
                    self.result.emit(self.platform, cookies if cookies else None)
                else:
                    print(f"[KS Login] No cookie file or too small", flush=True)
                    self.result.emit(self.platform, None)
            elif self.platform == "xiaohongshu":
                cookie = extract_xiaohongshu_cookies_sync(
                    on_qr_callback=lambda png: self.xhs_qr_ready.emit(png)
                )
                self.result.emit(self.platform, cookie if cookie else None)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.result.emit(self.platform, None)

    def stop(self):
        """强制终止线程。
        
        注意: 必须用 terminate() 而非 quit()，因为 run() 里是 asyncio.run() 同步阻塞调用，
        不是 Qt 事件循环。quit() 对阻塞线程无效，会导致旧平台的 Playwright 浏览器窗口残留，
        切换到其他平台登录时两个窗口同时存在。
        """
        if self.isRunning():
            self.terminate()
            self.wait(3000)
