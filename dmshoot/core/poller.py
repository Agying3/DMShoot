"""自适应轮询间隔 — 有消息加快，无消息降速"""
import time


class AdaptivePoller:
    """有消息时缩小间隔(灵敏)，无消息时扩大间隔(省CPU)"""

    def __init__(self, base: float = 3.0, min_interval: float = 0.5, max_interval: float = 10.0):
        self._interval = base
        self._min = min_interval
        self._max = max_interval

    @property
    def interval(self) -> float:
        return self._interval

    def wait(self, had_messages: bool):
        """先 sleep，再根据是否有消息调整下次间隔"""
        time.sleep(self._interval)
        if had_messages:
            self._interval = max(self._min, self._interval * 0.7)
        else:
            self._interval = min(self._max, self._interval * 1.3)
