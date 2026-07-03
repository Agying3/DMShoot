"""B站私信适配器 — 全异步轮询 + AI自动回复"""

import json
import time
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from dmshoot.core.adapter import BaseAdapter, ErrorCategory, ReconnectBackoff
from dmshoot.core.message import Message
from dmshoot.utils.console_log import get_logger, is_log_enabled

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
STATE_FILE = _PROJECT_ROOT / "dmshoot" / "data" / "bilibili_state.json"


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


def _debug(msg: str):
    try:
        debug_path = Path(__file__).parent.parent.parent / "data" / "adapter_debug.txt"
        with open(str(debug_path), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except:
        pass


class BilibiliAdapter(BaseAdapter):
    platform_name = "bilibili"

    def __init__(self, bilibili_sessdata: str = "", bilibili_jct: str = "",
                 bilibili_buvid3: str = "", bilibili_buvid4: str = "",
                 bilibili_dedeuserid: str = "", bilibili_ac_time_value: str = "",
                 bus=None):
        super().__init__(bus)
        self._sessdata = bilibili_sessdata
        self._bili_jct = bilibili_jct
        self._buvid3 = bilibili_buvid3
        self._buvid4 = bilibili_buvid4
        self._dedeuserid = bilibili_dedeuserid
        self._ac_time_value = bilibili_ac_time_value
        self._credential = None
        self._my_uid: int = 0
        self._state = _load_state()
        self._replied: set[int] = set(self._state.get("replied", []))
        self._session_last_seq: dict[int, int] = {}
        self._http: Optional["httpx.AsyncClient"] = None  # 异步复用连接池

    def stop(self):
        """异步安全停止 — 用 Event 取消协程，再回退基类"""
        self._running = False
        self._connected = False
        if hasattr(self, '_stop_event'):
            self._stop_event.set()
        super().stop()

    def run(self):
        """QThread 入口 — asyncio 事件循环"""
        from dmshoot.core.bus import PlatformStatus
        self._running = True
        self._set_status(PlatformStatus.CONNECTING, "连接中...")
        if not self.connect():
            self._set_status(PlatformStatus.ERROR, "连接失败")
            import time as _time; _time.sleep(0.1)  # 等信号处理完毕再退出线程
            return
        self._connected = True
        self._set_status(PlatformStatus.ONLINE, f"{self._my_name} · 已连接")
        self._stop_event = asyncio.Event()
        try:
            asyncio.run(self._async_loop())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.on_error(ErrorCategory.INTERNAL, f"事件循环崩溃: {e}", e)
        finally:
            self.disconnect()
            self._set_status(PlatformStatus.OFFLINE, "已断开")

    def connect(self) -> bool:
        try:
            from bilibili_api import Credential, user, sync as bsync
            self._credential = Credential(
                sessdata=self._sessdata,
                bili_jct=self._bili_jct,
                buvid3=self._buvid3,
                buvid4=self._buvid4,
                dedeuserid=self._dedeuserid,
                ac_time_value=self._ac_time_value,
            )
            info = bsync(user.get_self_info(self._credential))
            self._my_uid = info.get("mid", 0) if isinstance(info, dict) else 0
            self._my_name = info.get("name", "") if isinstance(info, dict) else ""
            logger.success(f"B站已连接: UID={self._my_uid}, 昵称={self._my_name}")
            return True
        except Exception as e:
            self.on_error(ErrorCategory.AUTH, f"凭证创建失败: {e}", e)
            return False

    def disconnect(self):
        self._state["replied"] = list(self._replied)[-5000:]
        _save_state(self._state)
        self._credential = None

    _user_info_cache: dict[int, tuple[str, str]] = {}
    _user_info_failed: set[int] = set()

    def _build_cookie(self) -> str:
        parts = [f"SESSDATA={self._sessdata}"]
        if self._buvid3: parts.append(f"buvid3={self._buvid3}")
        if self._buvid4: parts.append(f"buvid4={self._buvid4}")
        if self._dedeuserid: parts.append(f"DedeUserID={self._dedeuserid}")
        return "; ".join(parts)

    async def _get_user_name(self, uid: int) -> tuple[str, str]:
        """异步获取用户昵称（httpx.AsyncClient 复用连接池）"""
        if uid in self._user_info_cache:
            return self._user_info_cache[uid]
        if uid in self._user_info_failed:
            return f"用户{uid}", ""

        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
            "Cookie": self._build_cookie(),
        }
        name, face = "", ""
        try:
            resp = await self._http.get("https://api.bilibili.com/x/web-interface/card", params={"mid": uid}, headers=headers)
            data = resp.json()
            if data.get("code") == 0:
                card = data.get("data", {}).get("card", {}) or {}
                name = card.get("name", "")
                face = card.get("face", "")
            else:
                _debug(f"  card({uid}) -> code={data.get('code')} msg={data.get('message','')}")
        except Exception as e:
            _debug(f"  card({uid}) FAIL: {e}")
        if not name:
            try:
                resp2 = await self._http.get("https://api.bilibili.com/x/space/acc/info", params={"mid": uid}, headers=headers)
                d2 = resp2.json()
                if d2.get("code") == 0 and d2.get("data"):
                    name = d2["data"].get("name", "") or name
                    face = d2["data"].get("face", "") or face
            except Exception as e:
                _debug(f"  space({uid}) FAIL: {e}")
        if name:
            self._user_info_cache[uid] = (name, face or "")
            return name, face or ""
        _debug(f"  getUserInfo({uid}) BOTH APIs FAILED")
        self._user_info_failed.add(uid)
        return f"用户{uid}", ""

    async def _sync_history(self):
        """在 _async_loop 中调用，asyncio.gather 并发拉取所有会话消息"""
        from bilibili_api import session as sess
        from dmshoot.storage import database
        from dmshoot.storage.models import SessionRecord, ChatMessage
        db = database

        data = await sess.get_sessions(self._credential)
        sessions = data.get("session_list", [])
        _debug(f"同步历史: {len(sessions)}个会话")

        total_msgs = 0
        batch_msgs: list[ChatMessage] = []

        async def fetch_one(s):
            tid = s.get("talker_id", 0)
            if not tid or tid in (12076317,):
                return None
            acc_raw = s.get("account_info", "")
            peer_name = s.get("name", "") or ""
            peer_face = s.get("face", "") or ""
            if acc_raw and isinstance(acc_raw, str):
                import ast
                try:
                    acc = ast.literal_eval(acc_raw)
                    peer_name = acc.get("name") or peer_name
                    peer_face = acc.get("pic_url", "") or peer_face
                except:
                    pass
            if not peer_name or peer_name.startswith("用户"):
                n, f = await self._get_user_name(tid)
                if n and not n.startswith("用户"): peer_name = n
                if f: peer_face = f
            elif not peer_face:
                _, f = await self._get_user_name(tid)
                if f: peer_face = f
            if not peer_name:
                peer_name = f"粉丝{tid}"

            try:
                msgs = await sess.fetch_session_msgs(tid, self._credential, 1, 0)
                messages = msgs.get("messages", [])
            except:
                return (tid, peer_name, peer_face, "", 0, [], [])

            last_text, last_time, seqs, parsed_msgs = "", 0, [], []
            for m in messages:
                parsed = self._parse_message(m, peer_name)
                if parsed is None: continue
                parsed_msgs.append(ChatMessage(
                    session_id=f"bilibili:{tid}",
                    sender_name=peer_name if not parsed.is_self else parsed.sender_name,
                    sender_id=parsed.sender_id, content=parsed.content,
                    msg_type=parsed.msg_type, timestamp=parsed.timestamp,
                    is_self=parsed.is_self,
                ))
                last_text, last_time = parsed.content[:30], parsed.timestamp
                if m.get("msg_seqno", 0): seqs.append(m["msg_seqno"])
            return (tid, peer_name, peer_face, last_text, last_time, seqs, parsed_msgs)

        tasks = [fetch_one(s) for s in sessions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        batch_upserts: list[SessionRecord] = []
        for result in results:
            if isinstance(result, Exception) or result is None: continue
            tid, name, face, last_text, last_time, seqs, msgs = result
            if tid == self._my_uid: continue
            batch_upserts.append(SessionRecord(
                session_id=f"bilibili:{tid}", platform="bilibili",
                peer_name=name, peer_id=str(tid),
                last_message=last_text, last_time=last_time or 0,
                avatar_url=face,
            ))
            self._replied.update(seqs)
            if seqs: self._session_last_seq[tid] = max(self._session_last_seq.get(tid, 0), max(seqs))
            batch_msgs.extend(msgs)
            total_msgs += len(msgs)

        if batch_msgs: db.save_messages_batch(batch_msgs)
        if batch_upserts: db.upsert_sessions_batch(batch_upserts)
        self._state["replied"] = list(self._replied)[-5000:]
        _save_state(self._state)
        logger.success(f"B站同步完成: {len(batch_upserts)}会话, {total_msgs}消息")

    def send_message(self, session_id: str, text: str) -> bool:
        """同步发送 — 保持兼容（用 bsync 封装）"""
        try:
            talker_id = int(session_id.split(":")[-1])
        except (ValueError, IndexError, AttributeError):
            return False
        try:
            from bilibili_api import session, sync as bsync
            bsync(session.send_msg(
                self._credential, talker_id,
                session.EventType.TEXT, content=text,
            ))
            logger.success(f"B站回复已发送 → uid={talker_id}: {text[:200]}")
            return True
        except Exception as e:
            logger.error(f"B站发送失败 → uid={talker_id}: {e}")
            return False

    def _parse_message(self, msg: dict, peer_name: str = "") -> Optional[Message]:
        try:
            sender_uid = int(msg.get("sender_uid", 0))
        except (ValueError, TypeError):
            return None

        is_self = (sender_uid == self._my_uid)

        # 过滤系统消息
        raw_content = msg.get("content", "")
        if isinstance(raw_content, str) and raw_content.startswith("{"):
            try:
                parsed = json.loads(raw_content)
                text = parsed.get("content", raw_content)
            except:
                text = raw_content
        else:
            text = str(raw_content)

        text = text.strip()
        if not text:
            return None
        if "互相关注" in text or "开始聊天" in text or "登录成功" in text:
            return None

        msg_type = "text"
        if msg.get("msg_type") in (2, 6):
            msg_type = "image"

        # B站时间戳：尝试多种字段名
        ts = msg.get("timestamp", 0) or msg.get("msg_time", 0) or msg.get("mtime", 0) or msg.get("ctime", 0)
        if isinstance(ts, (int, float)) and ts > 1000000000000:  # 毫秒
            ts = ts / 1000
        elif isinstance(ts, (int, float)) and ts > 100000000:    # Unix 秒
            pass
        elif isinstance(ts, str):
            try: ts = float(ts); ts = ts / 1000 if ts > 1000000000000 else ts
            except: ts = 0
        else:
            ts = 0
        if not ts:
            _debug(f"  时间戳缺失 msg_keys={list(msg.keys())[:10]}")

        return Message(
            platform="bilibili",
            msg_type=msg_type,
            sender_id=str(sender_uid),
            sender_name=(
                peer_name if (not is_self and peer_name) else
                msg.get("sender_name") or f"粉丝{sender_uid}"
            ),
            session_id=f"bilibili:{msg.get('talker_id', sender_uid)}",
            content=text,
            seq_id=msg.get("msg_seqno", 0),
            is_self=is_self,
            timestamp=float(ts) if ts else 0.0,
        )

    async def _async_poll(self):
        """异步并发轮询 — asyncio.gather 拉所有会话"""
        if self._stop_event.is_set():
            return
        import time as _time; _start = _time.perf_counter()
        try:
            from bilibili_api import session as sess

            data = await sess.get_sessions(self._credential)
            sessions = data.get("session_list", [])
            total_unread = sum(s.get("unread_count", 0) for s in sessions)
            if total_unread > 0:
                if is_log_enabled("polling"):
                    logger.debug(f"B站轮询: {len(sessions)}会话, 未读={total_unread}")

            # asyncio.gather 并发拉取
            async def poll_one(s):
                talker_id = s.get("talker_id", 0)
                if s.get("unread_count", 0) <= 0 or not talker_id:
                    return []
                if int(s.get("system_msg_type", 0)) > 0:
                    return []
                acc_raw = s.get("account_info", "")
                # 从 account_info 提取真实昵称
                real_name = s.get("name", "")
                if acc_raw and isinstance(acc_raw, str):
                    import ast
                    try:
                        acc = ast.literal_eval(acc_raw)
                        name = acc.get("name", "")
                        if name in ("UP主小助手", "哔哩哔哩智能机", "bilibili"): return []
                        if name and not name.startswith("用户"):
                            real_name = name  # 优先用 account_info 里的真名
                    except: pass

                begin = self._session_last_seq.get(talker_id, 0)
                try:
                    msg_data = await sess.fetch_session_msgs(talker_id, self._credential, 1, begin)
                    messages = msg_data.get("messages") or []
                except:
                    return []

                results = []
                for msg in messages:
                    seq = msg.get("msg_seqno", 0)
                    if seq and seq in self._replied: continue
                    dm_msg = self._parse_message(msg, real_name)
                    if dm_msg is None: continue

                    if not dm_msg.is_self:
                        logger.recv("B站", dm_msg.sender_name, dm_msg.content[:200])
                        self._on_message(dm_msg)
                        # 有真名时更新 sessions 表，确保通讯录显示真名
                        if real_name and not real_name.startswith("用户") and not real_name.startswith("粉丝"):
                            try:
                                db = __import__('dmshoot.storage.database', fromlist=['database'])
                                db.get_conn().execute(
                                    "UPDATE sessions SET peer_name=? WHERE session_id=? AND (peer_name LIKE '用户%' OR peer_name LIKE '粉丝%' OR peer_name LIKE 'fans_%')",
                                    (real_name, dm_msg.session_id)
                                )
                                db.get_conn().commit()
                            except Exception:
                                pass
                    if seq:
                        self._replied.add(seq)
                        if seq > self._session_last_seq.get(talker_id, 0):
                            self._session_last_seq[talker_id] = seq
                    results.append(dm_msg)
                return results

            tasks = [poll_one(s) for s in sessions]
            all_results = await asyncio.gather(*tasks, return_exceptions=True)
            total_new = sum(len(r) for r in all_results if isinstance(r, list))
            errors = sum(1 for r in all_results if isinstance(r, Exception))
            if errors:
                _debug(f"轮询完成: {len(sessions)}会话, {total_new}新消息, {errors}异常")
            elif total_new > 0:
                _debug(f"轮询完成: {len(sessions)}会话, {total_new}新消息")

            if len(self._replied) > 100:
                self._state["replied"] = list(self._replied)
                _save_state(self._state)

        except Exception as e:
            err_str = str(e)
            if "-101" in err_str or "未登录" in err_str:
                self.on_error(ErrorCategory.AUTH, f"Cookie 已过期: {e}", e)
                self._running = False
                return
            if "-509" in err_str or "请求过于频繁" in err_str:
                # 限流错误：抛出让外层退避，不在此处标记网络错误
                raise
            self.on_error(ErrorCategory.NETWORK, f"单次轮询异常: {e}", e)
            await self._sleep(5)
            from dmshoot.core.perf_monitor import get_monitor
            get_monitor().record_api(0, is_error=True)
        else:
            await self._sleep(10)
            _elapsed = (_time.perf_counter() - _start) * 1000
            from dmshoot.core.perf_monitor import get_monitor
            get_monitor().record_api(_elapsed)

    async def _sleep(self, seconds: float):
        """可中断 sleep — 收到 stop 信号时立即返回"""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _async_loop(self):
        """asyncio 主循环 — 历史同步(30s超时) → 轮询（退避重连）"""
        import httpx
        backoff = ReconnectBackoff(min_s=1.0, max_s=30.0)
        async with httpx.AsyncClient(timeout=5) as self._http:
            try:
                await asyncio.wait_for(self._sync_history(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("B站历史同步超时(30s)，跳过")
            except Exception as e:
                logger.warning(f"B站历史同步失败: {e}")
            while self._running and not self._stop_event.is_set():
                try:
                    if self._stop_event.is_set():
                        break
                    await self._async_poll()
                    backoff.reset()  # 成功则重置退避
                except Exception as e:
                    wait = backoff.fail()
                    self.on_error(ErrorCategory.NETWORK, f"轮询失败(重试间隔{wait:.0f}s): {e}", e)
                    await self._sleep(wait)
