"""实时性能监控 — 每秒采集 7 项指标，60 点环形缓冲

指标:
  队列积压       pending     0~10 正常 / 50 警告
  API 响应时间   api_ms      50~200ms 正常 / 500ms 警告
  错误率         error_pct   0~1% 正常 / 5% 警告
  线程池活跃度   workers_pct 50~70% 正常 / 90% 警告
  内存占用       mem_mb      <512MB 正常 / 1024MB 警告
  每秒消息数     msg_rate    5~10 正常 / <2 警告
  DB 写入延迟    db_ms       10~50ms 正常 / 100ms 警告
"""

import time
import threading
from collections import deque
from typing import Optional

import psutil


class Metric:
    """单条指标：名称 + 环形缓冲 + 告警阈值"""
    __slots__ = ("name", "unit", "low_warn", "high_warn", "normal_range", "_buf", "_max")

    def __init__(self, name, unit, low_warn, high_warn, normal_range="", max_points=60):
        self.name = name
        self.unit = unit
        self.low_warn = low_warn
        self.high_warn = high_warn
        self.normal_range = normal_range
        self._buf = deque(maxlen=max_points)
        self._max = max_points

    def push(self, value: float):
        self._buf.append(value)

    @property
    def latest(self) -> float:
        return self._buf[-1] if self._buf else 0.0

    @property
    def values(self) -> list:
        return list(self._buf)

    @property
    def status(self) -> str:
        v = self.latest
        if v >= self.high_warn:
            return "critical"
        if v >= self.low_warn:
            return "warning"
        return "normal"


class PerfMonitor:
    """全局性能监控单例 — 每秒 tick 一次"""

    _instance: Optional["PerfMonitor"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._lock = threading.Lock()
        self._process = psutil.Process()
        self._last_msg_count = 0
        self._last_api_ms = 0
        self._last_db_ms = 0
        self._api_errors = 0
        self._api_total = 0
        self._enabled = True

        self.metrics = {
            "pending":      Metric("队列积压", "条", 10, 50, "0~10"),
            "api_ms":       Metric("API响应", "ms", 200, 500, "50~200ms"),
            "error_pct":    Metric("错误率", "%", 1, 5, "0~1%"),
            "workers_pct":  Metric("线程池活跃", "%", 70, 90, "50~70%"),
            "mem_mb":       Metric("内存占用", "MB", 512, 1024, "<512MB"),
            "msg_rate":     Metric("消息速率", "条/秒", 5, 2, "5~10"),
            "db_ms":        Metric("DB写入", "ms", 50, 100, "10~50ms"),
        }
        self._tick_count = 0

    def tick(self):
        """每秒调用一次，采集所有指标"""
        if not self._enabled:
            return
        with self._lock:
            self._tick_count += 1
            mem = self._process.memory_info()
            cpu = self._process.cpu_percent()
            thread_count = self._process.num_threads()

            self.metrics["pending"].push(self._get_pending())
            self.metrics["api_ms"].push(self._get_api_ms())
            self.metrics["error_pct"].push(self._get_error_pct())
            self.metrics["workers_pct"].push(self._get_workers_pct(thread_count))
            self.metrics["mem_mb"].push(mem.rss / 1024 / 1024)
            self.metrics["msg_rate"].push(self._get_msg_rate())
            self.metrics["db_ms"].push(self._last_db_ms)

    # ── 外部注入点 ──

    def record_api(self, ms: float, is_error: bool = False):
        with self._lock:
            self._last_api_ms = ms
            self._api_total += 1
            if is_error:
                self._api_errors += 1

    def record_db_write(self, ms: float):
        with self._lock:
            self._last_db_ms = ms

    def record_msg(self):
        with self._lock:
            self._last_msg_count += 1

    def set_pending(self, count: int):
        self._last_pending = count

    # ── 采集逻辑 ──

    def _get_pending(self):
        try:
            from dmshoot.core.concurrency import ConcurrencyManager
            stats = ConcurrencyManager.instance().stats()
            return stats.get("total_tasks", 0)
        except Exception:
            return getattr(self, "_last_pending", 0)

    def _get_api_ms(self):
        return self._last_api_ms

    def _get_error_pct(self):
        if self._api_total == 0:
            return 0.0
        return (self._api_errors / self._api_total) * 100.0

    def _get_workers_pct(self, thread_count):
        try:
            from dmshoot.core.concurrency import ConcurrencyManager
            stats = ConcurrencyManager.instance().stats()
            max_w = stats.get("max_workers", 16)
            return (stats.get("total_tasks", 0) / max(max_w, 1)) * 100.0
        except Exception:
            return 0.0

    def _get_msg_rate(self):
        v = self._last_msg_count
        self._last_msg_count = 0
        return v

    @property
    def enabled(self):
        return self._enabled

    def set_enabled(self, v: bool):
        self._enabled = v


# ── 全局便捷函数 ──

def get_monitor() -> PerfMonitor:
    """获取全局性能监控单例（通过 PerfMonitor.__new__ 保证单例）"""
    return PerfMonitor()
