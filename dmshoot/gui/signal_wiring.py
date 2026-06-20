"""信号连接器 — 从 MainWindow 提取的 MessageBus 与 UI 组件信号连接"""


class SignalWiring:
    """MainWindow 中核心信号连接逻辑的提取。
    在 MainWindow 所有 UI 构建完成后调用 connect_all()。"""

    @staticmethod
    def connect_all(main_window, adapter_mgr, auth_ctrl):
        """连接所有核心信号 — 替代原来的 _connect_signals"""
        mw = main_window

        # 登录页 → 适配器 / 认证
        mw.page_login.connect_platform.connect(auth_ctrl.connect_platform)
        mw.page_login.start_monitor.connect(adapter_mgr.start_from_ui)
        mw.page_login.stop_monitor.connect(adapter_mgr.stop_from_ui)
        mw.page_login.clear_platform.connect(adapter_mgr.clear_platform)
        mw.page_login.auto_monitor.toggled.connect(adapter_mgr.on_auto_monitor_toggle)

        # DeepSeek 页
        mw.page_deepseek.save_clicked.connect(mw._save_deepseek)

        # 总线 → 主窗口
        mw.bus.new_message.connect(mw._on_new_message)
        mw.bus.platform_status.connect(auth_ctrl.on_platform_status)
        mw.bus.ai_response.connect(mw._on_ai_response)
        mw.bus.log.connect(mw._on_bus_log)
