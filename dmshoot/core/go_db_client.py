"""Go 数据库客户端 — Python 端所有 DB 操作路由到 Go 服务

用法:
    from dmshoot.core.go_db_client import GoDatabaseClient
    db = GoDatabaseClient()   # 需要 Go 服务已启动
    sessions = db.get_sessions("bilibili")
    db.save_messages(msgs)
"""

import json
from typing import Optional

import httpx

from dmshoot.storage.models import ChatMessage, SessionRecord, AppConfig

_GO_URL = "http://127.0.0.1:9800"


class GoDatabaseClient:
    """Go 后端数据库客户端 — 镜像 database.py 接口"""

    def __init__(self, base_url: str = _GO_URL):
        self._client = httpx.Client(base_url=base_url, timeout=30)
        self._base = base_url

    def alive(self) -> bool:
        try:
            return self._client.get("/api/health").status_code == 200
        except Exception:
            return False

    # ── 消息 ──

    def save_messages(self, msgs: list[ChatMessage]) -> int:
        if not msgs:
            return 0
        payload = [
            {
                "session_id": m.session_id,
                "sender_name": m.sender_name,
                "sender_id": m.sender_id,
                "content": m.content,
                "msg_type": m.msg_type,
                "timestamp": m.timestamp,
                "is_self": m.is_self,
                "is_auto": m.is_auto,
            }
            for m in msgs
        ]
        resp = self._client.post("/api/db/messages/save", json=payload)
        return resp.json().get("saved", 0)

    def get_messages(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        resp = self._client.get("/api/db/messages", params={
            "session_id": session_id, "limit": str(limit),
        })
        rows = resp.json()
        return [
            ChatMessage(
                session_id=r["session_id"], sender_name=r["sender_name"],
                sender_id=r["sender_id"], content=r["content"],
                msg_type=r["msg_type"], timestamp=r["timestamp"],
                is_self=r["is_self"], is_auto=r["is_auto"],
            )
            for r in rows
        ] if isinstance(rows, list) else []

    # ── 会话 ──

    def upsert_sessions(self, sessions: list[SessionRecord]) -> int:
        if not sessions:
            return 0
        payload = [
            {
                "session_id": s.session_id, "platform": s.platform,
                "peer_name": s.peer_name, "peer_id": s.peer_id,
                "last_message": s.last_message, "last_time": s.last_time,
                "avatar_url": s.avatar_url,
            }
            for s in sessions
        ]
        resp = self._client.post("/api/db/sessions/upsert", json=payload)
        return resp.json().get("saved", 0)

    def get_sessions(self, platform: str = "") -> list[SessionRecord]:
        params = {}
        if platform:
            params["platform"] = platform
        resp = self._client.get("/api/db/sessions", params=params)
        rows = resp.json()
        return [
            SessionRecord(
                session_id=r["session_id"], platform=r["platform"],
                peer_name=r["peer_name"], peer_id=r["peer_id"],
                last_message=r["last_message"], last_time=r["last_time"],
                avatar_url=r["avatar_url"],
            )
            for r in rows
        ] if isinstance(rows, list) else []

    def delete_sessions(self, platform: str):
        self._client.post("/api/db/sessions/delete", json={"platform": platform})

    # ── 配置 ──

    def load_config(self) -> Optional[AppConfig]:
        resp = self._client.get("/api/db/config")
        if resp.status_code == 200 and resp.text.strip():
            data = json.loads(resp.text)
            return AppConfig(**data) if data else None
        return None

    def save_config(self, config: AppConfig):
        from dataclasses import asdict
        self._client.post("/api/db/config", content=json.dumps(asdict(config), ensure_ascii=False))

    def close(self):
        self._client.close()
