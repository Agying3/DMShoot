## AppState — 全局状态管理器
##
## 管理整个应用的运行时状态：平台连接、当前页面、会话列表、
## 未读消息等。所有页面通过 AppState 读取和响应状态变化。
extends Node

# ──── 信号 ────

## 平台连接状态变化
signal platform_status_changed(platform: String, status: String)
## 新消息到达
signal new_message_received(session_id: String, msg: Dictionary)
## 会话列表更新
signal sessions_updated(sessions: Array)
## 当前页面切换
signal page_changed(page_name: String)

## 调试日志
signal log_added(level: String, source: String, message: String)

# ──── 状态枚举 ────

enum Page {
	LOGIN,
	CHAT,
	SETTINGS,
	AI_SETTINGS,
	PROMPTS,
	PERF,
}

# ──── 状态变量 ────

## 当前活跃页面
var current_page: Page = Page.LOGIN

## 平台状态: { "douyin": "online"|"offline"|"connecting", ... }
var platform_status: Dictionary = {}

## 会话列表
var sessions: Array = []

## 当前选中的会话 ID
var active_session_id: String = ""

## 每个会话的未读计数: { session_id: int }
var unread_map: Dictionary = {}

## 每个会话的消息列表缓存: { session_id: Array[Dictionary] }
var message_cache: Dictionary = {}

## 配置快照
var config: Dictionary = {}

## 提示词列表
var prompts: Dictionary = {}
var active_prompt: String = ""
var behavior_presets: Dictionary = {}
var active_behavior: String = ""

## 总未读数
var total_unread: int = 0

## 性能快照
var perf_snapshot: Dictionary = {}

## AI 是否在生成中
var ai_generating: bool = false
var ai_stream_session: String = ""
var ai_stream_buffer: String = ""

var recent_logs: Array = []
const MAX_LOGS := 200


# ──── 初始化 ────

func _ready() -> void:
	# 默认所有平台离线
	platform_status = {
		"douyin": "offline",
		"bilibili": "offline",
		"kuaishou": "offline",
		"xiaohongshu": "offline",
	}


# ──── 平台状态 ────

func set_platform_status(platform: String, status: String) -> void:
	var old = platform_status.get(platform, "")
	if old != status:
		platform_status[platform] = status
		platform_status_changed.emit(platform, status)


func is_platform_online(platform: String) -> bool:
	return platform_status.get(platform, "offline") == "online"


# ──── 会话管理 ────

func set_sessions(new_sessions: Array) -> void:
	sessions = new_sessions
	_update_total_unread()
	sessions_updated.emit(sessions)


func _update_total_unread() -> void:
	total_unread = 0
	for s in sessions:
		total_unread += s.get("unread", 0)


func select_session(session_id: String) -> void:
	active_session_id = session_id
	# 清零该会话未读
	if session_id in unread_map:
		unread_map[session_id] = 0
		_update_total_unread()
	page_changed.emit("chat")


# ──── 消息管理 ────

func cache_messages(session_id: String, messages: Array) -> void:
	message_cache[session_id] = messages


func add_message_to_cache(session_id: String, msg: Dictionary) -> void:
	if session_id not in message_cache:
		message_cache[session_id] = []
	message_cache[session_id].append(msg)


func get_cached_messages(session_id: String) -> Array:
	return message_cache.get(session_id, [])


# ──── 页面导航 ────

func switch_page(page: Page) -> void:
	current_page = page
	match page:
		Page.LOGIN:
			page_changed.emit("login")
		Page.CHAT:
			page_changed.emit("chat")
		Page.SETTINGS:
			page_changed.emit("settings")
		Page.AI_SETTINGS:
			page_changed.emit("ai_settings")
		Page.PROMPTS:
			page_changed.emit("prompts")
		Page.PERF:
			page_changed.emit("perf")


# ──── 配置 ────

func update_config(new_config: Dictionary) -> void:
	for key in new_config:
		config[key] = new_config[key]


func add_log(level: String, source: String, message: String) -> void:
	recent_logs.push_back({"level": level, "source": source, "message": message, "time": Time.get_time_string_from_system()})
	if recent_logs.size() > MAX_LOGS:
		recent_logs.pop_front()
	log_added.emit(level, source, message)
