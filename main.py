"""DMShoot 启动入口"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 终端日志（最早初始化）──
from dmshoot.utils.console_log import setup_console_logging
setup_console_logging()


def main():
    """启动 AI 值守监控台"""
    from PySide6.QtWidgets import QApplication
    from dmshoot.gui.main_window import MainWindow

    # 避免 QThread 退出警告
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    # 强制软件渲染，避免 QtCharts GPU 驱动 segfault
    from PySide6.QtCore import Qt
    app.setAttribute(Qt.AA_UseSoftwareOpenGL)
    app.setApplicationName("DMShoot")
    app.setOrganizationName("DMShoot")

    window = MainWindow()
    window.show()

    code = app.exec()
    try:
        window.deleteLater()
    except Exception:
        pass
    app.processEvents()
    app.deleteLater()
    sys.exit(code)


if __name__ == "__main__":
    if "--profile" in sys.argv:
        import cProfile, pstats, io
        from datetime import datetime
        prof_path = PROJECT_ROOT / "docs" / f"profile_{datetime.now().strftime('%m%d_%H%M')}.prof"
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
