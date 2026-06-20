"""小红书创作者平台 — 扫码登录模块

纯 HTTP 方案，无需 Playwright。
基于 Spider_XHS (cv-cat) 的 QR 登录流程。

流程: 生成初始 cookies → 获取反爬 cookie → 请求二维码 → 轮询扫码状态 → 获取完整 cookie
"""

import json
import time
import random
import hashlib
import binascii
from pathlib import Path
from typing import Optional

import requests

_STATIC_DIR = Path(__file__).parent / "static"


# ── Cookie 工具 ──

def _cookies_to_str(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _cookies_to_requests(cookies: dict) -> dict:
    """转为 requests 库可用的 cookie dict (只保留 key=value)"""
    return {k: v for k, v in cookies.items()}


# ── a1 / web_id 生成 (纯 Python) ──

def generate_a1() -> str:
    """生成 XHS a1 cookie (设备追踪标识)"""
    ts_hex = hex(int(time.time() * 1000))[2:]
    random_str = ''.join(random.choices(
        'abcdefghijklmnopqrstuvwxyz1234567890', k=30
    ))
    a_part = ts_hex + random_str + '5' + '0' + '000'
    crc = binascii.crc32(a_part.encode()) & 0xFFFFFFFF
    return (a_part + str(crc))[:52]


def generate_web_id(a1: str) -> str:
    """webId = MD5(a1)"""
    return hashlib.md5(a1.encode()).hexdigest()


# ── HTTP 工具 ──

def _get_login_headers() -> dict:
    return {
        'user-agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/147.0.0.0 Safari/537.36'
        ),
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'sec-ch-ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'origin': 'https://creator.xiaohongshu.com',
        'referer': 'https://creator.xiaohongshu.com/',
        'authorization': '',
    }


def _generate_xsc_headers(a1: str, api: str, data=None, method: str = 'POST') -> dict:
    """生成签名头 (复用 sign 模块)"""
    from dmshoot.plugins.xiaohongshu.sign import generate_xsc
    data_str = ""
    if data:
        data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return generate_xsc(a1, api, data_str)


# ── 反爬 Cookie 获取 ──

def _fetch_sec_cookies(cookies: dict) -> dict:
    """获取 websectiga 和 sec_poison_id (需要 xhs_websectiga_env.js)"""
    cookies = dict(cookies)
    api = '/api/sec/v1/scripting'
    data = {"callFrom": "web", "callback": "seccallback"}

    headers = _get_login_headers()
    headers['content-type'] = 'application/json;charset=UTF-8'
    sign_h = _generate_xsc_headers(cookies['a1'], api, data)
    headers.update(sign_h)

    data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    try:
        resp = requests.post(
            'https://as.xiaohongshu.com' + api,
            headers=headers, cookies=cookies,
            data=data_str.encode('utf-8'), timeout=15,
        )
        res = resp.json()
        sec_poison_id = res.get('data', {}).get('secPoisonId')
        if sec_poison_id:
            cookies['sec_poison_id'] = sec_poison_id

        # 执行 websectiga JSVMP 代码
        jsvmp_code = res.get('data', {}).get('data', '')
        if jsvmp_code:
            env_path = _STATIC_DIR / 'xhs_websectiga_env.js'
            if env_path.exists():
                import subprocess, tempfile
                env_js = env_path.read_text(encoding='utf-8')
                combined = (
                    f"{env_js}\n"
                    f"{jsvmp_code}\n"
                    f"var __result = _websectiga_result;\n"
                    f"console.log(JSON.stringify(__result));"
                )
                tmp = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.js', delete=False,
                    dir=str(_STATIC_DIR), encoding='utf-8',
                )
                try:
                    tmp.write(combined)
                    tmp.close()
                    # 复用 sign 模块的 node 路径查找
                    from dmshoot.plugins.xiaohongshu.sign import _NODE_PATH
                    r = subprocess.run(
                        [_NODE_PATH, tmp.name],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        websectiga = json.loads(r.stdout.strip().split('\n')[-1])
                        if websectiga:
                            cookies['websectiga'] = websectiga
                finally:
                    try:
                        Path(tmp.name).unlink(missing_ok=True)
                    except:
                        pass
    except Exception:
        pass

    return cookies


def _fetch_gid(cookies: dict) -> dict:
    """获取 gid cookie"""
    cookies = dict(cookies)
    api = '/api/sec/v1/shield/webprofile'
    data = {
        "platform": "Windows",
        "sdkVersion": "4.3.5",
        "svn": "2",
        "profileData": ""
    }

    headers = _get_login_headers()
    headers['content-type'] = 'application/json'
    sign_h = _generate_xsc_headers(cookies['a1'], api, data)
    headers.update(sign_h)

    data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    try:
        resp = requests.post(
            'https://as.xiaohongshu.com' + api,
            headers=headers, cookies=cookies,
            data=data_str.encode('utf-8'), timeout=15,
        )
        for key, value in resp.cookies.items():
            cookies[key] = value
    except Exception:
        pass

    return cookies


# ── 登录流程 ──

def generate_init_cookies() -> dict:
    """生成初始 cookies (a1, webId, 反爬 cookies)"""
    ts = int(time.time() * 1000)
    a1 = generate_a1()
    web_id = generate_web_id(a1)

    cookies = {
        'ets': str(ts),
        'xsecappid': 'ugc',
        'loadts': str(ts + random.randint(50, 200)),
        'a1': a1,
        'webId': web_id,
    }

    # 访问登录页获取初始 cookie
    headers = {
        'user-agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/147.0.0.0 Safari/537.36'
        ),
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'accept-language': 'zh-CN,zh;q=0.9',
    }
    try:
        resp = requests.get(
            'https://creator.xiaohongshu.com/login',
            headers=headers, cookies=cookies,
            allow_redirects=False, timeout=15,
        )
        for key, value in resp.cookies.items():
            cookies[key] = value
    except Exception:
        pass

    # 获取反爬 cookies
    cookies = _fetch_sec_cookies(cookies)
    cookies = _fetch_gid(cookies)

    return cookies


