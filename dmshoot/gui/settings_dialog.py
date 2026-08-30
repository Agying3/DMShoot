"""设置对话框"""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QCheckBox, QComboBox, QPushButton, QDoubleSpinBox,
    QGroupBox, QFormLayout, QSpinBox, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal

from dmshoot.storage.models import AppConfig
from dmshoot.storage import database
from dmshoot.gui.widgets.toast import show_toast


class GlassPopup(QDialog):
    """毛玻璃弹窗 — 替代 QMessageBox"""
    def __init__(self, parent=None, title="", text="", icon="info"):
        super().__init__(parent)
        self.setObjectName("glassPopup")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(324, 164)
        self._drag_pos = None
        self._perf_placeholder = None

        # 内嵌边框容器：dialog 比 outer 大 4px，留出 2px 青色边框
        wall = QHBoxLayout(self); wall.setContentsMargins(2, 2, 2, 2); wall.setSpacing(0)
        outer = QWidget()
        outer.setObjectName("glassFrame")
        outer.setStyleSheet("#glassFrame { background: #1e1e24; border: 1.5px solid rgba(0, 229, 255, 0.35); border-radius: 14px; }")
        wall.addWidget(outer)

        layout = QVBoxLayout(outer); layout.setContentsMargins(0, 0, 0, 0)

        # 标题栏（可拖拽）
        bar = QWidget(); bar.setFixedHeight(36)
        bar.setStyleSheet("background: transparent; border: none;")
        bar.mousePressEvent = self._title_mouse_press
        bar.mouseMoveEvent = self._title_mouse_move
        bar.mouseReleaseEvent = self._title_mouse_release
        bl = QHBoxLayout(); bl.setContentsMargins(18, 0, 8, 0)
        icon_label = QLabel({"info": "i", "warn": "!", "ok": "✓"}.get(icon, "i"))
        icon_label.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: rgba(255,255,255,0.5);"
            " background: rgba(255,255,255,0.08); border-radius: 10px;"
            " min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;"
            " qproperty-alignment: AlignCenter;")
        bl.addWidget(icon_label)
        tl = QLabel(title); tl.setStyleSheet("font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.75);")
        bl.addWidget(tl); bl.addStretch()
        bar.setLayout(bl); layout.addWidget(bar)

        # 内容
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 12px; padding: 8px 20px; background: transparent;")
        layout.addWidget(msg)
        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout(); btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn); btn_layout.setContentsMargins(0, 0, 16, 12)
        layout.addLayout(btn_layout)

    def _title_mouse_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()
    def _title_mouse_move(self, e):
        if self._drag_pos is not None:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()
    def _title_mouse_release(self, e):
        self._drag_pos = None


def show_glass_popup(parent, title, text, icon="info"):
    """显示毛玻璃弹窗（居中于父窗口）"""
    popup = GlassPopup(parent, title, text, icon)
    if parent:
        pg = parent.geometry()
        popup.move(pg.center() - popup.rect().center())
    popup.exec_()


