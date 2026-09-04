"""抖音私信适配器 — asyncio 版

监听: WebSocket 实时消息
同步: 缓存 + 子进程 Playwright (不阻塞 QThread)

SDK 依赖已通过 DouyinClient 隔离。
"""

import time
import asyncio
import threading
from collections import deque
from pathlib import Path

import urllib3
urllib3.disable_warnings()

from dmshoot.core.adapter import BaseAdapter, ErrorCategory, ReconnectBackoff
from dmshoot.core.message import Message
from dmshoot.utils.console_log import get_logger
from dmshoot.plugins.douyin.douyin_client import DouyinClient

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # plugins/douyin → 项目根
# 去重全走 DB 唯一索引 + 内存 set，不持久化文件


class DouyinAdapter(BaseAdapter):
    platform_name = "douyin"

    def __init__(self, douyin_cookie: str, douyin_web_protect: str = "", douyin_keys: str = "", bus=None):
        super().__init__(bus)
        self._cookie_str = douyin_cookie
        self._web_protect = douyin_web_protect
        self._keys = douyin_keys
        self._auth = None
        self._client = None
        self._my_uid: str = ""
        self._my_name = ""
        self._my_avatar = ""
        self._replied: set[str] = set()
        self._replied_order: deque[str] = deque()
        self._stop_event = threading.Event()
        self._conv_to_peer: dict[str, str] = {}
        self._peer_cache: dict[str, tuple[str, str]] = {}
        self._conv_cache: dict[str, tuple] = {}
        self._pending_peer_uids: set[str] = set()
        self._peer_refresh_task = None

    def stop(self):
        self._running = False
        self._connected = False
        self._stop_event.set()
        if self._client:
            self._client.stop_ws_receiver()
        super().stop()

    def run(self):
        """QThread 入口 — asyncio 事件循环"""
        from dmshoot.core.bus import PlatformStatus
        self._running = True
        self._set_status(PlatformStatus.CONNECTING, "连接中...")
        if not self.connect():
            self._set_status(PlatformStatus.ERROR, "连接失败")
            import time; time.sleep(0.1)  # 等信号处理完毕再退出
            return
        ws = self._client.ws_receiver if self._client else None
        if ws and ws.connected:
            self._on_ws_state("online", "WS 已连接")
        else:
            self._set_status(PlatformStatus.CONNECTING, f"{self._my_name} · 等待 WS 连接")
        try:
            asyncio.run(self._async_loop())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.on_error(ErrorCategory.INTERNAL, f"事件循环崩溃: {e}", e)
        finally:
            self.disconnect()
            self._set_status(PlatformStatus.OFFLINE, "已断开")

    # ── 生命周期 ──

    def connect(self) -> bool:
        try:
            self._client = DouyinClient(self._cookie_str, self._web_protect, self._keys)
            ok, err = self._client.connect()
            if not ok:
                logger.warning(f"  连接: {err}，Cookie 可能已过期")
                self.bus.set_platform_status("douyin", err, "请重新扫码登录")
                return False
            self._auth = self._client.auth
            self._my_uid = self._client.uid
            self._my_name, self._my_avatar = self._fetch_my_profile()
            if not self._my_name:
                logger.warning("  连接: 无法获取昵称，Cookie 可能已过期")
                self.bus.set_platform_status("douyin", "Cookie 已过期", "请重新扫码登录")
                return False
            ticket_status = "有" if self._client.has_ticket else "无（发消息需重新扫码）"
            logger.success(f"  状态: {self._my_name} | ticket={ticket_status}")
            if not self._client.has_ticket:
                self.bus.log.emit("ERROR", "抖音", "缺少 ticket，能收不能发。请清理后重新扫码。")
                self.bus.set_platform_status("douyin", "缺少 ticket", "能收不能发，需重新扫码")
            # 预热 DB 缓存
            self._warm_peer_cache()

            # WS 监听（先于历史同步启动）
            self._client.start_ws_receiver(on_state=self._on_ws_state)

            # 同步历史会话
            logger.info("  → 开始同步数据...")
            self._sync_history()

            return True
        except Exception as e:
            logger.error(f"抖音连接失败: {e}")
            self.bus.set_platform_status("douyin", "Cookie 已过期", str(e)[:60])
            return False

    def disconnect(self):
        if self._client:
            self._client.stop_ws_receiver()
        self._auth = None
        self._client = None

    def _on_ws_state(self, state: str, message: str):
        """WS 线程回报真实连接状态，绿灯只由握手成功触发。"""
        if not self._running:
            return
        from dmshoot.core.bus import PlatformStatus
        if state == "online":
            self._connected = True
            suffix = "已连接"
            if self._client and not self._client.has_ticket:
                suffix += "（缺少 ticket，无法发送）"
            self._set_status(PlatformStatus.ONLINE, f"{self._my_name} · {suffix}")
        else:
            self._connected = False
            self._set_status(PlatformStatus.CONNECTING, message or "WS 重连中")

    def _remember_message_key(self, key: str):
        """保存有限数量的运行时去重键，持久去重由 SQLite 负责。"""
        if key in self._replied:
            return
        if len(self._replied_order) >= 10_000:
            expired = self._replied_order.popleft()
            self._replied.discard(expired)
        self._replied_order.append(key)
        self._replied.add(key)

    def _fetch_my_name(self) -> str:
        return self._fetch_my_profile()[0]

    def _fetch_my_profile(self) -> tuple[str, str]:
        """读取当前抖音账号昵称和头像，失败时返回空值。"""
        try:
            import requests
            resp = requests.get(
                "https://creator.douyin.com/web/api/media/user/info/",
                headers={"Cookie": self._cookie_str, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                         "Referer": "https://creator.douyin.com/"},
                timeout=15, verify=False)
            if resp.status_code == 200:
                user = resp.json().get("user", {}) or {}
                avatar_obj = (
                    user.get("avatar_larger") or user.get("avatar_medium")
                    or user.get("avatar_thumb") or {}
                )
                avatar = (
                    list(avatar_obj.get("url_list", []))[0]
                    if avatar_obj.get("url_list") else
                    user.get("avatar_url", "") or user.get("avatar", "")
                )
                return user.get("nickname", ""), avatar
        except Exception:
            pass
        return "", ""

    # ── 发送 ──

    def send_message(self, session_id: str, text: str) -> bool:
        """发送私信"""
        if not self._auth:
            logger.warning("抖音发送失败: auth 未初始化")
            return False
        if not self._client.has_ticket:
            logger.warning("抖音发送失败: 缺少 ticket")
            return False
        try:
            parts = session_id.split(":")
            if len(parts) < 5:
                logger.warning(f"抖音 send_message 格式错误: {session_id}")
                return False
            peer_uid = parts[3]  # douyin:0:1:{peer_uid}:{my_uid}:0:
            return self._client.send_message(int(peer_uid), text)
        except Exception as e:
            logger.error(f"抖音发送失败: {e}")
            return False

    # ── 同步 ──

    def _sync_history(self):
        """同步历史会话 + 消息（从 protobuf 缓存）"""
        try:
            from dmshoot.storage import database
            from dmshoot.storage.models import SessionRecord, ChatMessage

            conversations = self._client.fetch_history()
            if not conversations:
                logger.info("暂无历史会话，WS 实时消息将逐步建立联系人列表")
                return

            session_records = []
            for conv in conversations:
                session_records.append(SessionRecord(
                    session_id=f"douyin:0:1:{conv['peer_uid']}:{self._my_uid}:0:",
                    platform="douyin",
                    peer_name=conv['nickname'],
                    peer_id=conv['peer_uid'],
                    last_message="",
                    last_time=time.time(),
                    avatar_url=conv.get('avatar', ''),
                ))
            database.upsert_sessions_batch(session_records)

            # 保存 protobuf 解析出的历史消息（批量写入）
            cached_msgs = self._client.get_cached_messages()
            saved_count = 0
            if cached_msgs:
                batch: list[ChatMessage] = []
                for msg in cached_msgs:
                    sender_uid = msg.get('sender_uid', '')
                    content = msg.get('content', '')
                    is_self = msg.get('is_self', False)
                    peer_uid = sender_uid if not is_self else (msg.get('conv_short_id', '') or sender_uid)
                    ts = msg.get('timestamp', time.time())
                    server_id = msg.get('server_message_id', 0)
                    msg_index = msg.get('msg_index', 0)
                    conv_short_id = msg.get('conv_short_id', '')
                    if server_id:
                        message_key = f"douyin:{server_id}"
                    elif conv_short_id and msg_index:
                        message_key = f"douyin:{conv_short_id}:{msg_index}"
                    else:
                        message_key = ""
                    session_id = f"douyin:0:1:{peer_uid}:{self._my_uid}:0:"
                    sender_name = self._my_name if is_self else f"用户{sender_uid}"[:20]
                    if not is_self and sender_uid in self._peer_cache:
                        sender_name = self._peer_cache[sender_uid][0]
                    batch.append(ChatMessage(
                        session_id=session_id, sender_name=sender_name,
                        sender_id=sender_uid, content=content,
                        msg_type="text", timestamp=ts, is_self=is_self,
                        message_key=message_key,
                    ))
                saved_count = database.save_messages_batch(batch)
                logger.success(f"  ✓ 同步完成: {len(conversations)}会话 + {saved_count}条历史消息")
                logger.debug_category(
                    "message_sync",
                    f"抖音历史同步: 会话={len(conversations)} 解析={len(batch)} 新增={saved_count}",
                )
            else:
                logger.success(f"  ✓ 同步完成: {len(conversations)}会话（无历史消息）")
        except Exception as e:
            logger.error(f"抖音同步异常: {e}")

    # ── 实时消息轮询 ──

    def _warm_peer_cache(self):
        """启动时从 DB 预热缓存"""
        try:
            from dmshoot.storage import database
            for s in (database.get_sessions("douyin") or []):
                if s.peer_id:
                    self._peer_cache[s.peer_id] = (s.peer_name, s.avatar_url or "")
        except Exception:
            pass

    def _get_peer_uid_for_conv(self, conv_id: str) -> str:
        """通过 conversation_short_id 查找 peer_uid。
        映射由 WS 非自己消息时建立（sender_uid → conv_id），
        自己的消息收到时如果映射还没建立，返回空（跳过不存）。
        """
        return self._conv_to_peer.get(conv_id, "")

    async def _async_poll(self):
        if self._stop_event.is_set():
            return False
        ws = self._client.ws_receiver
        if ws is None:
            return False

        entries = ws.get_messages_batch(100)
        if not entries:
            return False

        qsize = ws.queue_size
        logger.debug_category(
            "polling",
            f"WS队列: 待处理{qsize} | 已去重{len(self._replied)} | 用户缓存{len(self._peer_cache)}",
        )

        from dmshoot.storage import database
        from dmshoot.storage.models import ChatMessage

        written = 0
        skipped_dup = 0
        self_messages: list[ChatMessage] = []
        unknown_senders: set[str] = set()  # 新发送者，需要拉取昵称+头像
        for entry in entries:
            try:
                sender_uid = entry["sender_uid"]
                content = entry["content"]
                conv_id = entry["conversation_id"]
                ts = entry.get("timestamp", time.time())
                is_self = sender_uid == self._my_uid
                msg_index = entry.get("msg_index", 0)
                server_message_id = entry.get("server_message_id", "")

                # 服务端 ID 优先；序号缺失时交给 DB 的精确时间戳规则兜底。
                if server_message_id:
                    dedup_key = f"douyin:{server_message_id}"
                elif msg_index:
                    dedup_key = f"douyin:{conv_id}:{msg_index}"
                else:
                    dedup_key = ""
                if dedup_key and dedup_key in self._replied:
                    skipped_dup += 1
                    continue

                # 确定 peer_uid: 自己的消息用对方的 conversation，对方的消息直接用自己的 UID 查
                if is_self:
                    peer_uid = self._get_peer_uid_for_conv(conv_id)
                else:
                    peer_uid = sender_uid
                    # 建立 conv_id ↔ peer_uid 映射，供后续自己的消息使用
                    if conv_id not in self._conv_to_peer:
                        self._conv_to_peer[conv_id] = peer_uid

                # session_id 统一用 peer_uid 格式，无 peer_uid 时用 conv_id 代替（避免格式分裂）
                session_id = f"douyin:0:1:{peer_uid or conv_id}:{self._my_uid}:0:"

                if is_self:
                    sender_name = self._my_name or "我"
                else:
                    # 优先从缓存取，避免每条消息全量扫 DB
                    cached = self._peer_cache.get(sender_uid)
                    sender_name = cached[0] if cached else f"用户{sender_uid}"

                if not is_self:
                    was_cached = sender_uid in self._peer_cache
                    avatar = (self._peer_cache.get(sender_uid) or ("", ""))[1]
                    self._peer_cache[sender_uid] = (sender_name, avatar)
                    # 新发送者：标记需要从 API 拉取实际昵称+头像
                    if not was_cached:
                        unknown_senders.add(sender_uid)

                written += 1

                if is_self:
                    logger.info(f"[我→{sender_name}] {content[:50]}")
                else:
                    logger.recv("抖音", sender_name, content[:200])

                # 入站消息交给统一 GUI 事务保存；自己的消息只在适配器批量持久化。
                if is_self:
                    self_messages.append(ChatMessage(
                        session_id=session_id, sender_name=sender_name,
                        sender_id=sender_uid, content=content,
                        msg_type="text", timestamp=ts, is_self=True,
                        message_key=dedup_key,
                    ))
                else:
                    self._on_message(Message(
                        platform="douyin", msg_type="text",
                        sender_id=sender_uid, sender_name=sender_name,
                        session_id=session_id, content=content,
                        timestamp=ts, is_self=False,
                        seq_id=int(server_message_id or msg_index or 0),
                        message_key=dedup_key,
                    ))
                if dedup_key:
                    self._remember_message_key(dedup_key)

            except Exception as e:
                logger.debug(f"抖音消息处理异常: {e}")

        if self_messages:
            database.save_messages_batch(self_messages)
        if written or skipped_dup:
            logger.debug_category("ws_batch", f"WS批处理: {written}接收 + {skipped_dup}去重")
        # 新发送者：从 API 拉取昵称+头像，更新会话表
        if unknown_senders:
            self._queue_peer_refresh(unknown_senders)
        return True

    def _queue_peer_refresh(self, uids: set[str]):
        self._pending_peer_uids.update(uids)
        if self._peer_refresh_task is None or self._peer_refresh_task.done():
            self._peer_refresh_task = asyncio.create_task(self._peer_refresh_loop())

    async def _peer_refresh_loop(self):
        """用户资料补全独立运行，不阻塞 WS 消息队列。"""
        while self._pending_peer_uids and self._running and not self._stop_event.is_set():
            now = time.monotonic()
            last = getattr(self, "_last_peer_refresh", 0.0)
            wait = max(0.0, 10.0 - (now - last))
            if wait:
                await asyncio.sleep(wait)
            uids = set(self._pending_peer_uids)
            self._pending_peer_uids.clear()
            self._last_peer_refresh = time.monotonic()
            await self._refresh_peer_info(uids)

    async def _refresh_peer_info(self, unknown_uids: set[str]):
        """异步拉取用户昵称+头像（httpx.AsyncClient 复用连接池）"""
        from dmshoot.storage import database
        headers = {
            "Cookie": self._cookie_str,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.douyin.com/",
        }
        async def fetch_one(uid: str):
            if self._stop_event.is_set():
                return False
            try:
                url = (
                    "https://www.douyin.com/aweme/v1/web/user/profile/other/"
                    f"?user_id={uid}&device_platform=webapp&aid=6383"
                    "&channel=channel_pc_web&source=channel_pc_web"
                )
                resp = await self._http.get(url, headers=headers)
                if resp.status_code != 200:
                    return False
                data = resp.json()
                user = data.get("user", {})
                nick = user.get("nickname", "")
                av_obj = (user.get("avatar_larger") or user.get("avatar_medium") or
                          user.get("avatar_thumb") or {})
                avatar = list(av_obj.get("url_list", []))[0] if av_obj.get("url_list") else ""
                if nick:
                    self._peer_cache[uid] = (nick, avatar)
                    sid = f"douyin:0:1:{uid}:{self._my_uid}:0:"
                    database.update_session_name_avatar(sid, nick, avatar)
                    self.bus.notify_session_updated(sid)
                    logger.info(f"抖音用户信息: {uid} → {nick}")
                    return True
            except Exception as e:
                logger.debug(f"抖音查用户 {uid} 失败: {e}")
            return False

        semaphore = asyncio.Semaphore(4)

        async def limited(uid: str):
            async with semaphore:
                return await fetch_one(uid)

        results = await asyncio.gather(
            *(limited(uid) for uid in unknown_uids),
            return_exceptions=True,
        )
        updated = sum(result is True for result in results)
        if updated:
            logger.info(f"抖音: 已更新 {updated} 个用户信息")

    async def _async_loop(self):
        """事件驱动消息循环；队列到达即唤醒，不再固定 500ms 轮询。"""
        import httpx
        backoff = ReconnectBackoff(min_s=1.0, max_s=30.0)
        loop = asyncio.get_running_loop()
        wakeup = asyncio.Event()
        ws = self._client.ws_receiver

        def notify():
            try:
                loop.call_soon_threadsafe(wakeup.set)
            except RuntimeError:
                pass

        if ws:
            ws.set_wakeup_callback(notify)
        async with httpx.AsyncClient(timeout=5, verify=False) as self._http:
            try:
                while self._running and not self._stop_event.is_set():
                    try:
                        wakeup.clear()
                        processed = await self._async_poll()
                        backoff.reset()
                        if processed or (ws and ws.queue_size):
                            continue
                        try:
                            await asyncio.wait_for(wakeup.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            pass
                    except Exception as e:
                        err_str = str(e)
                        if any(kw in err_str for kw in ["过期", "未登录", "invalid", "expired", "token"]):
                            self.on_error(ErrorCategory.AUTH, f"Cookie 已过期: {e}", e)
                            break
                        wait = backoff.fail()
                        self.on_error(ErrorCategory.NETWORK, f"消息处理失败(重试间隔{wait:.0f}s): {e}", e)
                        await asyncio.sleep(wait)
            finally:
                if ws:
                    ws.set_wakeup_callback(None)
                if self._peer_refresh_task and not self._peer_refresh_task.done():
                    self._peer_refresh_task.cancel()
