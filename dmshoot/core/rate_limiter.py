"""消息发送限流器 — token bucket 算法，防止平台风控

用法:
    limiter = RateLimiter(rate=5.0)  # 每秒5条
    if limiter.acquire():
        adapter.send_message(...)
    else:
        # 被限流，稍后重试
"""

import time
import threading
from typing import Optional


class RateLimiter:
    """Token bucket 限流器 — 线程安全"""

    def __init__(self, rate: float = 5.0, burst: int = 10):
        self._rate = rate           # tokens per second
        self._burst = burst         # max burst size
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._wait_count = 0        # 被限流的次数
        self._total_acquired = 0    # 成功获取的次数

    def acquire(self) -> bool:
        """尝试获取一个 token。成功返回 True，限流返回 False"""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._total_acquired += 1
                return True
            self._wait_count += 1
            return False

    @property
    def available(self) -> float:
        with self._lock:
            return self._available_unlocked()

    def _available_unlocked(self) -> float:
        elapsed = time.monotonic() - self._last_refill
        return min(self._burst, self._tokens + elapsed * self._rate)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "rate": self._rate,
                "burst": self._burst,
                "available": round(self._available_unlocked(), 1),
                "throttled": self._wait_count,
                "sent": self._total_acquired,
            }

    def reset(self):
        with self._lock:
            self._tokens = float(self._burst)
            self._last_refill = time.monotonic()
            self._wait_count = 0
            self._total_acquired = 0

    def set_rate(self, rate: float):
        with self._lock:
            self._rate = max(0.1, rate)


# ── 平台级限流 ──

_PLATFORM_RATES = {
    "douyin":      5.0,   # 抖音保守 5条/秒
    "bilibili":   10.0,   # B站 10条/秒
    "xiaohongshu": 3.0,   # 小红书 3条/秒
    "kuaishou":    5.0,   # 快手 5条/秒
}

_limiter_lock = threading.Lock()
_limiters: dict[str, RateLimiter] = {}


def get_limiter(platform: str) -> RateLimiter:
    """获取平台限流器（不存在则自动创建）"""
    if platform not in _limiters:
        with _limiter_lock:
            if platform not in _limiters:
                rate = _PLATFORM_RATES.get(platform, 5.0)
                _limiters[platform] = RateLimiter(rate=rate, burst=max(2, int(rate * 2)))
    return _limiters[platform]


def get_all_stats() -> dict:
    return {p: l.stats for p, l in _limiters.items()}
