"""DMShoot 自动化截图测试 — 启动应用、等待各模块就绪、截图验证"""
import sys
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORT_DIR = PROJECT_ROOT / "docs" / "test_screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

report_lines = []
ts = lambda: datetime.now().strftime("%H:%M:%S")

def log(msg):
    line = f"[{ts()}] {msg}"
    print(line)
    report_lines.append(line)

log("=== DMShoot 自动化测试开始 ===")

# ── 1. DB 状态快照 ──
log("--- DB 状态 ---")
from dmshoot.storage import database
database.init_database()
conn = database._get_conn()

for platform in ("douyin", "bilibili", "xiaohongshu"):
    s = conn.execute("SELECT COUNT(*) FROM sessions WHERE platform=?", (platform,)).fetchone()[0]
    m = conn.execute("SELECT COUNT(*) FROM messages WHERE platform=?", (platform,)).fetchone()[0]
    names = conn.execute(
        "SELECT peer_name FROM sessions WHERE platform=? LIMIT 6", (platform,)
    ).fetchall()
    log(f"  {platform}: {s}会话 {m}消息 | {', '.join(n['peer_name'] for n in names)}")

# ── 2. 配置状态 ──
log("--- 配置状态 ---")
cfg = database.load_config()
log(f"  抖音cookie: {'有' if cfg.douyin_cookie else '无'} ({len(cfg.douyin_cookie)}chars)")
log(f"  B站sessdata: {'有' if cfg.bilibili_sessdata else '无'}")
log(f"  AI key: {'有' if cfg.api_key else '无'}, model={cfg.model}")

# ── 3. 头像缓存 ──
log("--- 头像缓存 ---")
avatar_dir = PROJECT_ROOT / "dmshoot" / "data" / "avatars"
if avatar_dir.exists():
    pngs = list(avatar_dir.glob("*.png"))
    fails = list(avatar_dir.glob("*.fail"))
    log(f"  已缓存: {len(pngs)}个头像, {len(fails)}个失败")
else:
    log("  头像目录不存在")

# ── 4. 启动 GUI ──
log("--- 启动 GUI ---")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer

app = QApplication.instance() or QApplication(sys.argv)
app.setApplicationName("DMShootTest")

from dmshoot.gui.main_window import MainWindow

window = MainWindow()
window.show()
app.processEvents()

# 等 2 秒让界面渲染
def take_screenshot(name, description):
    QApplication.processEvents()
    path = str(REPORT_DIR / f"{name}.png")
    window.grab().save(path)
    size = Path(path).stat().st_size
    log(f"  截图: {name} ({size//1024}KB) — {description}")

take_screenshot("00_startup", "启动首页")

# ── 5. 检查 login page ──
log("--- 登录页状态 ---")
try:
    lp = window.page_login
    dy_status = lp.dy_status.text() if hasattr(lp, 'dy_status') else "?"
    bili_status = lp.bili_status.text() if hasattr(lp, 'bili_status') else "?"
    log(f"  抖音: {dy_status}")
    log(f"  B站: {bili_status}")
    log(f"  自动监听: {'勾选' if lp.auto_monitor.isChecked() else '未勾选'}")
except Exception as e:
    log(f"  登录页读取失败: {e}")

# ── 6. 检查 home page ──
log("--- 首页状态 ---")
try:
    hp = window.page_home
    contacts = hp.contacts
    widget_count = contacts.list.count() if hasattr(contacts, 'list') else 0
    log(f"  通讯录条目: {widget_count}")
    log(f"  当前平台: {hp._current_platform}")
    log(f"  消息缓存: {len(hp._msg_cache)} 个会话")
except Exception as e:
    log(f"  首页读取失败: {e}")

take_screenshot("01_home", "首页通讯录+空对话")

# ── 7. 检查 sidebar ──
log("--- 侧边栏状态 ---")
try:
    sb = window.sidebar
    for name, lbl in [("抖音", sb.status_dy), ("B站", sb.status_bili), ("小红书", sb.status_xhs), ("AI", sb.status_ai)]:
        log(f"  {name}: {lbl.text()}")
except Exception as e:
    log(f"  侧边栏读取失败: {e}")

take_screenshot("02_sidebar", "侧边栏状态")

# ── 8. 切到提示词页面 ──
window.sidebar._buttons["prompt"].click()
app.processEvents()
QTimer.singleShot(500, lambda: None)
app.processEvents()
take_screenshot("03_prompt", "提示词页面")

# ── 9. 切回首页 ──
window.sidebar._buttons["home"].click()
app.processEvents()
QTimer.singleShot(500, lambda: None)
app.processEvents()

# ── 10. 检查 monitor panel ──
log("--- 监控面板 ---")
try:
    mp = window.monitor
    log(f"  可见: {mp.isVisible()}")
    log(f"  日志条目: {mp._entry_count}")
except Exception as e:
    log(f"  监控面板读取失败: {e}")

take_screenshot("04_monitor", "监控面板")

# ── 11. 适配器状态 ──
log("--- 适配器状态 ---")
try:
    adapters = window._adapters if hasattr(window, '_adapters') else {}
    for p, a in adapters.items():
        running = a.isRunning() if hasattr(a, 'isRunning') else "?"
        log(f"  {p}: {running}")
    if not adapters:
        log("  无运行中的适配器")
except Exception as e:
    log(f"  适配器状态读取失败: {e}")

# ── 12. 输出报告 ──
log("=== 测试完成 ===")

# 写报告
report = "\n".join(report_lines)
report_path = REPORT_DIR / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
report_path.write_text(report, encoding="utf-8")
log(f"报告: {report_path}")

# 截图目录
pngs = sorted(REPORT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
log(f"截图: {len(pngs)}张")

for line in report_lines:
    if "❌" in line or "失败" in line or "0消息" in line:
        log(f"⚠️  问题发现: {line}")

app.quit()
