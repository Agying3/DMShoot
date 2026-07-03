"""小红书私信适配器 — HTTP + 签名方案

原理:
  XHS Creator API 需要 x-s/x-t/x-s-common 签名头。
  通过 Node.js 子进程执行 Spider_XHS 的混淆 JS 生成签名，
  Python 侧发起纯 HTTP 请求，无需 Playwright/浏览器。

依赖:
  - Node.js + crypto-js (cd static && npm install)
  - sign.py (本模块的签名封装)
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from dmshoot.core.adapter import BaseAdapter
from dmshoot.core.message import Message
from dmshoot.plugins.xiaohongshu.im_client import XHSIMClient
from dmshoot.utils.console_log import get_logger, is_log_enabled

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
STATE_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "xhs_state.json"
COOKIE_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "xhs_cookie.txt"
DEBUG_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "adapter_debug.txt"


def _debug(msg: str):
    try:
        from datetime import datetime
        with open(str(DEBUG_FILE), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] [XHS] {msg}\n")
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
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _load_cookie() -> str:
    """加载 Cookie：优先环境变量 → 数据库配置 → 文件"""
    cookie = os.environ.get("XHS_COOKIE", "")
    if cookie:
        return cookie
    # 从数据库配置读取 (GUI 扫码登录保存)
    try:
        from dmshoot.storage import database
        cfg = database.load_config()
        if cfg.xhs_cookie:
            return cfg.xhs_cookie
    except Exception:
        pass
    # 兜底：文件
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_cookie(cookie_str: str):
    """保存 Cookie 到文件（供扫码后手动写入或 GUI 调用）"""
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(cookie_str.strip(), encoding="utf-8")


def _parse_timestamp(ts) -> float:
    if isinstance(ts, str):
        try:
            ts = float(ts)
        except:
            return 0
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            return ts / 1000
        if ts > 1e9:
            return ts
    return 0


class XHSAdapter(BaseAdapter):
    platform_name = "xiaohongshu"
    _im_unavailable = True  # Web 端不支持私信，跳过启动横幅
    BASE_URL = "https://edith.xiaohongshu.com"     # 用户/签名
    GALAXY_URL = "https://creator.xiaohongshu.com" # 创作者消息 API

    def __init__(self, xhs_cookie: str = "", bus=None):
        super().__init__(bus)
        self._cookie = xhs_cookie or _load_cookie()
        self._im = XHSIMClient(self._cookie)
        self._my_uid: str = ""
        self._my_name: str = ""
        self._my_avatar: str = ""
        self._state = _load_state()
        self._replied: set[str] = set(self._state.get("replied", []))
        self._user_cache: dict[str, tuple[str, str]] = {}

    def _call(self, url: str, method: str = "GET",
              json_data: dict = None, params: dict = None) -> Optional[dict]:
        """统一 HTTP 调用入口 — 自动附加签名"""
        from dmshoot.plugins.xiaohongshu.sign import signed_request
        return signed_request(self._cookie, url, method, json_data, params)

    # ── 生命周期 ──

    def connect(self) -> bool:
        _debug("connect: start")
        if not self._cookie:
            _debug("connect: no cookie")
            logger.warning("小红书未登录，请设置 XHS_COOKIE 环境变量或 "
                           "将 Cookie 写入 dmshoot/data/xhs_cookie.txt")
            return False

        try:
            resp = self._call(f"{self.BASE_URL}/api/sns/web/v2/user/me")
            _debug(f"user/me: {json.dumps(resp, ensure_ascii=False)[:300] if resp else 'NULL'}")

            if not resp or not resp["body"].get("success"):
                msg = (resp.get("body", {}).get("msg", "") if resp else "无响应")
                logger.warning(f"小红书Cookie已失效: {msg}")
                _debug(f"connect FAIL: {msg}")
                return False

            user = resp["body"].get("data", {})
            self._my_uid = str(user.get("id", "") or user.get("user_id", ""))
            if not self._my_uid:
                _debug("connect: empty uid")
                return False

            # 从 Galaxy API 获取昵称和头像
            try:
                gresp = self._call(
                    f"{self.GALAXY_URL}/api/galaxy/user/info",
                    params={"userId": self._my_uid},
                )
                if gresp and gresp["status"] == 200 and gresp["body"].get("success"):
                    guser = gresp["body"].get("data", {})
                    self._my_name = guser.get("userName", "") or f"用户{self._my_uid}"
                    self._my_avatar = guser.get("userAvatar", "") or ""
            except Exception:
                pass
            if not self._my_name:
                self._my_name = f"用户{self._my_uid}"

            _debug(f"connect OK: uid={self._my_uid} name={self._my_name} avatar={'YES' if self._my_avatar else 'NO'}")
            # Web 端不支持 IM 私信，跳过历史同步
            logger.success(f"小红书已连接: {self._my_name}({self._my_uid})")
            return True

        except Exception as e:
            _debug(f"connect EXCEPTION: {e}")
            logger.error(f"小红书连接失败: {e}")
            return False

    def disconnect(self):
        self._state["replied"] = list(self._replied)[-5000:]
        _save_state(self._state)

    # ── 发送 ──

    def send_message(self, session_id: str, text: str) -> bool:
        """通过 edith V3 IM API 发送私信"""
        # 解析 session_id 获取 peer_id
        peer_id = session_id.replace("xiaohongshu:", "")
        if not peer_id:
            return False

        try:
            return self._im.send_text(peer_id, text)
        except Exception as e:
            _debug(f"send_message FAIL: {e}")
            return False

    # ── 同步历史 ──

    def _sync_history(self):
        """从创作者平台消息 API 拉取历史（仅通知类消息）"""
        try:
            from dmshoot.storage import database
            from dmshoot.storage.models import SessionRecord

            resp = self._call(f"{self.GALAXY_URL}/api/galaxy/message/list",
                              params={"size": 20})
            if not resp or not resp["body"].get("success"):
                return

            body = resp["body"]
            messages = body.get("data", {}).get("messages", [])
            _debug(f"sync_history: {len(messages)} messages")

            conv_last: dict[str, dict] = {}
            for m in messages:
                sid = str(m.get("sender_id", ""))
                tid = str(m.get("target_user_id", ""))
                peer_id = sid if sid != self._my_uid else tid
                if not peer_id or peer_id == self._my_uid:
                    continue

                content = self._extract_content(m)
                if not content:
                    continue

                ts = _parse_timestamp(m.get("time", 0))
                peer_name = self._user_cache.get(peer_id, (f"用户{peer_id}", ""))[0]

                conv_last[peer_id] = {
                    "peer_name": peer_name,
                    "last_text": content[:50],
                    "last_time": ts,
                    "avatar_url": self._user_cache.get(peer_id, ("", ""))[1],
                }

            for peer_id, info in conv_last.items():
                db.upsert_session(SessionRecord(
                    session_id=f"xiaohongshu:{peer_id}",
                    platform="xiaohongshu", peer_name=info["peer_name"],
                    peer_id=peer_id, last_message=info["last_text"],
                    last_time=info["last_time"],
                    avatar_url=info.get("avatar_url", ""),
                ))
            _debug(f"sync_history done: {len(conv_last)} sessions")

        except Exception as e:
            _debug(f"_sync_history EXCEPTION: {e}")
            logger.warning(f"小红书同步异常: {e}")

    def _get_user_info(self, uid: str) -> tuple[str, str]:
        if uid in self._user_cache:
            return self._user_cache[uid]
        try:
            resp = self._call(
                f"{self.GALAXY_URL}/api/galaxy/user/info",
                params={"userId": uid},
            )
            if resp and resp["status"] == 200 and resp["body"].get("success"):
                user = resp["body"].get("data", {})
                name = user.get("userName", "") or f"用户{uid}"
                avatar = user.get("userAvatar", "") or ""
                return name, avatar
        except Exception as e:
            _debug(f"user/info uid={uid}: {e}")
        return f"用户{uid}", ""

    # ── 轮询 ──

    _poll_debug_done = False

    def _poll_messages(self):
        time.sleep(10)  # Web 端 IM 不可用，跳过无用轮询

    def _process_v3_chats(self, chats: list[dict]):
        """处理 V3 API 返回的聊天会话数据"""
        try:
            from dmshoot.storage import database as db
            from dmshoot.storage.models import ChatMessage, SessionRecord

            for chat in chats:
                peer_id = str(chat.get("peer_id", "") or chat.get("user_id", ""))
                if not peer_id or peer_id == self._my_uid:
                    continue

                last_msg = chat.get("last_msg", "") or chat.get("last_message", "")
                last_time = chat.get("last_time", 0) or chat.get("update_time", 0)
                ts = _parse_timestamp(last_time)

                if peer_id not in self._user_cache:
                    name, avatar = self._get_user_info(peer_id)
                    self._user_cache[peer_id] = (name, avatar)
                peer_name, peer_avatar = self._user_cache.get(peer_id, (f"用户{peer_id}", ""))

                session_id = f"xiaohongshu:{peer_id}"

                # 更新会话记录
                db.upsert_session(SessionRecord(
                    session_id=session_id, platform="xiaohongshu",
                    peer_name=peer_name, peer_id=peer_id,
                    last_message=last_msg[:50] if last_msg else "",
                    last_time=ts, avatar_url=peer_avatar,
                ))

                # 处理新消息
                messages = chat.get("messages", []) or chat.get("msg_list", [])
                for m in messages:
                    msg_id = str(m.get("id", "") or m.get("msg_id", ""))
                    if msg_id and msg_id in self._replied:
                        continue

                    sender_id = str(m.get("sender_id", "") or m.get("user_id", ""))
                    content = m.get("content", "") or m.get("text", "")
                    if not content:
                        continue

                    is_self = sender_id == self._my_uid
                    msg_ts = _parse_timestamp(m.get("time", 0) or m.get("timestamp", 0))
                    sender_name = self._my_name if is_self else peer_name

                    db.save_message(ChatMessage(
                        session_id=session_id, sender_name=sender_name,
                        sender_id=sender_id, content=content,
                        msg_type="text", timestamp=msg_ts, is_self=is_self,
                    ))

                    if not is_self:
                        dm_msg = Message(
                            platform="xiaohongshu", msg_type="text",
                            sender_id=sender_id, sender_name=sender_name,
                            session_id=session_id, content=content,
                            timestamp=msg_ts, is_self=is_self,
                        )
                        logger.recv("小红书", sender_name, content[:50])
                        self._on_message(dm_msg)
                        self._replied.add(msg_id)

            self._state["replied"] = list(self._replied)[-5000:]
            _save_state(self._state)

        except Exception as e:
            _debug(f"_process_v3_chats: {e}")

    def _poll_galaxy_messages(self):
        """回退：轮询创作者平台消息（仅通知类）"""
        try:
            from dmshoot.storage import database as db
            from dmshoot.storage.models import ChatMessage, SessionRecord

            resp = self._call(f"{self.GALAXY_URL}/api/galaxy/message/list",
                              params={"size": 20})
            if not self._poll_debug_done:
                _debug(f"poll: success={resp['body'].get('success') if resp else 'NULL'}")
                self._poll_debug_done = True
            if not resp or not resp["body"].get("success"):
                time.sleep(3)
                return

            messages = resp["body"].get("data", {}).get("messages", [])
            new_count = 0

            for m in messages:
                msg_id = str(m.get("id", ""))
                if msg_id and msg_id in self._replied:
                    continue

                sender_id = str(m.get("sender_id", ""))
                target_id = str(m.get("target_user_id", ""))
                peer_id = sender_id if sender_id != self._my_uid else target_id
                if peer_id == self._my_uid:
                    continue

                content = self._extract_content(m)
                if not content:
                    continue

                is_self = sender_id == self._my_uid
                ts = _parse_timestamp(m.get("time", 0))

                if peer_id not in self._user_cache:
                    name, avatar = self._get_user_info(peer_id)
                    self._user_cache[peer_id] = (name, avatar)
                peer_name, peer_avatar = self._user_cache.get(peer_id, (f"用户{peer_id}", ""))

                session_id = f"xiaohongshu:{peer_id}"
                sender_name = self._my_name if is_self else peer_name

                db.save_message(ChatMessage(
                    session_id=session_id, sender_name=sender_name,
                    sender_id=sender_id, content=content,
                    msg_type="text", timestamp=ts, is_self=is_self,
                ))
                if not is_self:
                    db.upsert_session(SessionRecord(
                        session_id=session_id, platform="xiaohongshu",
                        peer_name=peer_name, peer_id=peer_id,
                        last_message=content[:50], last_time=ts,
                        avatar_url=peer_avatar,
                    ))

                dm_msg = Message(
                    platform="xiaohongshu", msg_type="text",
                    sender_id=sender_id, sender_name=sender_name,
                    session_id=session_id, content=content,
                    timestamp=ts, is_self=is_self,
                )
                logger.recv("小红书", sender_name, content[:50])
                self._on_message(dm_msg)
                self._replied.add(msg_id)
                new_count += 1

            if new_count > 0:
                self._state["replied"] = list(self._replied)[-5000:]
                _save_state(self._state)
                if is_log_enabled("polling"):
                    logger.debug(f"小红书轮询: {new_count}条新消息")

        except Exception as e:
            logger.warning(f"小红书轮询异常: {e}")

    # ── 工具 ──

    @staticmethod
    def _extract_content(msg: dict) -> str:
        content = msg.get("content", "") or msg.get("text", "")
        if not content:
            return ""
        if isinstance(content, str) and content.strip() and content.strip()[0] in "{[":
            try:
                cj = json.loads(content)
                content = cj.get("text") or cj.get("content") or content
            except:
                pass
        return content.strip()
