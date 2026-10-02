## API — HTTP 客户端，封装所有后端 REST API 调用
##
## 通过 HTTP 与 Python 后端通信，所有方法返回 Dictionary 或 Array。
## 后端地址: http://127.0.0.1:9876
extends Node

const BASE_URL := "http://127.0.0.1:9876"

var _http: HTTPRequest
var _pending: Dictionary = {}  # 待处理请求


func _ready() -> void:
	_http = HTTPRequest.new()
	add_child(_http)


# ──── 通用请求 ────

func _do_request(method: HTTPClient.Method, path: String, body: Dictionary = {}) -> Dictionary:
	var url = BASE_URL + path
	var json_body = JSON.stringify(body) if not body.is_empty() else ""
	var headers = ["Content-Type: application/json"]

	var err = _http.request(url, headers, method, json_body)
	if err != OK:
		return {"ok": false, "error": "network_error", "detail": "请求发送失败: %d" % err}

	var result = await _http.request_completed
	var response_code = result[1]
	var response_body = result[3].get_string_from_utf8()

	if response_code == 0:
		return {"ok": false, "error": "network_error", "detail": "无法连接后端"}

	var data = JSON.parse_string(response_body)
	if data == null:
		return {"ok": false, "error": "parse_error", "detail": "响应解析失败"}

	if response_code >= 400:
		return {"ok": false, "error": data.get("error", "unknown"), "detail": data.get("detail", str(data))}

	return data


func _do_get(path: String) -> Dictionary:
	return await _do_request(HTTPClient.METHOD_GET, path)


func _do_post(path: String, body: Dictionary) -> Dictionary:
	return await _do_request(HTTPClient.METHOD_POST, path, body)


func _do_put(path: String, body: Dictionary) -> Dictionary:
	return await _do_request(HTTPClient.METHOD_PUT, path, body)


# ──── 健康检查 ────

func health() -> Dictionary:
	return await _do_get("/api/health")


# ──── 适配器 ────

func get_adapter_status() -> Dictionary:
	return await _do_get("/api/adapter/status")


func start_adapter(platform: String, auto_reply: bool = true) -> Dictionary:
	return await _do_post("/api/adapter/start", {
		"platform": platform,
		"auto_reply": auto_reply,
	})


func stop_adapter(platform: String) -> Dictionary:
	return await _do_post("/api/adapter/stop", {
		"platform": platform,
	})


# ──── 登录 ────

func scan_login(platform: String) -> Dictionary:
	return await _do_post("/api/login/scan", {
		"platform": platform,
	})


func cancel_login(platform: String) -> Dictionary:
	return await _do_post("/api/login/cancel", {
		"platform": platform,
	})


# ──── 消息 ────

func get_sessions(platform: String = "") -> Dictionary:
	var path = "/api/sessions"
	if platform != "":
		path += "?platform=" + platform
	return await _do_get(path)


func get_messages(session_id: String, limit: int = 50) -> Dictionary:
	var path = "/api/messages/" + session_id.uri_encode() + "?limit=" + str(limit)
	return await _do_get(path)


func send_message(session_id: String, text: String) -> Dictionary:
	return await _do_post("/api/message/send", {
		"session_id": session_id,
		"text": text,
	})


# ──── AI ────

func ai_active(session_id: String, persona: String = "") -> Dictionary:
	return await _do_post("/api/ai/active", {
		"session_id": session_id,
		"persona": persona,
	})


func ai_test() -> Dictionary:
	return await _do_get("/api/ai/test")


# ──── 配置 ────

func get_config() -> Dictionary:
	return await _do_get("/api/config")


func update_config(data: Dictionary) -> Dictionary:
	return await _do_put("/api/config", data)


# ──── 提示词 ────

func get_prompts() -> Dictionary:
	return await _do_get("/api/prompts")


func save_prompt(name: String, content: String, type_hint: String = "role") -> Dictionary:
	return await _do_put("/api/prompts", {
		"name": name,
		"content": content,
		"type": type_hint,
	})


# ──── 性能 ────

func get_perf_snapshot() -> Dictionary:
	return await _do_get("/api/perf/snapshot")
