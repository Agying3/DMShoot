"""小红书 DM / IM 客户端 — edith.xiaohongshu.com V3 API

基于 DEX 逆向提取的 API 端点和 Spider_XHS 签名机制，
使用 Web Cookie 调用 V3 版 IM API。
"""

import json
import time
from pathlib import Path
from typing import Optional


def _get_sign_module():
    """延迟加载签名模块，避免 adapter.py 的 PySide6 依赖链"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'sign',
        Path(__file__).parent / 'sign.py'
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 在首次调用时加载签名模块
_sign = None


def _signed_req(cookie, url, method, json_data=None, params=None, timeout=15):
    """签名的 HTTP 请求封装"""
    global _sign
    if _sign is None:
        _sign = _get_sign_module()
    return _sign.signed_request(cookie, url, method, json_data, params, timeout)

EDITH_BASE = "https://edith.xiaohongshu.com"
V3_CHATS = f"{EDITH_BASE}/api/im/v3/chats"
V3_CHATS_INFO = f"{EDITH_BASE}/api/im/v3/chats/info"
V3_CHAT_GET_UNREAD = f"{EDITH_BASE}/api/im/chat/get_unread"
V3_USERS_MUTUAL_FOLLOW = f"{EDITH_BASE}/api/im/v1/users/mutual/follow"
V3_USERS_FOLLOWING = f"{EDITH_BASE}/api/im/users/following"


def _log(msg: str):
    """简易日志，避免 logger 依赖链"""
    try:
        from dmshoot.utils.console_log import get_logger
        get_logger(__name__).debug(msg)
    except Exception:
        pass


class XHSIMClient:
    """小红书 IM V3 API 客户端

    使用 Web Cookie (a1, web_session 等) + Spider_XHS 签名
    调用 edith.xiaohongshu.com 的 V3 版本 IM API。
    """

    def __init__(self, cookie: str):
        self._cookie = cookie
        self._my_uid: str = ""

    # ── 基础调用 ──

    def _call(self, url: str, method: str = "GET",
              json_data: dict = None, params: dict = None,
              timeout: int = 15) -> Optional[dict]:
        """带签名的 HTTP 调用的简易封装"""
        resp = _signed_req(self._cookie, url, method, json_data, params, timeout)
        if not resp:
            return None
        body = resp.get("body", {})
        if not isinstance(body, dict):
            return None
        return body

    # ── 身份验证 ──

    def verify(self) -> tuple[bool, str, str]:
        """验证 cookie 有效性并获取用户信息

        Returns:
            (ok, user_id, user_name)
        """
        resp = self._call(f"{EDITH_BASE}/api/sns/web/v2/user/me")
        if not resp or not resp.get("success"):
            msg = resp.get("msg", "无响应") if resp else "无响应"
            return False, "", msg

        user = resp.get("data", {})
        uid = str(user.get("user_id", "") or user.get("id", ""))
        if not uid:
            return False, "", "未获取到用户ID"

        self._my_uid = uid

        # 从 Galaxy API 获取昵称
        name = f"用户{uid}"
        try:
            gresp = self._call(
                "https://creator.xiaohongshu.com/api/galaxy/user/info",
                params={"userId": uid},
            )
            if gresp and gresp.get("success"):
                guser = gresp.get("data", {})
                name = guser.get("userName", "") or name
        except Exception:
            pass

        return True, uid, name

    # ── 会话列表 ──

    def list_chats(self) -> list[dict]:
        """获取 IM 会话（聊天）列表

        Returns:
            [{"chat_id": str, "peer_id": str, "peer_name": str, "last_msg": str, ...}, ...]
        """
        result = self._call(V3_CHATS, method="POST")
        if not result:
            return []

        code = result.get("code", -1)
        if code != 0:
                if code == -100:
                    _log("IM 会话列表需要移动端鉴权 (code=-100)")
                else:
                    _log(f"IM 会话列表返回异常: code={code} msg={result.get('msg','')}")
                return []

        data = result.get("data", {})
        chats = data.get("chats") or data.get("chat_list") or data.get("list") or []
        return chats

    def get_chat_info(self, peer_id: str) -> Optional[dict]:
        """获取指定会话详情"""
        result = self._call(V3_CHATS_INFO, params={"target_user_id": peer_id})
        if not result:
            return None
        if result.get("code") == 0:
            return result.get("data", {})
        return None

    def get_unread_count(self) -> int:
        """获取未读消息计数"""
        result = self._call(V3_CHAT_GET_UNREAD)
        if not result or result.get("code") != 0:
            return 0
        data = result.get("data", {})
        return data.get("unread_count", 0) or data.get("count", 0) or data.get("unread", 0)

    # ── 消息发送 ──

    def send_text(self, target_user_id: str, text: str) -> bool:
        """发送文本消息

        尝试多个已知端点格式，直到找到可用的。
        
        当前状态: 所有 V3 端点需要移动端 app token，
        Web Cookie 仅能验证身份但无 IM 权限。
        """
        # 方式1: v3/chats POST 作为发消息入口
        resp = self._call(V3_CHATS, method="POST", json_data={
            "target_user_id": target_user_id,
            "content": text,
            "msg_type": "text",
        })
        if resp and resp.get("code") == 0:
            data = resp.get("data", {})
            if data:
                _log(f"IM 消息发送成功: → {target_user_id}")
                return True
            else:
                _log(f"IM 发送需要移动端 token，Web Cookie 无权限")
                return False

        _log(f"IM 消息发送: 暂无可用端点")
        return False

    # ── 用户查询 ──

    def get_mutual_follows(self) -> list[str]:
        """获取互关用户列表"""
        result = self._call(V3_USERS_MUTUAL_FOLLOW)
        if not result or result.get("code") != 0:
            return []
        data = result.get("data", {})
        return data.get("user_ids", []) or data.get("list", [])

    def get_following(self) -> list[str]:
        """获取关注的用户列表"""
        result = self._call(V3_USERS_FOLLOWING)
        if not result or result.get("code") != 0:
            return []
        data = result.get("data", {})
        return data.get("user_ids", []) or data.get("list", [])
