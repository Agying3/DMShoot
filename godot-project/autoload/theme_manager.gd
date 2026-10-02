## ThemeManager — 主题管理器
##
## 管理应用的暗色/亮色主题切换，提供统一配色变量。
extends Node

# ──── 信号 ────

signal theme_changed(theme_name: String)

# ──── 暗色主题配色 ────

const DARK_THEME := {
	# 背景
	"bg_primary": Color("#0d0d1a"),
	"bg_secondary": Color("#16162a"),
	"bg_tertiary": Color("#1e1e34"),
	"bg_card": Color("#141428"),
	"bg_input": Color("#1e1e36"),

	# 文字
	"text_primary": Color("#e0e0e0"),
	"text_secondary": Color("#a0a0b0"),
	"text_muted": Color("#606070"),
	"text_inverse": Color("#121212"),

	# 强调色
	"accent_primary": Color("#6c63ff"),
	"accent_secondary": Color("#4ec9b0"),
	"accent_warning": Color("#ffb347"),
	"accent_danger": Color("#ff6b6b"),

	# 平台色
	"platform_douyin": Color("#ff0044"),
	"platform_bilibili": Color("#00a1d6"),
	"platform_kuaishou": Color("#ff4906"),
	"platform_xiaohongshu": Color("#ff2442"),

	# 状态色
	"status_online": Color("#4ec95b"),
	"status_offline": Color("#606070"),
	"status_connecting": Color("#ffb347"),

	# 边框
	"border_light": Color("#ffffff", 0.06),
	"border_normal": Color("#ffffff", 0.1),
	"border_strong": Color("#ffffff", 0.15),

	# 消息气泡
	"bubble_self": Color("#6c63ff", 0.3),
	"bubble_other": Color("#ffffff", 0.08),

	# 导航
	"nav_bg": Color("#16162a"),
	"nav_active": Color("#6c63ff", 0.2),
	"nav_text": Color("#a0a0b0"),
	"nav_text_active": Color("#e0e0e0"),

	# 滚动条
	"scrollbar_bg": Color("#ffffff", 0.05),
	"scrollbar_thumb": Color("#ffffff", 0.15),

	# 分隔线
	"separator": Color("#ffffff", 0.06),

	# 阴影
	"shadow_color": Color("#000000", 0.3),
}

# ──── 亮色主题配色 ────

const LIGHT_THEME := {
	"bg_primary": Color("#f5f5f7"),
	"bg_secondary": Color("#ffffff"),
	"bg_tertiary": Color("#e8e8ec"),
	"bg_card": Color("#ffffff"),
	"bg_input": Color("#e8e8ec"),

	"text_primary": Color("#1a1a2e"),
	"text_secondary": Color("#555566"),
	"text_muted": Color("#888899"),
	"text_inverse": Color("#ffffff"),

	"accent_primary": Color("#5a52e0"),
	"accent_secondary": Color("#3ba890"),
	"accent_warning": Color("#e6992e"),
	"accent_danger": Color("#e05555"),

	"platform_douyin": Color("#ff0044"),
	"platform_bilibili": Color("#00a1d6"),
	"platform_kuaishou": Color("#ff4906"),
	"platform_xiaohongshu": Color("#ff2442"),

	"status_online": Color("#3ba84e"),
	"status_offline": Color("#9999aa"),
	"status_connecting": Color("#e6992e"),

	"border_light": Color("#000000", 0.06),
	"border_normal": Color("#000000", 0.1),
	"border_strong": Color("#000000", 0.15),

	"bubble_self": Color("#5a52e0", 0.15),
	"bubble_other": Color("#000000", 0.06),

	"nav_bg": Color("#ebebf0"),
	"nav_active": Color("#5a52e0", 0.1),
	"nav_text": Color("#666678"),
	"nav_text_active": Color("#1a1a2e"),

	"scrollbar_bg": Color("#000000", 0.05),
	"scrollbar_thumb": Color("#000000", 0.12),

	"separator": Color("#000000", 0.08),

	"shadow_color": Color("#000000", 0.08),
}

# ──── 状态 ────

var current_theme: String = "dark"
var colors: Dictionary = DARK_THEME


# ──── 主题切换 ────

func set_theme(theme_name: String) -> void:
	match theme_name:
		"dark":
			colors = DARK_THEME.duplicate()
			current_theme = "dark"
		"light":
			colors = LIGHT_THEME.duplicate()
			current_theme = "light"
		_:
			push_warning("[ThemeManager] 未知主题: %s, 使用暗色" % theme_name)
			colors = DARK_THEME.duplicate()
			current_theme = "dark"

	theme_changed.emit(current_theme)


func toggle_theme() -> void:
	if current_theme == "dark":
		set_theme("light")
	else:
		set_theme("dark")


# ──── 便捷访问 ────

func get_color(key: String) -> Color:
	return colors.get(key, Color.WHITE)


func get_platform_color(platform: String) -> Color:
	return colors.get("platform_" + platform, colors.get("accent_primary", Color.WHITE))


func get_status_color(status: String) -> Color:
	return colors.get("status_" + status, colors.get("text_muted", Color.GRAY))


func get_stylebox_flat(color: Color, radius: float = 8.0) -> StyleBoxFlat:
	var sb = StyleBoxFlat.new()
	sb.bg_color = color
	sb.corner_radius_top_left = radius
	sb.corner_radius_top_right = radius
	sb.corner_radius_bottom_left = radius
	sb.corner_radius_bottom_right = radius
	return sb


func get_stylebox_border(color: Color, width: int = 1, radius: float = 8.0) -> StyleBoxFlat:
	var sb = StyleBoxFlat.new()
	sb.bg_color = Color.TRANSPARENT
	sb.border_width_left = width
	sb.border_width_right = width
	sb.border_width_top = width
	sb.border_width_bottom = width
	sb.border_color = color
	sb.corner_radius_top_left = radius
	sb.corner_radius_top_right = radius
	sb.corner_radius_bottom_left = radius
	sb.corner_radius_bottom_right = radius
	return sb
