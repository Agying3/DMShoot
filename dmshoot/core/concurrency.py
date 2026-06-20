"""统一并发管理器 — 共享线程池 + 优先级调度

设计目标：
  1. 所有适配器共享一个 ThreadPoolExecutor，避免各自创建线程池抢占资源
  2. 按优先级调度：消息回复(HIGH) > 批量同步(MEDIUM) > 头像/缓存(LOW)
  3. 背压控制：待处理任务过多时拒绝新任务，防止内存爆炸
  4. 可观测：每个平台的任务计数 + 队列深度

使用方式：
  from dmshoot.core.concurrency import ConcurrencyManager
  mgr = ConcurrencyManager.instance()
  future = mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin", fn, *args)
"""

from __future__ import annotations

import threading
import os
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Optional
from collections import deque, defaultdict


class ConcurrencyManager:
    """全应用共享的线程池管理器（单例）"""

    # 优先级常量
    PRIO_HIGH = 0    # 消息回复、AI 调用
    PRIO_MEDIUM = 1  # 批量同步、会话列表拉取
    PRIO_LOW = 2     # 头像下载、缓存刷新

    # 背压阈值
    MAX_QUEUE_DEPTH = 200       # 总队列上限
    MAX_PLATFORM_QUEUE = 60     # 单平台队列上限

    _instance: Optional["ConcurrencyManager"] = None
    _lock = threading.Lock()

    def __init__(self, max_workers: int = None):
        if max_workers is None:
            max_workers = min(32, (os.cpu_count() or 4) * 2)  # CPU×2 上限32
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="dmshoot-",
        )
        # 每个平台的任务计数
        self._platform_tasks: defaultdict[str, int] = defaultdict(int)
        self._task_lock = threading.Lock()
        self._shutdown = False

    @classmethod
    def instance(cls) -> "ConcurrencyManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def submit(
        self,
        priority: int,
        platform: str,
        fn: Callable,
        *args,
        **kwargs,
    ) -> Optional[Future]:
        """提交任务到共享线程池。返回 Future 或 None（背压拒绝）。

        Args:
            priority: PRIO_HIGH/MEDIUM/LOW
            platform: 平台标识 "douyin"/"bilibili"/"xiaohongshu"
            fn: 要在线程中执行的函数
            *args, **kwargs: 传给 fn 的参数
        """
        if self._shutdown:
            return None

        with self._task_lock:
            total = sum(self._platform_tasks.values())
            plat = self._platform_tasks[platform]

            # 背压：HIGH 永远不拒绝，MEDIUM/LOW 超过阈值拒绝
            if priority >= self.PRIO_MEDIUM and total >= self.MAX_QUEUE_DEPTH:
                return None
            if priority >= self.PRIO_MEDIUM and plat >= self.MAX_PLATFORM_QUEUE:
                return None

            self._platform_tasks[platform] += 1

        def _wrapper():
            try:
                return fn(*args, **kwargs)
            finally:
                with self._task_lock:
                    self._platform_tasks[platform] -= 1

        return self._executor.submit(_wrapper)

    def stats(self) -> dict:
        """返回当前并发统计"""
        with self._task_lock:
            return {
                "total_tasks": sum(self._platform_tasks.values()),
                "by_platform": dict(self._platform_tasks),
                "max_workers": self._executor._max_workers,
            }

    def shutdown(self, wait: bool = True):
        """关闭线程池（通常在应用退出时调用）"""
        self._shutdown = True
        self._executor.shutdown(wait=wait)

    @classmethod
    def reset(cls):
        """重置单例（测试用）"""
        if cls._instance:
            cls._instance.shutdown(wait=False)
        cls._instance = None