class SettingsDialog(QDialog):
    """全局设置对话框"""
    cache_cleared = Signal(str)  # platform name
    cache_clear_finished = Signal(bool, str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        # 设置页使用独立草稿；保存时只合并本页拥有的字段，不能覆盖扫码等并发更新。
        self.config = database.load_config()
        self._cache_clear_button = None
        self.cache_clear_finished.connect(self._on_cache_clear_finished)
        self.setWindowTitle("DMShoot 设置")
        self.setMinimumSize(550, 620)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None

        # ── 外墙：留 4px 给光晕/阴影 ──
        wall = QHBoxLayout(self)
        wall.setContentsMargins(4, 4, 4, 4)
        wall.setSpacing(0)

        # ── 主容器：毛玻璃背景 + 圆角 + 细边框 ──
        container = QWidget()
        container.setObjectName("settingsContainer")
        container.setStyleSheet(
            "#settingsContainer {"
            "  background: rgba(24,24,30,0.94);"
            "  border: 1.5px solid rgba(255,255,255,0.08);"
            "  border-radius: 14px;"
            "}"
            "QGroupBox { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06);"
            " border-radius: 10px; margin-top: 12px; padding-top: 18px;"
            " font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.7); }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
            "QLineEdit { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);"
            " border-radius: 6px; padding: 6px 10px; color: rgba(255,255,255,0.85); font-size: 12px; }"
            "QTabWidget::pane { border: none; background: transparent; }"
            "QTabBar::tab { background: rgba(255,255,255,0.04); border: none; border-radius: 8px;"
            " padding: 6px 16px; margin: 2px; color: rgba(255,255,255,0.5); font-size: 12px; }"
            "QTabBar::tab:selected { background: rgba(255,255,255,0.10); color: rgba(255,255,255,0.9); }"
            "QSpinBox { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);"
            " border-radius: 6px; padding: 4px 8px; color: rgba(255,255,255,0.85); }"
        )
        wall.addWidget(container)

        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 标题栏（在容器内，有背景）──
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background: transparent;")
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(18, 0, 8, 0)
        tb_title = QLabel("设置")
        tb_title.setStyleSheet("font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.75);")
        tb_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 不拦截拖拽
        tb_layout.addWidget(tb_title)
        tb_layout.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.08); border: none; border-radius: 14px;"
            " color: rgba(255,255,255,0.45); font-size: 12px; }"
            "QPushButton:hover { background: rgba(232,17,35,0.55); color: #fff; }")
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)
        main_layout.addWidget(title_bar)

        # ── 内容区（外层滚动，防止 PerfChart 撑大后按钮不可见）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(20, 8, 20, 16)

        # 标签页
        tabs = QTabWidget()
        tabs.addTab(self._create_reply_tab(), "回复")
        self._theme_placeholder = QWidget()
        tabs.addTab(self._theme_placeholder, "主题")
        tabs.addTab(self._create_data_tab(), "数据")
        self._perf_placeholder = QWidget()
        tabs.addTab(self._perf_placeholder, "性能")
        tabs.addTab(self._create_debug_tab(), "调试")
        tabs.currentChanged.connect(self._on_tab_changed)
        inner_layout.addWidget(tabs)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        inner_layout.addLayout(btn_layout)

        scroll.setWidget(inner)
        main_layout.addWidget(scroll)

    def _title_mouse_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()
    def _title_mouse_move(self, e):
        if self._drag_pos is not None:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()
    def _title_mouse_release(self, e):
        self._drag_pos = None

    def _create_reply_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout()

        reply_group = QGroupBox("自动回复设置")
        form = QFormLayout()

        self.auto_reply_enabled = QCheckBox("启用自动AI回复")
        self.auto_reply_enabled.setChecked(self.config.auto_reply_enabled)
        form.addRow(self.auto_reply_enabled)

        self.delay_min = QDoubleSpinBox()
        self.delay_min.setRange(0, 60)
        self.delay_min.setDecimals(1)
        self.delay_min.setSingleStep(0.5)
        self.delay_min.setValue(self.config.reply_delay_min)
        self.delay_min.setSuffix(" 秒")
        form.addRow("最小延迟:", self.delay_min)

        self.delay_max = QDoubleSpinBox()
        self.delay_max.setRange(self.delay_min.value(), 120)
        self.delay_max.setDecimals(1)
        self.delay_max.setSingleStep(0.5)
        self.delay_max.setValue(max(self.config.reply_delay_min, self.config.reply_delay_max))
        self.delay_max.setSuffix(" 秒")
        form.addRow("最大延迟:", self.delay_max)
        self.delay_min.valueChanged.connect(self.delay_max.setMinimum)

        self.context_rounds = QSpinBox()
        self.context_rounds.setRange(1, 50)
        self.context_rounds.setValue(self.config.max_context_rounds)
        self.context_rounds.setSuffix(" 轮")
        form.addRow("上下文轮数:", self.context_rounds)

        reply_group.setLayout(form)
        layout.addWidget(reply_group)

        # ── 发送限流 ──
        rate_group = QGroupBox("发送限流（防平台风控）")
        rate_form = QFormLayout()
        rate_form.setSpacing(6)

        self.rate_douyin = QSpinBox()
        self.rate_douyin.setRange(1, 60); self.rate_douyin.setValue(self.config.rate_douyin)
        self.rate_douyin.setSuffix(" 条/秒")
        rate_form.addRow("抖音:", self.rate_douyin)

        self.rate_bilibili = QSpinBox()
        self.rate_bilibili.setRange(1, 60); self.rate_bilibili.setValue(self.config.rate_bilibili)
        self.rate_bilibili.setSuffix(" 条/秒")
        rate_form.addRow("B站:", self.rate_bilibili)

        # self.rate_xhs = QSpinBox()  # 小红书已废弃
        # self.rate_xhs.setRange(1, 50); self.rate_xhs.setValue(3)
        # self.rate_xhs.setSuffix(" 条/秒")
        # rate_form.addRow("小红书:", self.rate_xhs)

        self.rate_ks = QSpinBox()
        self.rate_ks.setRange(1, 60); self.rate_ks.setValue(self.config.rate_kuaishou)
        self.rate_ks.setSuffix(" 条/秒")
        rate_form.addRow("快手:", self.rate_ks)

        rate_group.setLayout(rate_form)
        layout.addWidget(rate_group)

        layout.addStretch()

        w.setLayout(layout)
        return w

    def _create_data_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        cache_group = QGroupBox("聊天缓存")
        cache_layout = QFormLayout(cache_group)
        clear_btn = QPushButton("清除抖音聊天缓存")
        clear_btn.setToolTip("删除缓存文件和抖音消息记录，不清理登录信息")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.clicked.connect(self._on_clear_douyin_cache)
        cache_layout.addRow("抖音:", clear_btn)
        layout.addWidget(cache_group)
        layout.addStretch()
        return w

    def _create_theme_tab(self) -> QWidget:
        """主题页 — 聊天背景壁纸设置"""
        w = QWidget()
        layout = QVBoxLayout()

        wp_group = QGroupBox("聊天背景壁纸")
        wp_layout = QVBoxLayout()
        wp_layout.setSpacing(8)

        # 画廊横排（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(140)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:horizontal { height: 4px; background: rgba(255,255,255,0.03); }"
            "QScrollBar::handle:horizontal { background: rgba(255,255,255,0.15); border-radius: 2px; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
        )

        self._wp_gallery_widget = QWidget()
        self._wp_gallery_widget.setStyleSheet("background: transparent;")
        self._wp_gallery_layout = QHBoxLayout(self._wp_gallery_widget)
        self._wp_gallery_layout.setContentsMargins(0, 0, 0, 0)
        self._wp_gallery_layout.setSpacing(10)
        self._wp_gallery_layout.addStretch()  # 右端弹簧
        scroll.setWidget(self._wp_gallery_widget)

        wp_layout.addWidget(scroll)

        # 控制行：下拉选择 + 按钮
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self._wp_combo = QComboBox()
        self._wp_combo.setMinimumWidth(180)
        self._wp_combo.setCursor(Qt.PointingHandCursor)
        self._wp_combo.setStyleSheet(
            "QComboBox { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);"
            "border-radius: 6px; padding: 4px 8px; color: rgba(255,255,255,0.85); font-size: 12px; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
            "QComboBox::down-arrow { image: none; }"
            "QComboBox QAbstractItemView { background: #1e1e24; color: rgba(255,255,255,0.85);"
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 6px;"
            "selection-background-color: rgba(0,229,255,0.15); outline: none; }"
        )
        self._wp_combo.currentIndexChanged.connect(self._on_wp_combo_changed)
        ctrl_row.addWidget(self._wp_combo)

        self.wp_select_btn = QPushButton("添加壁纸")
        self.wp_select_btn.setCursor(Qt.PointingHandCursor)
        self.wp_select_btn.setFixedWidth(80)
        self.wp_select_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);"
            "border-radius: 6px; padding: 4px 10px; color: rgba(255,255,255,0.7); font-size: 12px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.10); }"
        )
        self.wp_select_btn.clicked.connect(self._on_select_wallpaper)
        ctrl_row.addWidget(self.wp_select_btn)

        self.wp_delete_btn = QPushButton("删除选中")
        self.wp_delete_btn.setObjectName("dangerBtn")
        self.wp_delete_btn.setCursor(Qt.PointingHandCursor)
        self.wp_delete_btn.setFixedWidth(72)
        self.wp_delete_btn.clicked.connect(self._on_delete_wallpaper)
        ctrl_row.addWidget(self.wp_delete_btn)
        ctrl_row.addStretch()
        wp_layout.addLayout(ctrl_row)

        # 选中信息行
        self.wp_path_label = QLabel()
        self.wp_path_label.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        self.wp_path_label.setWordWrap(True)
        wp_layout.addWidget(self.wp_path_label)

        self.wp_perf_label = QLabel()
        self.wp_perf_label.setStyleSheet("color: rgba(255,255,255,0.35); font-size: 11px;")
        wp_layout.addWidget(self.wp_perf_label)

        wp_group.setLayout(wp_layout)
        layout.addWidget(wp_group)

        layout.addStretch()

        # 初始化画廊
        self._rebuild_wallpaper_gallery()

        w.setLayout(layout)
        return w

    def _create_perf_tab(self) -> QWidget:
        """性能监控页 — 图表"""
        from dmshoot.gui.widgets.perf_chart import PerfChart, PerfWindow

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        try:
            self._perf_chart = PerfChart(parent=w, compact=True)
        except Exception as e:
            self._perf_chart = QLabel(f"图表初始化失败: {e}")
            self._perf_chart.setStyleSheet("color:#f38ba8;font-size:12px;padding:20px;")
        layout.addWidget(self._perf_chart)

        # 按钮行：开关 + 弹出窗口
        toggle_layout = QHBoxLayout()
        self._perf_toggle = QCheckBox("启用性能监控")
        self._perf_toggle.setChecked(self.config.perf_monitor_enabled)
        self._perf_toggle.setStyleSheet(
            "color: rgba(255,255,255,0.6); font-size: 12px;"
        )
        toggle_layout.addWidget(self._perf_toggle)
        toggle_layout.addStretch()

        pop_btn = QPushButton("📊 弹出窗口")
        pop_btn.setFixedWidth(100)
        pop_btn.setCursor(Qt.PointingHandCursor)
        pop_btn.setStyleSheet(
            "QPushButton { background: rgba(137,180,250,0.15); color: #89b4fa;"
            "border: 1px solid rgba(137,180,250,0.25); border-radius: 6px;"
            "padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: rgba(137,180,250,0.25); }"
        )
        pop_btn.clicked.connect(lambda: PerfWindow.open(parent=self))
        toggle_layout.addWidget(pop_btn)
        layout.addLayout(toggle_layout)

        # 包裹在可滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return scroll
    
    def _on_tab_changed(self, index: int):
        """按需创建壁纸和性能页，避免打开设置时解码图片和初始化图表。"""
        from PySide6.QtWidgets import QTabWidget
        tabs = self.sender()
        if not tabs:
            return
        placeholder = tabs.widget(index)
        if placeholder is self._theme_placeholder:
            real_tab = self._create_theme_tab()
            tabs.removeTab(index)
            tabs.insertTab(index, real_tab, "主题")
            tabs.setCurrentIndex(index)
            self._theme_placeholder = None
            return
        if placeholder is not self._perf_placeholder:
            return
        try:
            # 替换占位为真实 perf tab
            real_tab = self._create_perf_tab()
            tabs.removeTab(index)
            tabs.insertTab(index, real_tab, "性能")
            tabs.setCurrentIndex(index)
        except Exception as e:
            tabs.removeTab(index)
            fallback = QLabel(f"性能监控初始化失败: {e}")
            fallback.setStyleSheet("color:#f38ba8;font-size:12px;padding:20px;")
            tabs.insertTab(index, fallback, "性能")
            tabs.setCurrentIndex(index)

    def tick_perf(self):
        """每秒 tick — 从主窗口定时器调用"""
        if hasattr(self, '_perf_chart') and self._perf_chart:
            try:
                self._perf_chart.tick()
            except Exception:
                pass

    def _create_debug_tab(self) -> QWidget:
        """调试标签页 — 保存后统一应用，取消不会留下运行时副作用。"""
        from dmshoot.utils.console_log import is_log_enabled
        import json as _json
        w = QWidget()
        layout = QVBoxLayout()

        hint = QLabel("勾选后在终端显示对应调试信息。")
        hint.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px; padding-bottom: 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 从配置恢复上次的调试开关状态
        saved = {}
        if self.config.debug_log_levels:
            try:
                saved = _json.loads(self.config.debug_log_levels)
            except Exception:
                pass

        categories = [
            ("ai_thinking", "AI 思考过程"),
            ("message_sync", "消息同步"),
            ("heartbeat", "适配器心跳"),
            ("polling", "WS 队列状态"),
            ("ws_batch", "WS 批处理统计"),
            ("api_timing", "API 耗时"),
            ("debug", "详细调试日志"),
        ]
        self._debug_checks: dict[str, QCheckBox] = {}
        for key, label in categories:
            cb = QCheckBox(label)
            # 优先使用保存的配置，否则读取当前内存状态
            if key in saved:
                default = saved[key]
            else:
                default = is_log_enabled(key)
            cb.setChecked(default)
            self._debug_checks[key] = cb
            layout.addWidget(cb)

        layout.addStretch()
        w.setLayout(layout)
        return w

    def _save_debug(self):
        """持久化调试开关到 config"""
        import json as _json
        state = {key: cb.isChecked() for key, cb in self._debug_checks.items()}
        self.config.debug_log_levels = _json.dumps(state)

    # ── 壁纸画廊操作 ──

    _THUMB_W, _THUMB_H = 160, 90

    def _make_default_thumbnail(self) -> "QPixmap":
        """生成默认壁纸缩略图（从 resources/b2.jpg 缩放）"""
        from PySide6.QtGui import QPixmap, QImage
        default_path = Path(__file__).parent.parent.parent / "resources" / "b2.jpg"
        if default_path.exists():
            img = QImage(str(default_path))
            pix = QPixmap.fromImage(img).scaled(
                self._THUMB_W, self._THUMB_H, Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
        else:
            # 兜底：纯色
            pix = QPixmap(self._THUMB_W, self._THUMB_H)
            pix.fill(Qt.GlobalColor.transparent)
        return pix

    def _rebuild_wallpaper_gallery(self):
        """重建画廊：默认 + 所有已添加壁纸"""
        from PySide6.QtGui import QPixmap, QImage
        # 清空旧缩略图
        layout = self._wp_gallery_layout
        while layout.count() > 1:  # 保留末尾 stretch
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        active = self.config.wallpaper_path

        def _make_card(thumb: QPixmap, label: str, path: str, is_default: bool = False):
            """创建一张可点击的壁纸卡片"""
            card = QPushButton()
            card.setFixedSize(self._THUMB_W + 6, self._THUMB_H + 28)
            card.setCursor(Qt.PointingHandCursor)
            is_active = (is_default and not active) or (not is_default and path == active)
            border = "1.5px solid rgba(255,255,255,0.28)" if is_active else "1.5px solid rgba(255,255,255,0.10)"
            card.setStyleSheet(
                f"QPushButton {{ background: transparent; border: {border}; border-radius: 8px; padding: 2px; }}"
                f"QPushButton:hover {{ border-color: rgba(255,255,255,0.25); }}"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(2, 2, 2, 0)
            inner.setSpacing(2)

            img_lbl = QLabel()
            img_lbl.setFixedSize(self._THUMB_W, self._THUMB_H)
            img_lbl.setPixmap(thumb.scaled(self._THUMB_W, self._THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            img_lbl.setAlignment(Qt.AlignCenter)
            img_lbl.setStyleSheet("border-radius: 5px; background: rgba(0,0,0,0.3);")
            img_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            inner.addWidget(img_lbl)

            name_lbl = QLabel(label)
            name_lbl.setAlignment(Qt.AlignCenter)
            name_lbl.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 10px; background: transparent;")
            name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            inner.addWidget(name_lbl)

            if is_default:
                card.clicked.connect(self._on_switch_to_default)
            else:
                card.clicked.connect(lambda checked, p=path: self._on_switch_wallpaper(p))
            return card

        # 默认壁纸卡片
        default_card = _make_card(self._make_default_thumbnail(), "默认壁纸", "", is_default=True)
        layout.insertWidget(0, default_card)

        # 自定义壁纸卡片
        for path in self.config.wallpaper_gallery:
            if path and Path(path).exists():
                img = QImage(path)
                thumb = QPixmap.fromImage(img)
                label = Path(path).stem[:16]
                card = _make_card(thumb, label, path)
                layout.insertWidget(layout.count() - 1, card)  # 插入到 stretch 前

        self._update_wp_info()
        self._populate_wp_combo()

    def _update_wp_info(self):
        """更新壁纸信息标签"""
        from PySide6.QtGui import QImage
        path = self.config.wallpaper_path
        if path and Path(path).exists():
            img = QImage(path)
            w, h = img.width(), img.height()
            mem_mb = (w * h * 4) / (1024 * 1024)
            name = Path(path).name
            self.wp_path_label.setText(f"当前: {name}  |  {w}×{h}  |  16:9 ✓")
            self.wp_perf_label.setText(f"性能: {mem_mb:.1f} MB VRAM  |  {int(mem_mb * 1.5)} MB 内存")
        else:
            self.wp_path_label.setText("当前: 默认壁纸")
            self.wp_perf_label.setText("性能: 0 MB")

    def _populate_wp_combo(self):
        """填充壁纸下拉框（在重建画廊时调用）"""
        combo = self._wp_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("默认壁纸", "")
        for path in self.config.wallpaper_gallery:
            if path and Path(path).exists():
                name = Path(path).stem[:24]
                combo.addItem(name, path)
        active = self.config.wallpaper_path or ""
        idx = combo.findData(active)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_wp_combo_changed(self, idx: int):
        """下拉框切换壁纸"""
        if idx < 0:
            return
        path = self._wp_combo.itemData(idx)
        self.config.wallpaper_path = path or ""
        self._rebuild_wallpaper_gallery()

    def _on_switch_to_default(self):
        self.config.wallpaper_path = ""
        self._rebuild_wallpaper_gallery()

    def _on_switch_wallpaper(self, path: str):
        self.config.wallpaper_path = path
        self._rebuild_wallpaper_gallery()

    def _on_select_wallpaper(self):
        from PySide6.QtWidgets import QFileDialog
        from PySide6.QtGui import QImage
        path, _ = QFileDialog.getOpenFileName(
            self, "选择壁纸", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            show_glass_popup(self, "错误", "无法加载图片", "warn")
            return
        w, h = img.width(), img.height()
        ratio = w / h if h else 0
        if abs(ratio - 16/9) > 0.05:
            show_glass_popup(self, "比例不符", f"仅支持 16:9 比例\n当前: {w}x{h} ≈ {ratio:.2f}:1", "warn")
            return
        # 去重
        if path in self.config.wallpaper_gallery:
            self.config.wallpaper_path = path
        else:
            self.config.wallpaper_gallery.append(path)
            self.config.wallpaper_path = path
        self._rebuild_wallpaper_gallery()

    def _on_delete_wallpaper(self):
        target = self.config.wallpaper_path
        if not target:  # 默认壁纸不能删
            show_glass_popup(self, "提示", "默认壁纸无法删除", "info")
            return
        if target in self.config.wallpaper_gallery:
            self.config.wallpaper_gallery.remove(target)
        self.config.wallpaper_path = ""
        self._rebuild_wallpaper_gallery()

    def _on_clear_douyin_cache(self):
        """后台清除聊天记录和缓存，不触碰登录信息。"""
        btn = self.sender()
        if not btn or not btn.isEnabled():
            return
        self._cache_clear_button = btn
        btn.setEnabled(False)
        btn.setText("清除中...")
        import threading
        threading.Thread(
            target=self._clear_douyin_cache_worker,
            name="douyin-cache-clear",
            daemon=True,
        ).start()

    def _clear_douyin_cache_worker(self):
        try:
            from dmshoot.utils.douyin_im_sync import clear_douyin_cache
            clear_douyin_cache()
            self.cache_clear_finished.emit(True, "")
        except Exception as e:
            self.cache_clear_finished.emit(False, str(e))

    def _on_cache_clear_finished(self, ok: bool, error: str):
        btn = self._cache_clear_button
        self._cache_clear_button = None
        if btn:
            btn.setEnabled(True)
            btn.setText("清除抖音聊天缓存")
        if ok:
            self.cache_cleared.emit("douyin")
            show_toast(self, "缓存已清除，正在重新拉取数据", "success")
        else:
            show_glass_popup(self, "错误", f"清除失败: {error}", "warn")

    def reject(self):
        """草稿未写入共享配置，取消可直接关闭。"""
        super().reject()

    def _on_save(self):
        """保存设置"""
        self._save_debug()
        updates = {
            "auto_reply_enabled": self.auto_reply_enabled.isChecked(),
            "reply_delay_min": self.delay_min.value(),
            "reply_delay_max": max(self.delay_min.value(), self.delay_max.value()),
            "max_context_rounds": self.context_rounds.value(),
            "rate_douyin": self.rate_douyin.value(),
            "rate_bilibili": self.rate_bilibili.value(),
            "rate_kuaishou": self.rate_ks.value(),
            "wallpaper_path": self.config.wallpaper_path,
            "wallpaper_gallery": list(self.config.wallpaper_gallery),
            "debug_log_levels": self.config.debug_log_levels,
        }
        if hasattr(self, '_perf_toggle'):
            updates["perf_monitor_enabled"] = self._perf_toggle.isChecked()

        # 认证字段不进入该事务，扫码线程更新 Cookie 时不会被设置页覆盖。
        database.update_config_fields(updates)
        self.config = database.load_config()

        # 运行时设置在持久化成功后统一应用。
        from dmshoot.core.rate_limiter import get_limiter
        get_limiter("douyin").set_rate(self.config.rate_douyin)
        get_limiter("bilibili").set_rate(self.config.rate_bilibili)
        get_limiter("kuaishou").set_rate(self.config.rate_kuaishou)
        from dmshoot.core.perf_monitor import get_monitor
        get_monitor().set_enabled(self.config.perf_monitor_enabled)
        from dmshoot.utils.console_log import set_log_level
        import json as _json
        for key, enabled in _json.loads(self.config.debug_log_levels or "{}").items():
            set_log_level(key, enabled)

        self.accept()
