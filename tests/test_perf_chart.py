"""性能页圆盘选择与视觉布局回归测试，不访问真实消息数据库。"""

import math
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from dmshoot.core.perf_monitor import PerfMonitor
from dmshoot.gui.widgets.perf_chart import (
    PerfChart, PerfWindow, _CHART_NAMES, _ChartPieSelector, _MetricCard, _MetricCardLight,
)


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if not getattr(QtTestCase, "_font_loaded", False):
            font_path = Path(__file__).resolve().parents[1] / "tools/fonts/AaCute-UI.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                cls.app.setFont(QFont(families[0]))
                QFont.insertSubstitution("Segoe UI", families[0])
            QtTestCase._font_loaded = True

    def flush(self):
        self.app.processEvents()

    def destroy(self, widget):
        widget.close()
        widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.flush()


class TestChartPieSelector(QtTestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.setWindowFlags(Qt.FramelessWindowHint)
        self.host.move(0, 0)
        self.host.resize(520, 400)
        layout = QVBoxLayout(self.host)
        self.selector = _ChartPieSelector(self.host)
        layout.addWidget(self.selector)
        layout.addStretch()
        self.changes = []
        self.previews = []
        self.selector.currentIndexChanged.connect(self.changes.append)
        self.selector.previewIndexChanged.connect(self.previews.append)
        self.host.show()
        self.flush()
        self.popup = self.selector._popup

    def tearDown(self):
        self.popup.hide()
        self.destroy(self.host)

    def open_menu(self, index=0):
        self.selector.setCurrentIndex(index)
        self.changes.clear()
        self.previews.clear()
        QTest.mouseClick(self.selector._button, Qt.LeftButton)
        self.flush()
        self.assertTrue(self.popup.isVisible())

    def sector_point(self, index, radius=None):
        radius = radius if radius is not None else self.popup.width() / 2 - 22
        angle = math.radians(-90 + index * 60)
        center = self.popup._center()
        return QPoint(round(center.x() + radius * math.cos(angle)), round(center.y() + radius * math.sin(angle)))

    def hold_menu(self, index=0):
        self.selector.setCurrentIndex(index)
        self.changes.clear()
        self.previews.clear()
        QTest.mouseMove(self.selector._button, self.selector._button.rect().center())
        self.flush()
        QTest.mousePress(self.selector._button, Qt.LeftButton)
        self.assertFalse(self.popup.isVisible())
        QTest.qWait(self.selector._button._hold_timer.interval() + 40)
        self.flush()
        self.assertTrue(self.popup.isVisible())
        self.assertTrue(self.popup._drag_selecting)
        self.assertFalse(self.selector._button.isDown())
        self.assertIsNone(self.selector._preview_index)
        self.assertEqual(self.previews, [])

    def test_short_click_still_opens_normal_menu(self):
        self.open_menu(5)
        self.assertFalse(self.popup._drag_selecting)
        self.assertFalse(self.selector._button._hold_timer.isActive())
        QTest.qWait(self.selector._button._hold_timer.interval() + 40)
        self.assertTrue(self.popup.isVisible())
        self.assertFalse(self.popup._drag_selecting)
        self.assertEqual(self.changes, [])

    def test_release_outside_before_hold_threshold_does_not_open_menu(self):
        button = self.selector._button
        QTest.mousePress(button, Qt.LeftButton)
        QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(-100, -100))
        QTest.qWait(button._hold_timer.interval() + 40)
        self.flush()
        self.assertFalse(button._hold_timer.isActive())
        self.assertFalse(self.popup.isVisible())
        self.assertFalse(self.popup._drag_selecting)
        self.assertEqual(self.changes, [])

    def test_hold_drag_release_selects_each_sector_once(self):
        for index in range(6):
            with self.subTest(index=index):
                previous = (index + 1) % 6
                self.hold_menu(previous)
                QTest.mouseMove(self.popup, self.sector_point(index))
                self.flush()
                self.assertEqual(self.popup._hover_index, index)
                self.assertEqual(self.selector.currentIndex(), previous)
                self.assertEqual(self.changes, [])
                self.assertEqual(self.previews, [index])
                self.assertEqual(self.selector._label.text(), _CHART_NAMES[index])
                QTest.mouseRelease(self.popup, Qt.LeftButton, pos=self.sector_point(index))
                self.flush()
                self.assertFalse(self.popup.isVisible())
                self.assertFalse(self.popup._drag_selecting)
                self.assertEqual(self.selector.currentIndex(), index)
                self.assertEqual(self.changes, [index])
                self.assertEqual(self.previews, [index])
                self.assertEqual(self.selector._caption.text(), "图表视图")

    def test_drag_release_on_native_button_selects_once(self):
        self.hold_menu(5)
        button = self.popup._buttons[1]
        QTest.mouseMove(button, button.rect().center())
        self.flush()
        self.assertEqual(self.popup._hover_index, 1)
        self.assertEqual(self.previews, [1])
        QTest.mouseRelease(button, Qt.LeftButton)
        self.flush()
        self.assertFalse(self.popup.isVisible())
        self.assertEqual(self.changes, [1])

    def test_drag_release_delivered_to_trigger_uses_global_position(self):
        self.hold_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(1))
        self.flush()
        button = self.selector._button
        point = button.mapFromGlobal(self.popup.mapToGlobal(self.sector_point(2)))
        QTest.mouseRelease(button, Qt.LeftButton, pos=point)
        self.flush()
        self.assertEqual(self.changes, [2])
        self.assertFalse(self.popup.isVisible())
        self.assertFalse(button.isDown())
        self.open_menu(2)
        self.assertFalse(self.popup._drag_selecting)

    def test_drag_release_in_center_outside_or_on_trigger_cancels(self):
        self.host.move(0, 200)
        self.flush()
        destinations = (
            (self.popup._center_button, self.popup._center_button.rect().center()),
            (self.host, QPoint(self.host.width() - 4, 4)),
            (self.selector._button, self.selector._button.rect().center()),
        )
        for destination, point in destinations:
            with self.subTest(destination=destination.objectName()):
                self.hold_menu(5)
                QTest.mouseMove(self.popup, self.sector_point(1))
                self.flush()
                QTest.mouseRelease(destination, Qt.LeftButton, pos=point)
                self.flush()
                self.assertFalse(self.popup.isVisible())
                self.assertFalse(self.popup._drag_selecting)
                self.assertEqual(self.selector.currentIndex(), 5)
                self.assertEqual(self.changes, [])
                self.assertEqual(self.previews, [1, 5])
                self.assertEqual(self.selector._label.text(), "消息分析")

    def test_escape_during_drag_does_not_reopen_on_release(self):
        self.hold_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(1))
        self.flush()
        QTest.keyClick(self.popup._buttons[5], Qt.Key_Escape)
        QTest.mouseRelease(self.selector._button, Qt.LeftButton)
        self.flush()
        self.assertFalse(self.popup.isVisible())
        self.assertFalse(self.popup._drag_selecting)
        self.assertFalse(self.selector._button.isDown())
        self.assertEqual(self.changes, [])
        self.assertEqual(self.previews, [1, 5])

    def test_hiding_owner_cancels_pending_hold_and_active_drag(self):
        QTest.mousePress(self.selector._button, Qt.LeftButton)
        self.host.hide()
        QTest.qWait(self.selector._button._hold_timer.interval() + 40)
        self.assertFalse(self.popup.isVisible())
        self.assertFalse(self.selector._button._hold_timer.isActive())
        self.assertFalse(self.selector._button.isDown())
        QTest.mouseRelease(self.selector._button, Qt.LeftButton)
        self.host.show()
        self.flush()
        self.hold_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(1))
        self.flush()
        self.host.hide()
        self.flush()
        self.assertFalse(self.popup.isVisible())
        self.assertFalse(self.popup._drag_selecting)
        self.assertEqual(self.popup._hover_animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.changes, [])
        self.assertEqual(self.previews, [1, 5])
        QTest.mouseRelease(self.selector._button, Qt.LeftButton)

    def test_drag_previews_all_options_without_committing_or_repeating(self):
        self.hold_menu(5)
        for index, button in enumerate(self.popup._buttons):
            QTest.mouseMove(button, button.rect().center())
            self.flush()
            self.assertEqual(self.selector.currentIndex(), 5)
            self.assertEqual(self.selector._label.text(), _CHART_NAMES[index])
            self.assertEqual(self.selector._caption.text(), "预览 · 松开确认")
            self.assertEqual(self.popup._center_button.text(), "预览\n" + button.text())
            previewed = self.previews.copy()
            QTest.mouseMove(self.popup, self.sector_point(index))
            self.flush()
            self.assertEqual(self.previews, previewed)
            self.assertEqual(self.changes, [])
        self.assertEqual(self.previews, list(range(6)))
        QTest.mouseRelease(self.popup._buttons[5], Qt.LeftButton)
        self.flush()
        self.assertFalse(self.popup.isVisible())
        self.assertIsNone(self.selector._preview_index)
        self.assertEqual(self.selector._caption.text(), "图表视图")
        self.assertEqual(self.changes, [])
        self.assertEqual(self.previews, list(range(6)))

    def test_hovering_center_restores_original_and_can_preview_again(self):
        self.hold_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(1))
        QTest.mouseMove(self.popup._center_button, self.popup._center_button.rect().center())
        self.flush()
        self.assertTrue(self.popup.isVisible())
        self.assertEqual(self.previews, [1, 5])
        self.assertIsNone(self.selector._preview_index)
        self.assertEqual(self.popup._center_button.text(), "当前\n消息分析")
        QTest.mouseMove(self.popup, self.sector_point(2))
        self.flush()
        self.assertEqual(self.previews, [1, 5, 2])
        self.assertEqual(self.changes, [])
        QTest.mouseRelease(self.popup, Qt.LeftButton, pos=self.sector_point(2))
        self.flush()
        self.assertEqual(self.changes, [2])
        self.assertEqual(self.previews, [1, 5, 2])

    def test_releasing_original_option_restores_without_commit_signal(self):
        self.hold_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(1))
        self.flush()
        QTest.mouseRelease(self.popup, Qt.LeftButton, pos=self.sector_point(5))
        self.flush()
        self.assertEqual(self.selector.currentIndex(), 5)
        self.assertEqual(self.previews, [1, 5])
        self.assertEqual(self.changes, [])
        self.assertIsNone(self.selector._preview_index)
        self.assertFalse(self.popup.isVisible())

    def test_index_signal_contract(self):
        self.assertEqual(self.selector.currentIndex(), 0)
        self.assertEqual(self.selector._button.size().width(), 44)
        self.selector.setCurrentIndex(5)
        self.selector.setCurrentIndex(5)
        self.selector.setCurrentIndex(-1)
        self.selector.setCurrentIndex(6)
        self.assertEqual(self.changes, [5])
        self.assertEqual(self.selector._label.text(), "消息分析")

    def test_every_sector_switches_once_and_closes(self):
        for index in range(6):
            with self.subTest(index=index):
                self.open_menu((index + 1) % 6)
                QTest.mouseClick(self.popup, Qt.LeftButton, pos=self.sector_point(index))
                self.flush()
                self.assertEqual(self.changes, [index])
                self.assertEqual(self.selector.currentIndex(), index)
                self.assertFalse(self.popup.isVisible())

    def test_native_buttons_select_their_original_indices(self):
        for index in range(6):
            with self.subTest(index=index):
                self.open_menu((index + 1) % 6)
                button = self.popup._buttons[index]
                self.assertEqual(button.toolTip(), _CHART_NAMES[index])
                self.assertEqual(button.accessibleName(), _CHART_NAMES[index])
                QTest.mouseClick(button, Qt.LeftButton)
                self.assertEqual(self.selector.currentIndex(), index)

    def test_hover_does_not_change_selection(self):
        self.open_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(2))
        self.flush()
        self.assertEqual(self.popup._hover_index, 2)
        self.assertEqual(self.selector.currentIndex(), 5)
        self.assertEqual(self.changes, [])
        self.assertEqual(self.previews, [])

    def test_hover_crossfades_and_retargets_from_current_brightness(self):
        self.open_menu(5)
        QTest.mouseMove(self.popup._center_button, self.popup._center_button.rect().center())
        QTest.mouseMove(self.popup, self.sector_point(0))
        self.flush()
        animation = self.popup._hover_animation
        animation.setCurrentTime(animation.duration() // 2)
        self.assertGreater(self.popup._hover_levels[0], 0)
        self.assertLess(self.popup._hover_levels[0], 1)
        image = self.popup.grab().toImage()
        point = self.sector_point(0)
        shade = image.pixelColor(
            round(point.x() * image.devicePixelRatio()),
            round(point.y() * image.devicePixelRatio()),
        )
        colors = self.selector.colors()
        self.assertGreater(shade.red(), QColor(colors["sector"]).red())
        self.assertLess(shade.red(), QColor(colors["hover"]).red())
        QTest.mouseMove(self.popup, self.sector_point(1))
        self.flush()
        animation.setCurrentTime(0)
        self.assertEqual(self.popup._hover_levels, self.popup._hover_from)
        previous = self.popup._hover_levels[0]
        self.assertGreater(previous, 0)
        animation.setCurrentTime(animation.duration() // 2)
        self.assertGreater(self.popup._hover_levels[0], 0)
        self.assertLess(self.popup._hover_levels[0], previous)
        self.assertGreater(self.popup._hover_levels[1], 0)
        self.assertLess(self.popup._hover_levels[1], 1)
        animation.setCurrentTime(animation.duration())
        self.assertEqual(self.popup._hover_levels, [0.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.selector.currentIndex(), 5)
        self.assertEqual(self.changes, [])

    def test_surface_translucency_survives_hover_and_selection_overlays(self):
        for dark in (True, False):
            with self.subTest(dark=dark):
                self.selector.setDark(dark)
                self.open_menu(5)
                QTest.mouseMove(self.popup._center_button, self.popup._center_button.rect().center())
                self.flush()
                image = self.popup.grab().toImage()

                def sample(point):
                    return image.pixelColor(
                        round(point.x() * image.devicePixelRatio()),
                        round(point.y() * image.devicePixelRatio()),
                    )

                idle = sample(self.sector_point(0))
                selected = sample(self.sector_point(5))
                center = sample(self.popup.rect().center() + QPoint(0, 27))
                self.assertGreater(idle.alpha(), 0)
                self.assertLess(idle.alpha(), 255)
                self.assertEqual(selected.alpha(), idle.alpha())
                self.assertEqual(center.alpha(), idle.alpha())
                self.assertEqual(sample(QPoint(1, 1)).alpha(), 0)
                QTest.mouseMove(self.popup, self.sector_point(0))
                self.flush()
                animation = self.popup._hover_animation
                for progress in (animation.duration() // 2, animation.duration()):
                    animation.setCurrentTime(progress)
                    image = self.popup.grab().toImage()
                    self.assertEqual(sample(self.sector_point(0)).alpha(), idle.alpha())
                QTest.mouseMove(self.popup, self.sector_point(5))
                self.flush()
                animation.setCurrentTime(animation.duration())
                image = self.popup.grab().toImage()
                self.assertEqual(sample(self.sector_point(5)).alpha(), idle.alpha())
                colors = self.selector.colors()
                accent = QColor(colors["accent"])
                image = self.popup._center_button.grab().toImage()
                pixels = [image.pixelColor(horizontal, vertical)
                          for horizontal in range(image.width()) for vertical in range(image.height())]
                self.assertTrue(any(pixel.alpha() == 255 and pixel.rgb() == accent.rgb() for pixel in pixels))
                self.popup.hide()

    def test_hover_keeps_brightness_between_button_and_same_sector(self):
        self.open_menu(5)
        button = self.popup._buttons[0]
        QTest.mouseMove(button, button.rect().center())
        self.flush()
        animation = self.popup._hover_animation
        animation.setCurrentTime(animation.duration())
        self.assertEqual(self.popup._hover_index, 0)
        QTest.mouseMove(self.popup, self.sector_point(0))
        self.flush()
        self.assertEqual(self.popup._hover_index, 0)
        self.assertEqual(self.popup._hover_levels[0], 1.0)
        self.assertEqual(animation.state(), QAbstractAnimation.Stopped)

    def test_center_and_outside_fade_hover_without_changing_selection(self):
        destinations = (
            (self.popup._center_button, self.popup._center_button.rect().center()),
            (self.host, QPoint(self.host.width() - 4, 4)),
        )
        for destination, point in destinations:
            with self.subTest(destination=destination.objectName()):
                self.open_menu(5)
                QTest.mouseMove(self.popup, self.sector_point(0))
                self.flush()
                animation = self.popup._hover_animation
                animation.setCurrentTime(animation.duration())
                QTest.mouseMove(destination, point)
                self.flush()
                self.assertEqual(self.popup._hover_index, -1)
                animation.setCurrentTime(animation.duration())
                self.assertEqual(self.popup._hover_levels, [0.0] * 6)
                self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
                self.assertEqual(self.selector.currentIndex(), 5)
                self.assertEqual(self.changes, [])
                self.popup.hide()

    def test_closing_menu_stops_hover_animation_and_reopening_resets_it(self):
        self.open_menu(5)
        QTest.mouseMove(self.popup, self.sector_point(0))
        self.flush()
        animation = self.popup._hover_animation
        animation.setCurrentTime(animation.duration() // 2)
        self.popup.hide()
        self.flush()
        self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.popup._hover_levels, [0.0] * 6)
        self.open_menu(5)
        self.assertEqual(self.popup._hover_index, -1)
        self.assertEqual(self.popup._hover_levels, [0.0] * 6)
        self.assertEqual(self.changes, [])

    def test_center_closes_without_changing_selection(self):
        self.open_menu(4)
        QTest.mouseClick(self.popup._center_button, Qt.LeftButton)
        self.assertFalse(self.popup.isVisible())
        self.assertEqual(self.selector.currentIndex(), 4)
        self.assertEqual(self.changes, [])

    def test_outside_and_escape_preserve_selection(self):
        for close_with_key in (False, True):
            with self.subTest(escape=close_with_key):
                self.open_menu(3)
                if close_with_key:
                    QTest.keyClick(self.popup._buttons[3], Qt.Key_Escape)
                else:
                    QTest.mouseClick(self.popup, Qt.LeftButton, pos=QPoint(1, 1))
                self.flush()
                self.assertFalse(self.popup.isVisible())
                self.assertEqual(self.selector.currentIndex(), 3)
                self.assertEqual(self.changes, [])

    def test_keyboard_navigation_wraps_without_switching_early(self):
        self.open_menu(5)
        self.assertTrue(self.popup._buttons[5].hasFocus())
        QTest.keyClick(self.popup._buttons[5], Qt.Key_Right)
        self.assertTrue(self.popup._buttons[0].hasFocus())
        self.assertEqual(self.selector.currentIndex(), 5)
        QTest.keyClick(self.popup._buttons[0], Qt.Key_Return)
        self.assertEqual(self.changes, [0])
        self.assertFalse(self.popup.isVisible())

    def test_tab_reaches_center_and_enter_only_closes(self):
        self.open_menu(5)
        QTest.keyClick(self.popup._buttons[5], Qt.Key_Tab)
        self.assertTrue(self.popup._center_button.hasFocus())
        QTest.keyClick(self.popup._center_button, Qt.Key_Return)
        self.assertFalse(self.popup.isVisible())
        self.assertEqual(self.changes, [])

    def test_sector_boundaries_have_a_single_deterministic_index(self):
        self.open_menu()
        center = self.popup._center()
        for index in range(6):
            angle = math.radians(-120 + index * 60)
            point = QPointF(center.x() + 120 * math.cos(angle), center.y() + 120 * math.sin(angle))
            self.assertEqual(self.popup._hit_index(point), index)
        self.assertEqual(self.popup._hit_index(center), -1)
        self.assertIsNone(self.popup._hit_index(QPointF(0, 0)))

    def test_screen_edges_and_small_screen_size(self):
        available = QRect(0, 0, 300, 300)
        screen = types.SimpleNamespace(availableGeometry=lambda: available)
        with patch.object(QApplication, "screenAt", return_value=screen):
            self.open_menu(1)
        self.assertEqual(self.popup.width(), 280)
        self.assertTrue(available.contains(self.popup.geometry()))
        for index, button in enumerate(self.popup._buttons):
            self.assertTrue(self.popup.rect().contains(button.geometry()))
            self.assertEqual(self.popup._hit_index(button.geometry().center()), index)
            self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()), button.width())

    def test_owner_hide_closes_popup(self):
        self.open_menu()
        self.host.hide()
        self.flush()
        self.assertFalse(self.popup.isVisible())


class TestPerfChartAppearance(QtTestCase):
    def setUp(self):
        self.previous_monitor = PerfMonitor._instance
        PerfMonitor._instance = None
        self.monitor = PerfMonitor()
        for name, value in {"api_ms": 240, "pending": 3, "msg_rate": 8, "error_pct": 1.2}.items():
            self.monitor.metrics[name].push(value)
        analytics = types.ModuleType("dmshoot.core.message_analytics")
        analytics.daily_summary = lambda days: [
            {"date": "2026-10-03", "incoming": 48, "outgoing": 42, "reply_rate": 87.5, "avg_response_ms": 240},
            {"date": "2026-10-02", "incoming": 36, "outgoing": 30, "reply_rate": 83.3, "avg_response_ms": 210},
        ]
        analytics.platform_distribution = lambda days: {"douyin": 54, "bilibili": 30}
        analytics.hourly_distribution = lambda days: [{"h": 10, "cnt": 30}, {"h": 18, "cnt": 54}]
        self.analytics_patch = patch.dict(sys.modules, {"dmshoot.core.message_analytics": analytics})
        self.analytics_patch.start()
        self.host = QWidget()
        self.host.setObjectName("PerfPreview")
        self.host.setWindowFlags(Qt.FramelessWindowHint)
        self.host.setStyleSheet("QWidget#PerfPreview { background: #18181E; }")
        self.host.move(0, 0)
        self.host.resize(720, 620)
        layout = QVBoxLayout(self.host)
        layout.setContentsMargins(20, 16, 20, 16)
        heading = QLabel("性能监控 · 示例数据")
        heading.setStyleSheet("color: #F0C060; font-size: 14px; background: transparent;")
        layout.addWidget(heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.chart = PerfChart(self.monitor, compact=True)
        self.scroll.setWidget(self.chart)
        layout.addWidget(self.scroll)
        self.host.show()
        self.flush()
        QTest.qWait(140)
        self.chart._tm.stop()

    def tearDown(self):
        self.chart._chart_combo._popup.hide()
        self.destroy(self.host)
        self.analytics_patch.stop()
        PerfMonitor._instance = self.previous_monitor

    def metric_texts(self):
        return [(value.text(), change.text()) for value, change in self.chart._metric_refs[1]]

    def test_values_and_refresh_interval_are_unchanged(self):
        self.assertEqual(self.chart._tm.interval(), 3000)
        self.assertEqual(self.metric_texts(), [("240ms", "正常"), ("3", "偏低"), ("8/s", "正常"), ("1.2%", "偏高")])
        snapshot = {name: metric.values for name, metric in self.monitor.metrics.items()}
        for index in range(6):
            self.chart._chart_combo.setCurrentIndex(index)
            self.flush()
            self.assertEqual([not card.isHidden() for card in self.chart._chart_cards], [position == index for position in range(6)])
        self.assertEqual({name: metric.values for name, metric in self.monitor.metrics.items()}, snapshot)

    def test_drag_previews_actual_charts_and_release_commits_without_reverting(self):
        selector = self.chart._chart_combo
        selector.setCurrentIndex(5)
        confirmed, previewed = [], []
        selector.currentIndexChanged.connect(confirmed.append)
        selector.previewIndexChanged.connect(previewed.append)
        snapshot = {name: metric.values for name, metric in self.monitor.metrics.items()}
        texts = self.metric_texts()
        buffers = ([values.copy() for values in self.chart._ld], [values.copy() for values in self.chart._ad])
        QTest.mouseMove(selector._button, selector._button.rect().center())
        self.flush()
        QTest.mousePress(selector._button, Qt.LeftButton)
        QTest.qWait(selector._button._hold_timer.interval() + 40)
        self.flush()
        popup = selector._popup
        for index, button in enumerate(popup._buttons):
            QTest.mouseMove(button, button.rect().center())
            self.flush()
            self.assertEqual([not card.isHidden() for card in self.chart._chart_cards], [position == index for position in range(6)])
            self.assertEqual(selector.currentIndex(), 5)
            self.assertEqual(confirmed, [])
            self.assertTrue(popup.isVisible())
        self.assertEqual(previewed, list(range(6)))
        QTest.mouseRelease(popup._buttons[2], Qt.LeftButton)
        self.flush()
        self.assertEqual(confirmed, [2])
        self.assertEqual(previewed, list(range(6)))
        self.assertEqual(selector.currentIndex(), 2)
        self.assertFalse(popup.isVisible())
        self.assertEqual([not card.isHidden() for card in self.chart._chart_cards], [position == 2 for position in range(6)])
        self.assertEqual({name: metric.values for name, metric in self.monitor.metrics.items()}, snapshot)
        self.assertEqual(self.metric_texts(), texts)
        self.assertEqual((self.chart._ld, self.chart._ad), buffers)
        self.assertEqual(self.chart._tm.interval(), 3000)

    def test_canceling_preview_restores_actual_chart_without_confirmation(self):
        selector = self.chart._chart_combo
        confirmed = []
        selector.currentIndexChanged.connect(confirmed.append)
        for hide_owner in (False, True):
            with self.subTest(hide_owner=hide_owner):
                selector.setCurrentIndex(3)
                confirmed.clear()
                QTest.mouseMove(selector._button, selector._button.rect().center())
                self.flush()
                QTest.mousePress(selector._button, Qt.LeftButton)
                QTest.qWait(selector._button._hold_timer.interval() + 40)
                popup = selector._popup
                QTest.mouseMove(popup._buttons[1], popup._buttons[1].rect().center())
                self.flush()
                self.assertEqual([not card.isHidden() for card in self.chart._chart_cards], [position == 1 for position in range(6)])
                if hide_owner:
                    self.host.hide()
                else:
                    QTest.keyClick(popup._buttons[3], Qt.Key_Escape)
                self.flush()
                QTest.mouseRelease(selector._button, Qt.LeftButton)
                self.assertFalse(popup.isVisible())
                self.assertEqual(selector.currentIndex(), 3)
                self.assertEqual(confirmed, [])
                self.assertEqual([not card.isHidden() for card in self.chart._chart_cards], [position == 3 for position in range(6)])
                self.host.show()
                self.flush()

    def test_zero_value_display_policy_is_preserved(self):
        for metric in self.monitor.metrics.values():
            metric._buf.clear()
        self.chart._rebuild_metrics()
        self.assertEqual(self.metric_texts(), [("-", "无数据"), ("-", "无数据"), ("-", "无数据"), ("0%", "无数据")])

    def test_cards_are_single_layer_and_responsive(self):
        self.assertEqual(self.chart._metric_columns, 4)
        for card in self.chart._metric_refs[0]:
            self.assertEqual(card.height(), 96)
            self.assertIn("QFrame#PerfMetricCard", card.styleSheet())
            self.assertIn("QLabel { background: transparent; border: none; padding: 0; }", card.styleSheet())
        self.host.resize(550, 620)
        self.flush()
        self.assertLess(self.chart.width(), 550)
        self.host.resize(470, 620)
        self.flush()
        self.assertEqual(self.chart._metric_columns, 2)
        for index, card in enumerate(self.chart._metric_refs[0]):
            layout_index = self.chart._metrics_row.indexOf(card)
            self.assertEqual(self.chart._metrics_row.getItemPosition(layout_index)[:2], (index // 2, index % 2))
            self.assertGreaterEqual(card.x(), 0)
            self.assertLessEqual(card.geometry().right(), self.chart.width())
        self.assertEqual(self.scroll.horizontalScrollBar().maximum(), 0)

    def test_light_card_keeps_its_text_and_size(self):
        card = _MetricCardLight("API 延迟", "240ms", "正常", "#378ADD", "#A6E3A1")
        self.assertIsInstance(card, _MetricCard)
        self.assertEqual(card.height(), 96)
        self.assertEqual(card.layout().itemAt(1).widget().text(), "240ms")
        self.assertIn("#FFFFFF", card.styleSheet())
        self.destroy(card)

    def test_analytics_height_follows_content_without_extra_spacer(self):
        self.chart._chart_combo.setCurrentIndex(5)
        self.flush()
        QTest.qWait(20)
        analytics = self.chart._analytics_c._inner
        self.assertLess(analytics.minimumHeight(), 320)
        self.assertGreater(analytics.minimumHeight(), 150)
        self.assertLess(self.chart._analytics_c.height(), 320)

    def test_independent_window_layout_and_theme_still_work(self):
        window = PerfWindow(self.monitor)
        window._chart._tm.stop()
        self.assertFalse(window._chart._compact)
        self.assertFalse(hasattr(window._chart, "_chart_combo"))
        window._chart._st(True)
        self.assertTrue(window._chart._d)
        window._chart._st(False)
        self.assertFalse(window._chart._d)
        QTest.qWait(140)
        self.destroy(window)

    def test_visual_preview(self):
        self.chart._chart_combo.setCurrentIndex(5)
        self.flush()
        QTest.qWait(20)
        selector = self.chart._chart_combo
        selector._show_popup()
        self.flush()
        self.assertTrue(selector._popup.isVisible())
        self.assertEqual(selector._popup._current_index, 5)
        output = os.environ.get("DMSHOOT_PERF_PREVIEW_DIR")
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            scale = os.environ.get("QT_SCALE_FACTOR", "1")
            suffix = str(round(float(scale) * 100))
            image = self.host.grab().toImage()
            painter = QPainter(image)
            origin = self.host.mapFromGlobal(selector._popup.mapToGlobal(QPoint(0, 0)))
            painter.drawPixmap(origin, selector._popup.grab())
            painter.end()
            self.assertTrue(image.save(str(directory / f"performance-pie-{suffix}.png")))
            selector._popup.hide()
            self.assertTrue(self.host.grab().save(str(directory / f"performance-overview-{suffix}.png")))


if __name__ == "__main__":
    unittest.main()
