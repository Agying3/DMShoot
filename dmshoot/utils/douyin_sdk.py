"""DouYin_Spider SDK 桥接层

将 SDK 的 Python 功能（不依赖 JS）和我们的 JS 签名桥（douyin_signer.py）组合，
使 SDK 的其他模块可以安全导入。

易错点:
- dy_util.py 在模块加载时就调用 execjs.compile()，必须绕过
- 本模块提供替代实现，用 douyin_signer.py 的 subprocess 方式代替 execjs
- 如果 Node.js 路径或 jsrsasign 变动，检查 _NODE 和 _NODE_MODULES
"""

import sys
import os
import logging
from pathlib import Path

# SDK 路径
_SDK = Path(__file__).parent.parent.parent / "external" / "DouYin_Spider"
_SDK_UTILS = _SDK / "utils"
_STATIC = _SDK / "static"
_NODE_MODULES = _SDK / "node_modules"

# 确保 SDK 在 sys.path
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))


# ── Python 工具函数（从 dy_util.py 提取，无需 JS） ──

def generate_msToken(length: int = 107) -> str:
    """生成随机 msToken"""
    import random
    base = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    return "".join(base[random.randint(0, len(base) - 1)] for _ in range(length))


def generate_millisecond() -> int:
    """毫秒时间戳"""
    import time
    return int(time.time() * 1000)


def trans_cookies(cookie_str: str) -> dict:
    """cookie 字符串转字典"""
    result = {}
    for part in cookie_str.split("; "):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v
    return result


def generate_webid(auth=None, url: str = "") -> str:
    """获取抖音 webid"""
    import requests
    import re
    if not url:
        url = "https://www.douyin.com/discover?modal_id=7376449060384935209"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "cookie": auth.cookie_str if auth else "",
        }
        r = requests.get(url, headers=headers, verify=False)
        uid = re.findall(r'\\"user_unique_id\\":\\"(.*?)\\"', r.text)
        return uid[0] if uid else ""
    except:
        return generate_fake_webid()


def generate_fake_webid(length: int = 19) -> str:
    """生成假 webid"""
    import random
    return "".join(random.choice("0123456789") for _ in range(length))


def splice_url(params: dict) -> str:
    """拼接 URL 参数"""
    import urllib.parse
    parts = []
    for k, v in params.items():
        parts.append(f"{k}={urllib.parse.quote(str(v) if v is not None else '')}")
    return "&".join(parts)


# ── JS 签名桥接（通过 douyin_signer.py 子进程） ──

def _init_signer():
    """延迟初始化签名器"""
    from dmshoot.utils.douyin_signer import generate_a_bogus, generate_req_sign, generate_ree_key
    return generate_a_bogus, generate_req_sign, generate_ree_key


def get_a_bogus(query: str, data: str = "") -> str:
    _get_ab, _, _ = _init_signer()
    return _get_ab(query, data)


def get_req_sign(data: str, private_key: str) -> str:
    _, _get_sign, _ = _init_signer()
    return _get_sign(data, private_key)


def get_ree_key(private_key: str) -> str:
    _, _, _get_key = _init_signer()
    return _get_key(private_key)


# ── SDK 模块导入（绕过 dy_util 的 execjs） ──

def _patch_imports():
    """Monkey-patch: 用我们的实现替换 SDK 的 dy_util 函数"""
    # 先让 SDK 的 utils 目录可以被 import
    sdk_path = str(_SDK)
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)

    # 动态替换——在 SDK 模块导入后，将其对 dy_util 的引用替换为我们的实现
    import importlib
    import types

    # 创建一个假的 dy_util 模块
    fake_dy_util = types.ModuleType("utils.dy_util")
    fake_dy_util.generate_msToken = generate_msToken
    fake_dy_util.generate_millisecond = generate_millisecond
    fake_dy_util.trans_cookies = trans_cookies
    fake_dy_util.generate_webid = generate_webid
    fake_dy_util.generate_fake_webid = generate_fake_webid
    fake_dy_util.splice_url = splice_url
    fake_dy_util.generate_a_bogus = get_a_bogus
    fake_dy_util.generate_req_sign = get_req_sign
    fake_dy_util.generate_ree_key = get_ree_key
    fake_dy_util.generate_bd_ticket_client_data = _generate_bd_ticket_client_data
    fake_dy_util.generate_csrf_token = generate_csrf_token
    fake_dy_util.__file__ = str(_SDK_UTILS / "dy_util.py")

    sys.modules["utils.dy_util"] = fake_dy_util
    if "utils" not in sys.modules:
        sys.modules["utils"] = types.ModuleType("utils")
    sys.modules["utils"].dy_util = fake_dy_util

    # 现在可以安全导入 SDK 的 builder 了
    from builder.auth import DouyinAuth
    from builder.header import HeaderBuilder, HeaderType
    from builder.params import Params
    from builder.proto import ProtoBuilder

    return DouyinAuth, HeaderBuilder, HeaderType, Params, ProtoBuilder


