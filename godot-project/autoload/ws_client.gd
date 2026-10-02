## WSClient — WebSocket 客户端，接收后端实时推送
##
## 连接 ws://127.0.0.1:9876/ws，处理所有实时事件：
## - 新消息到达 → AppState.new_message_received
## - 平台状态变化 → AppState.platform_status_changed
## - 二维码推送 → login 页面显示
## - AI 流式内容 → 聊天页实时显示
## - 日志 → 按需显示
extends Node

signal connected()
signal disconnected()
signal qr_code_received(platform: String, base64_data: String)
signal login_ok(platform: String)
signal login_fail(platform: String, reason: String)
signal ai_stream_chunk(session_id: String, chunk: String, done: bool)
signal log_received(level: String, source: String, message: String)

const WS_URL := "ws://127.0.0.1:9876/ws"

var _ws: WebSocketPeer
var _connected: bool = false
var _reconnect_timer: Timer
var _heartbeat_timer: Timer
var _should_reconnect: bool = true


func _ready() -> void:
	_ws = WebSocketPeer.new()
	_ws.supported_protocols = ["json"]

	# 重连定时器
	_reconnect_timer = Timer.new()
	_reconnect_timer.wait_time = 3.0
	_reconnect_timer.one_shot = true
	_reconnect_timer.timeout.connect(_try_connect)
	add_child(_reconnect_timer)

	# 心跳定时器
	_heartbeat_timer = Timer.new()
	_heartbeat_timer.wait_time = 30.0
	_heartbeat_timer.timeout.connect(_send_heartbeat)
	add_child(_heartbeat_timer)


func connect_to_server() -> void:
	_should_reconnect = true
	var err = _ws.connect_to_url(WS_URL)
	if err != OK:
		push_warning("[WS] 连接失败: %d, 3秒后重试..." % err)
		_reconnect_timer.start()


func disconnect_from_server() -> void:
	_should_reconnect = false
	_ws.close()
	_connected = false
	_heartbeat_timer.stop()


func _try_connect() -> void:
	if not _should_reconnect:
		return
	connect_to_server()


func _send_heartbeat() -> void:
	if _connected:
		_ws.send_text(JSON.stringify({"event": "ping"}))


func _process(_delta: float) -> void:
	_ws.poll()

	var state = _ws.get_ready_state()
	match state:
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
				_heartbeat_timer.start()
				connected.emit()
			_read_messages()
		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_connected = false
				_heartbeat_timer.stop()
				disconnected.emit()
				if _should_reconnect:
					_reconnect_timer.start()
		WebSocketPeer.STATE_CLOSING:
			pass  # 等待关闭完成


func _read_messages() -> void:
	while _ws.get_available_packet_count() > 0:
		var payload = _ws.get_packet().get_string_from_utf8()
		_handle_message(payload)


func _handle_message(raw: String) -> void:
	var data = JSON.parse_string(raw)
	if data == null:
		return

	var event = data.get("event", "")
	match event:
		"new_message":
			var msg = data.get("data", {})
			var sid = msg.get("session_id", "")
			AppState.add_message_to_cache(sid, msg)
			AppState.new_message_received.emit(sid, msg)

		"platform_status":
			var platform = data.get("platform", "")
			var status = data.get("status", "offline")
			AppState.set_platform_status(platform, status)

		"qr_code":
			var platform = data.get("platform", "")
			var b64 = data.get("data", "")
			qr_code_received.emit(platform, b64)

		"login_ok":
			var platform = data.get("platform", "")
			AppState.set_platform_status(platform, "online")
			login_ok.emit(platform)

		"login_fail":
			var platform = data.get("platform", "")
			var reason = data.get("detail", "未知错误")
			AppState.set_platform_status(platform, "offline")
			login_fail.emit(platform, reason)

		"ai_stream":
			var sid = data.get("session_id", "")
			var chunk = data.get("chunk", "")
			var done = data.get("done", false)
			ai_stream_chunk.emit(sid, chunk, done)

		"system_error":
			var error_type = data.get("error", "unknown")
			var detail = data.get("detail", "")
			system_error.emit(error_type, detail)

		"perf_snapshot":
			AppState.perf_snapshot = data.get("data", {})

		"log":
			var lvl = data.get("level", "INFO")
			var src = data.get("source", "")
			var msg = data.get("message", "")
			log_received.emit(lvl, src, msg)
			AppState.add_log(lvl, src, msg)

		"pong":
			pass  # 心跳响应

		_:
			push_warning("[WS] 未知事件: %s" % event)
