"""小红书创作者平台签名模块

基于 Spider_XHS (cv-cat) 签名方案，通过 Node.js 子进程
执行 XHS 混淆 JS 生成 x-s / x-t / x-s-common 签名头。

依赖:
  - Node.js: 需要安装 crypto-js (cd static && npm install)
  - JS 文件: static/xhs_creator_260411.js, static/xhs_xray.js,
             static/xhs_xray_pack1.js, static/xhs_xray_pack2.js
"""

import json
import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_STATIC_DIR = Path(__file__).parent / "static"

# 查找 node.exe 绝对路径 (GUI 进程 PATH 可能不包含)
_NODE_PATH = shutil.which('node') or shutil.which('nodejs')
if _NODE_PATH:
    _NODE_PATH = str(Path(_NODE_PATH))
else:
    # 回退：尝试常见安装路径
    _CANDIDATES = [
        r'C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2\node.exe',
        r'C:\Program Files\nodejs\node.exe',
        r'C:\Program Files (x86)\nodejs\node.exe',
    ]
    for p in _CANDIDATES:
        if Path(p).exists():
            _NODE_PATH = p
            break

if not _NODE_PATH:
    raise RuntimeError(
        "未找到 Node.js。请安装 Node.js 或设置 PATH 环境变量。\n"
        "下载: https://nodejs.org/"
    )


def _node_require_call(filename: str, func_name: str, *args) -> object:
    """通过 require() 加载 JS 模块并调用函数，返回 JSON 结果

    比字符串拼接稳定——避免不同 JS 文件因编码/模块系统导致的
    console 作用域问题。
    """
    args_json = json.dumps(args)

    # 构建调用脚本：require 模块 → 调用函数 → 输出 JSON
    # 注意：部分 JS 文件将函数定义在 global 作用域而非 module.exports
    # 且在初始化时有大量 console.log 输出，需要抑制
    script = (
        f'const __orig_log = console.log;\n'
        f'console.log = () => {{}};\n'
        f'const mod = require("./{filename}");\n'
        f'const __fn = mod.{func_name} || global.{func_name};\n'
        f'if (typeof __fn !== "function") '
        f'  throw new Error("{func_name} not found in module or global");\n'
        f'const __result = __fn(...{args_json});\n'
        f'__orig_log(JSON.stringify(__result));'
    )

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.js', delete=False,
        dir=str(_STATIC_DIR), encoding='utf-8',
    )
    try:
        tmp.write(script)
        tmp.close()

        try:
            result = subprocess.run(
                [_NODE_PATH, tmp.name],
                capture_output=True, text=True,
                timeout=30,
                cwd=str(_STATIC_DIR),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"JS 签名超时: {filename}.{func_name}")

        if result.returncode != 0:
            raise RuntimeError(
                f"Node.js 错误 ({filename}.{func_name}):\n"
                f"{result.stderr.strip()[-500:]}"
            )

        # 取最后一行有效 JSON
        stdout = result.stdout.strip()
        for line in reversed(stdout.split('\n')):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        raise RuntimeError(f"JS 输出中无有效 JSON: {stdout[:200]}")

    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass


# ── Cookie 解析 ──

def parse_cookies(cookie_str: str) -> dict:
    """解析 Cookie 字符串为 dict (requests 格式)"""
    if not cookie_str:
        return {}
    result = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            key, _, value = item.partition('=')
            result[key] = value
    return result


# ── Trace ID 生成 ──

def generate_x_b3_traceid(length: int = 16) -> str:
    """生成随机 x-b3-traceid (纯 Python)"""
    chars = "abcdef0123456789"
    return "".join(chars[math.floor(16 * random.random())] for _ in range(length))


_cached_xray_traceid: str = ""

def generate_xray_traceid() -> str:
    """生成 x-xray-traceid (需要 xhs_xray.js + 2 个 pack)，仅首次调用时生成并缓存"""
    global _cached_xray_traceid
    if not _cached_xray_traceid:
        _cached_xray_traceid = _node_require_call('xhs_xray.js', 'traceId')
    return _cached_xray_traceid


# ── 签名生成 ──

def generate_xsc(a1: str, api: str, data: str = "") -> dict:
    """生成签名头 dict

    Args:
        a1:   Cookie 中的 a1 值
        api:  API 路径 (含 query string)
        data: POST 请求体 JSON 字符串, GET 时传 ""

    Returns:
        {"x-s": ..., "x-t": ..., "x-s-common": ...,
         "x-b3-traceid": ..., "x-xray-traceid": ...}
    """
    ret = _node_require_call(
        'xhs_creator_260411.js',
        'get_request_headers_params',
        api, data, a1,
    )
    return {
        "x-s": ret['xs'],
        "x-t": str(ret['xt']),
        "x-s-common": ret['xs_common'],
        "x-b3-traceid": generate_x_b3_traceid(),
        "x-xray-traceid": generate_xray_traceid(),
    }


# ── 基础请求头 ──

def _base_headers() -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://creator.xiaohongshu.com",
        "referer": "https://creator.xiaohongshu.com/",
        "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
        ),
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }


# ── 带签名 HTTP 请求 ──

def signed_request(
    cookie_str: str,
    url: str,
    method: str = "GET",
    json_data: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 15,
) -> Optional[dict]:
    """发起带完整签名的创作者平台 API 请求

    Returns:
        {"status": <int>, "body": <dict|str>} 或 None
    """
    import requests
    from urllib.parse import urlparse, urlencode

    cookies = parse_cookies(cookie_str)
    a1 = cookies.get('a1', '')

    parsed = urlparse(url)
    api_path = parsed.path

    data_str = ""
    if json_data:
        data_str = json.dumps(json_data, separators=(',', ':'), ensure_ascii=False)

    if method.upper() == "GET" and params:
        api_path = f"{api_path}?{urlencode(params)}"

    headers = _base_headers()
    try:
        sign_headers = generate_xsc(a1, api_path, data_str)
        headers.update(sign_headers)
    except Exception as e:
        from dmshoot.utils.console_log import get_logger
        get_logger(__name__).error(f"签名生成失败: {e}")
        return None

    try:
        if method.upper() == "POST":
            body_bytes = data_str.encode('utf-8') if data_str else None
            resp = requests.post(
                url, headers=headers, cookies=cookies,
                data=body_bytes, timeout=timeout,
            )
        else:
            resp = requests.get(
                url, headers=headers, cookies=cookies,
                params=params, timeout=timeout,
            )

        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            body = resp.text

        return {"status": resp.status_code, "body": body}

    except requests.RequestException:
        return None
