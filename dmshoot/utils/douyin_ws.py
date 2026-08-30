"""抖音 WebSocket 消息接收器 — 包装 DouyinRecvMsg

在后台线程运行 WebSocket，将收到的私信推送到线程安全队列。
适配器通过 dequeue 获取新消息。
"""

import json
import queue
import threading
import time

from dmshoot.utils.console_log import get_logger

logger = get_logger(__name__)


def _decode_timestamp(server_msg_id: int, conv_short_id: int) -> float:
    """从抖音IM消息ID解码真实Unix时间戳

    server_message_id / conversation_short_id 可能的编码:
      1. Snowflake (>= 1e18): 高32位存Unix秒 → id >> 32
      2. 微秒级 (16+ 位数字, >= 1e15) → id / 1e6
      3. 毫秒级 (13 位数字, >= 1e12) → id / 1e3
      兜底: time.time()
    """
    ids = [v for v in (server_msg_id, conv_short_id) if v and v > 0]
    now = time.time()
    for vid in ids:
        if vid >= 1_000_000_000_000_000_000:  # >= 1e18, Snowflake → 高32位=秒
            ts = vid >> 32
        elif vid >= 10_000_000_000_000_000:  # >= 1e16, 微秒级
            ts = vid / 1_000_000
        elif vid >= 1_000_000_000_000:      # >= 1e12, 毫秒级
            ts = vid / 1_000
        elif vid >= 1_000_000_000:          # >= 1e9, 尝试
            ts = vid
        else:
            continue
        # 验证合理性: +/- 90天范围内（protobuf 历史消息可能是几个月前的）
        if abs(ts - now) < 86400 * 180:
            return ts
    return now


