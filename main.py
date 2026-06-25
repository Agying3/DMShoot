"""DMShoot 启动入口"""

import sys
import os
import traceback
from pathlib import Path

# PyInstaller 打包后使用 _MEIPASS 临时目录
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── 终端日志（最早初始化）──
try:
    from dmshoot.utils.console_log import setup_console_logging
    setup_console_logging()
except Exception:
    pass  # PyInstaller 环境可能 import 失败，等 GUI 启动后再处理


def _ensure_playwright():
    """首次启动自动安装 Playwright Chromium（~300MB）"""
    pw_browsers = Path.home() / "AppData" / "Local" / "ms-playwright"
    if pw_browsers.exists() and any(pw_browsers.glob("chromium-*")):
        return
    print("[*] 首次启动 — 安装 Playwright Chromium (~300MB)...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception:
        import subprocess
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=False)
    print("[OK] Chromium 已就绪")


def main():
    """启动 AI 值守监控台"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtCore import Qt

        app = QApplication(sys.argv)
        app.setAttribute(Qt.AA_UseSoftwareOpenGL)
        app.setApplicationName("DMShoot")
        app.setOrganizationName("DMShoot")

        # 后台安装 Playwright Chromium
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, _ensure_playwright)

        from dmshoot.gui.main_window import MainWindow
        window = MainWindow()
        window.show()

        code = app.exec()
        _safe_cleanup(window, app)
        sys.exit(code)

    except Exception as e:
        # PyInstaller 环境无控制台，弹窗显示错误
        err = "".join(traceback.format_exception_only(e))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "DMShoot 启动失败", f"{err}")
        except Exception:
            print(f"FATAL: {err}", file=sys.stderr)
        sys.exit(1)


def _safe_cleanup(window, app):
    """清理 Qt 对象 + 数据库，记录异常但不中断退出"""
    import logging
    logger = logging.getLogger("dmshoot.cleanup")

    # 1. 销毁窗口（调度 deleteLater，让 Qt 事件循环处理）
    try:
        window.deleteLater()
    except Exception:
        logger.warning("窗口 deleteLater 异常", exc_info=True)

    # 2. 处理待处理事件（让 deleteLater 生效）
    app.processEvents()

    # 3. 销毁 QApplication
    try:
        app.deleteLater()
    except Exception:
        logger.warning("app deleteLater 异常", exc_info=True)

    # 4. 确保 WAL checkpoint 已执行（atexit 也会触发，但显式调用更可靠）
    try:
        from dmshoot.storage.database import _checkpoint_on_exit
        _checkpoint_on_exit()
    except Exception:
        pass  # atexit 已有兜底，此处静默


if __name__ == "__main__":
    if "--profile" in sys.argv:
        import cProfile, pstats, io
        from datetime import datetime
        prof_path = BASE_DIR / "docs" / f"profile_{datetime.now().strftime('%m%d_%H%M')}.prof"
        print(f"[PROFILE] 启动性能分析，输出: {prof_path}")
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            main()
        finally:
            profiler.disable()
            profiler.dump_stats(str(prof_path))
            s = io.StringIO()
            ps = pstats.Stats(profiler, stream=s).sort_stats("cumtime")
            ps.print_stats(30)
            print(f"[PROFILE] 已保存: {prof_path}")
            print(s.getvalue())
    else:
        main()