def _generate_bd_ticket_client_data(api, ticket, ts_sign, priK):
    """BD ticket guard data"""
    import json, base64, time
    timestamp = int(time.time())
    res_sign = f"ticket={ticket}&path={api}&timestamp={timestamp}"
    p = {
        "ts_sign": ts_sign,
        "req_content": "ticket,path,timestamp",
        "req_sign": get_req_sign(res_sign, priK),
        "timestamp": timestamp,
    }
    p = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(p.encode("utf-8")).decode("utf-8")


def generate_csrf_token(cookies_str: str):
    """获取 CSRF token"""
    import requests
    try:
        headers = {
            "accept": "*/*",
            "cookie": cookies_str,
            "referer": "https://www.douyin.com/?recommend=1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-secsdk-csrf-request": "1",
            "x-secsdk-csrf-version": "1.2.22",
        }
        r = requests.head("https://www.douyin.com/service/2/abtest_config/", headers=headers, verify=False)
        tokens = r.headers["X-Ware-Csrf-Token"].split(",")
        return tokens[1], tokens[4]
    except Exception as e:
        logging.getLogger(__name__).warning(f"CSRF token 获取失败: {e}")
        return "", ""


# ── SDK Auth ──

def create_auth(cookie_str: str, web_protect: str = "", keys: str = ""):
    """创建 DouyinAuth 对象"""
    import logging
    _lg = logging.getLogger(__name__)
    # 保险：如果 cookie 缺少 s_v_web_id（SDK 多处硬依赖），自动补充一个
    if "s_v_web_id" not in cookie_str:
        fake_id = f"verify_{generate_fake_webid()}_{generate_fake_webid(19)}"
        cookie_str = cookie_str.strip().rstrip(";")
        cookie_str = f"{cookie_str}; s_v_web_id={fake_id}" if cookie_str else f"s_v_web_id={fake_id}"
        _lg.warning(f"s_v_web_id 缺失，已自动补充")

    DouyinAuth, _, _, _, _ = _patch_imports()
    auth = DouyinAuth()
    try:
        auth.perepare_auth(cookie_str, web_protect, keys)
    except Exception:
        # web_protect/keys 格式异常时降级
        try:
            auth.perepare_auth(cookie_str, "", "")
        except Exception:
            pass
    return auth


# ── 发消息（封装版，隐藏 SDK 内部类） ──

_conv_cache: dict[str, tuple] = {}  # key: "{uid_hash}", 全局缓存


def send_message_cached(auth, peer_uid: int, text: str, cache: dict = None) -> bool:
    """创建对话并发消息，带缓存（避免每次 send 重复 create_conversation）"""
    if cache is None:
        cache = _conv_cache
    try:
        from dy_apis.douyin_api import DouyinAPI
        uid_str = str(peer_uid)
        if uid_str not in cache:
            cache[uid_str] = DouyinAPI.create_conversation(auth, peer_uid)
        cid, sid, ticket = cache[uid_str]
        return DouyinAPI.send_msg(auth, cid, sid, ticket, text)
    except Exception as e:
        logging.getLogger(__name__).error(f"抖音发送失败(uid={peer_uid}): {e}")
        return False


# ── SDK 补丁：模块加载时执行一次 ──

_patch_imports()  # 全局替换 dy_util，确保后续 import 安全


# ── 通知列表 ──

def get_notice_list(auth, num: int = 20) -> list:
    """获取通知/私信列表"""
    try:
        from dy_apis.douyin_api import DouyinAPI
        return DouyinAPI.get_some_notice_list(auth, num=num, notice_group="700")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"抖音获取通知失败: {e}")
        return []