class DouyinWSReceiver:
    """抖音 WebSocket 私信接收器

    用法:
        receiver = DouyinWSReceiver(auth)
        receiver.start()
        # ...
        msg = receiver.get_message(timeout=1.0)  # 阻塞获取
        receiver.stop()
    """

    def __init__(self, auth, on_state=None):
        self._auth = auth
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._ws = None
        self._connected = False
        self._stop_event = threading.Event()
        self._callback_lock = threading.Lock()
        self._wakeup_callback = None
        self._state_callback = on_state

    def start(self):
        """启动 WebSocket 后台线程"""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_ws, daemon=True, name="douyin-ws")
        self._thread.start()
        logger.success("WebSocket 接收器已启动")

    def stop(self):
        """停止 WebSocket"""
        self._running = False
        self._connected = False
        self._stop_event.set()
        self._notify_wakeup()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("抖音 WebSocket 接收器已停止")

    def set_wakeup_callback(self, callback):
        """设置队列到达通知；回调可安全唤醒另一个 asyncio 事件循环。"""
        with self._callback_lock:
            self._wakeup_callback = callback
        if callback and not self._queue.empty():
            self._notify_wakeup()

    def _notify_wakeup(self):
        with self._callback_lock:
            callback = self._wakeup_callback
        if callback:
            try:
                callback()
            except Exception:
                pass

    def _emit_state(self, state: str, message: str = ""):
        callback = self._state_callback
        if callback:
            try:
                callback(state, message)
            except Exception:
                logger.debug("WS 状态回调异常", exc_info=True)

    def get_message(self, timeout: float = 0.1):
        """非阻塞获取一条消息，如果没有返回 None"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_all_messages(self) -> list:
        """获取队列中所有消息（非阻塞）"""
        msgs = []
        while True:
            m = self.get_message(timeout=0)
            if m is None:
                break
            msgs.append(m)
        return msgs

    def get_messages_batch(self, max_items: int = 100) -> list:
        """按上限取一批消息，避免突发流量长时间占用适配器线程。"""
        msgs = []
        for _ in range(max(1, max_items)):
            try:
                msgs.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return msgs

    @property
    def queue_size(self) -> int:
        """队列中待处理消息数"""
        return self._queue.qsize()

    @property
    def connected(self) -> bool:
        return self._connected

    # ── 内部 ──

    def _run_ws(self):
        """WebSocket 主循环，在后台线程运行，自动重连"""
        # 确保 SDK 路径在 sys.path（dy_apis 内部使用 from douyin_api import ...）
        import sys
        from pathlib import Path
        _SDK = Path(__file__).parent.parent.parent / "external" / "DouYin_Spider"
        if str(_SDK) not in sys.path:
            sys.path.insert(0, str(_SDK))
        _SDK_DY = _SDK / "dy_apis"
        if str(_SDK_DY) not in sys.path:
            sys.path.insert(0, str(_SDK_DY))

        reconnect_delay = 3  # 连续握手失败时指数退避

        while self._running:
            wrapped = None
            try:
                self._connected = False
                self._emit_state("connecting", "WS 连接中")
                wrapped = _WrappedWS(
                    self._auth,
                    self._queue,
                    on_message_ready=self._notify_wakeup,
                    on_open=self._on_open,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws = wrapped
                wrapped.start()  # 阻塞，直到连接断开
            except Exception as e:
                logger.warning(f"抖音 WS 异常: {type(e).__name__}: {e}")
                self._emit_state("connecting", f"WS 异常，准备重连: {e}")
            finally:
                self._connected = False

            if not self._running:
                break

            # 成功握手过就回到短重连；只有连续握手失败才指数退避。
            delay = 3 if wrapped and wrapped.was_opened else reconnect_delay
            reconnect_delay = 3 if wrapped and wrapped.was_opened else min(reconnect_delay * 2, 60)
            logger.warning(f"WebSocket 断开，{delay}秒后重连...")
            self._emit_state("connecting", f"WS 已断开，{delay} 秒后重连")
            if self._stop_event.wait(delay):
                break

        self._connected = False
        logger.info("抖音 WS 线程退出")

    def _on_open(self):
        self._connected = True
        self._emit_state("online", "WS 已连接")

    def _on_error(self, error):
        self._connected = False
        self._emit_state("connecting", f"WS 异常: {error}")

    def _on_close(self, code, message):
        self._connected = False
        detail = f"code={code}" if code is not None else "连接关闭"
        if message:
            detail += f" {str(message)[:60]}"
        self._emit_state("connecting", detail)


class _WrappedWS:
    """包装 DouyinRecvMsg，将消息推入队列（不处理重连，由外层循环负责）"""
    
    def __init__(self, auth, msg_queue, on_message_ready=None,
                 on_open=None, on_error=None, on_close=None):
        self._auth = auth
        self._msg_queue = msg_queue
        self._inner = None
        self._ws_app = None
        self._on_message_ready = on_message_ready
        self._on_open_callback = on_open
        self._on_error_callback = on_error
        self._on_close_callback = on_close
        self.was_opened = False

    def start(self):
        """创建 DouyinRecvMsg 实例并启动 WebSocket（阻塞）"""
        from dy_apis.douyin_recv_msg import DouyinRecvMsg
        import websocket

        inner = DouyinRecvMsg(self._auth, auto_reconnect=False)
        inner.on_message = self._make_on_message(inner)
        self._inner = inner

        # 直接用 WebSocketApp，加 ping 心跳防止服务端断连
        self._ws_app = websocket.WebSocketApp(
            url=inner.url,
            header={
                'Pragma': 'no-cache',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'User-Agent': inner.auth.cookie.get('user-agent', 'Mozilla/5.0'),
                'Cache-Control': 'no-cache',
                'Sec-WebSocket-Protocol': 'binary, base64, pbbp2',
                'Sec-WebSocket-Extensions': 'permessage-deflate; client_max_window_bits',
            },
            cookie=inner.auth.cookie_str,
            on_message=inner.on_message,
            on_error=self._handle_error,
            on_close=self._handle_close,
            on_open=self._handle_open,
        )
        self._ws_app.run_forever(
            origin='https://www.douyin.com',
            ping_interval=15,
            ping_timeout=5,
            ping_payload='ping',
        )

    def _handle_open(self, ws):
        self.was_opened = True
        logger.success("WS已连接 ✓")
        if self._on_open_callback:
            self._on_open_callback()

    def _handle_error(self, ws, error):
        logger.warning(f"WS异常: {error}")
        if self._on_error_callback:
            self._on_error_callback(error)

    def _handle_close(self, ws, code, message):
        logger.warning(
            f"WS断开 (code={code})" + (f" msg={str(message)[:60]}" if message else "")
        )
        if self._on_close_callback:
            self._on_close_callback(code, message)

    def close(self):
        if self._ws_app:
            try:
                self._ws_app.close()
            except Exception:
                pass
        elif self._inner and self._inner.ws:
            try:
                self._inner.ws.close()
            except Exception:
                pass

    def _make_on_message(self, inner):
        """返回 on_message 回调函数 —— 解析 protobuf 并推入队列"""
        msg_queue = self._msg_queue

        def on_message(ws, message):
            try:
                from static import Live_pb2, Response_pb2

                frame = Live_pb2.PushFrame()
                frame.ParseFromString(message)

                if frame.payloadType == 'pb':
                    response = Response_pb2.Response()
                    response.ParseFromString(frame.payload)

                    notify = response.body.new_message_notify
                    if notify and notify.message:
                        msg_data = notify.message
                        sender_uid = str(msg_data.sender)
                        content_raw = json.loads(msg_data.content) if msg_data.content else {}
                        msg_type = msg_data.message_type
                        conversation_id = str(msg_data.conversation_id)
                        conversation_short_id = msg_data.conversation_short_id
                        index = msg_data.index_in_conversation
                        server_msg_id = msg_data.server_message_id

                        # 从 server_message_id 推导真实时间戳
                        # 抖音 IM 的 server_message_id 编码可能是：
                        #   1) 微秒级 epoch (16位数字) → /1e6
                        #   2) 毫秒级 epoch (13位数字) → /1e3
                        #   3) Snowflake (高位时间戳) → >>22 + epoch_offset
                        real_ts = _decode_timestamp(server_msg_id, conversation_short_id)

                        # 全量接收，不设 msg_type 过滤
                        text = content_raw.get("text", "") or content_raw.get("content", "")
                        if text:
                            msg_queue.put({
                                "platform": "douyin",
                                "sender_uid": sender_uid,
                                "content": text,
                                "conversation_id": conversation_id,
                                "conversation_short_id": str(conversation_short_id),
                                "msg_index": index,
                                "server_message_id": str(server_msg_id or ""),
                                "msg_type": "text",
                                "timestamp": real_ts,
                            })
                            if self._on_message_ready:
                                self._on_message_ready()
            except Exception as e:
                logger.debug(f"抖音 WS 消息解析异常: {e}")

        return on_message