def generate_qrcode(cookies: dict) -> Optional[dict]:
    """请求二维码，返回 {qr_id, qr_url} 或 None"""
    api = '/api/cas/customer/web/qr-code'
    data = {"service": "https://creator.xiaohongshu.com"}

    headers = _get_login_headers()
    headers['content-type'] = 'application/json'
    sign_h = _generate_xsc_headers(cookies['a1'], api, data)
    headers.update(sign_h)

    data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    try:
        resp = requests.post(
            'https://customer.xiaohongshu.com' + api,
            headers=headers, cookies=cookies,
            data=data_str.encode('utf-8'), timeout=15,
        )
        for key, value in resp.cookies.items():
            cookies[key] = value

        res = resp.json()
        if not res.get('success'):
            return None
        data = res.get('data') or {}
        return {
            'qr_id': data.get('id', ''),
            'qr_url': data.get('url', ''),
        }
    except Exception:
        return None


def check_session(cookies: dict) -> bool:
    """检查是否已有有效 session"""
    api = '/api/cas/customer/web/service-ticket'
    data = {"service": "https://creator.xiaohongshu.com", "source": "", "type": "tgt"}

    headers = _get_login_headers()
    headers['content-type'] = 'application/json'
    sign_h = _generate_xsc_headers(cookies['a1'], api, data)
    headers.update(sign_h)

    data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    try:
        resp = requests.post(
            'https://customer.xiaohongshu.com' + api,
            headers=headers, cookies=cookies,
            data=data_str.encode('utf-8'), timeout=15,
        )
        for key, value in resp.cookies.items():
            cookies[key] = value
        return resp.json().get('data') is not None
    except Exception:
        return False


def check_qrcode_status(qr_id: str, cookies: dict) -> tuple[bool, str, dict]:
    """轮询二维码状态。返回 (已完成, 状态描述, cookies)"""
    api = '/api/cas/customer/web/qr-code'
    params = {
        'service': 'https://creator.xiaohongshu.com',
        'qr_code_id': qr_id,
        'source': '',
    }
    from urllib.parse import urlencode
    splice_api = f"{api}?{urlencode(params)}"

    headers = _get_login_headers()
    sign_h = _generate_xsc_headers(cookies['a1'], splice_api)
    headers.update(sign_h)

    try:
        resp = requests.get(
            'https://customer.xiaohongshu.com' + splice_api,
            headers=headers, cookies=cookies, timeout=15,
        )
        for key, value in resp.cookies.items():
            cookies[key] = value

        res = resp.json()
        status = (res.get('data') or {}).get('status')

        status_map = {
            1: (True, '验证成功'),
            2: (False, '请扫描二维码'),
            3: (False, '请确认登录'),
            -1: (False, '二维码已过期'),
        }
        return status_map.get(status, (False, f'未知状态: {status}'))[0:2] + (cookies,)
    except Exception:
        return False, '网络错误', cookies


def verify_login(cookies: dict) -> tuple[bool, dict, dict]:
    """验证登录并获取用户信息"""
    api = '/api/galaxy/user/info'

    headers = _get_login_headers()
    headers['sec-fetch-site'] = 'same-origin'
    sign_h = _generate_xsc_headers(cookies['a1'], api)
    headers.update(sign_h)

    try:
        resp = requests.get(
            'https://creator.xiaohongshu.com' + api,
            headers=headers, cookies=cookies, timeout=15,
        )
        for key, value in resp.cookies.items():
            cookies[key] = value

        res = resp.json()
        return res.get('success', False), res.get('data', {}), cookies
    except Exception:
        return False, {}, cookies


# ── 主入口 ──

class XHSLoginResult:
    """登录结果"""
    def __init__(self, success: bool, cookie_str: str = "",
                 user_info: dict = None, error: str = ""):
        self.success = success
        self.cookie_str = cookie_str
        self.user_info = user_info or {}
        self.error = error


def qrcode_login_step1() -> tuple[dict, Optional[dict]]:
    """扫码登录第1步：生成 cookies 并获取二维码

    Returns:
        (cookies, qr_data) — qr_data 含 {'qr_id', 'qr_url'}, None 表示失败
    """
    try:
        cookies = generate_init_cookies()

        # 检查是否有已有 session
        check_session(cookies)

        qr_data = generate_qrcode(cookies)
        if not qr_data:
            return cookies, None

        return cookies, qr_data
    except Exception:
        return {}, None


def qrcode_login_step2(qr_id: str, cookies: dict) -> tuple[bool, str, dict]:
    """扫码登录第2步：检查二维码状态 (可反复调用)

    Returns:
        (已完成, 状态描述, cookies)
    """
    return check_qrcode_status(qr_id, cookies)


def qrcode_login_step3(cookies: dict) -> XHSLoginResult:
    """扫码登录第3步：验证登录，获取最终 Cookie

    Returns:
        XHSLoginResult
    """
    try:
        success, user_info, cookies = verify_login(cookies)
        if success:
            return XHSLoginResult(
                success=True,
                cookie_str=_cookies_to_str(cookies),
                user_info=user_info,
            )
        else:
            return XHSLoginResult(
                success=False,
                error=f"登录验证失败",
            )
    except Exception as e:
        return XHSLoginResult(success=False, error=str(e))
