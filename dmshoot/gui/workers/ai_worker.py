"""AI 回复工作线程 — 从 MainWindow._call_ai 提取的匿名 _AIThread"""

from PySide6.QtCore import QThread, Signal as QtSignal


class AIWorker(QThread):
    """在独立线程中调用 AI 处理消息，完成后通过 done 信号返回回复"""
    done = QtSignal(str, str)  # (session_id, reply_text)

    def __init__(self, msg, ai, parent=None):
        super().__init__(parent)
        self._msg = msg
        self._ai = ai

    def run(self):
        import asyncio
        async def go():
            return await self._ai.handle_message(self._msg)
        loop = asyncio.new_event_loop()
        try:
            reply = loop.run_until_complete(go())
        finally:
            loop.close()
        if reply:
            self.done.emit(self._msg.session_id, reply)
