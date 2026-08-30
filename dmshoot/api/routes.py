"""FastAPI 路由 —— 所有 HTTP 接口"""

import asyncio
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, WebSocket
from pydantic import ValidationError

from dmshoot.api.models import (
    AdapterStartRequest, AdapterStopRequest, LoginScanRequest,
    MessageSendRequest, AIGenerateRequest, ConfigUpdateRequest,
    PromptUpdateRequest, StatusResponse, AdapterStatusItem,
    SessionListResponse, SessionItem,
    MessageListResponse, MessageItem,
    ConfigResponse, PromptListResponse, PerfSnapshotResponse,
    ErrorResponse,
)
from dmshoot.api.ws_bridge import get_bridge

router = APIRouter(prefix="/api")
logger = logging.getLogger("dmshoot.api.routes")

# ── 全局引用（延迟初始化，避免循环导入） ──

_adapter_mgr = None
_config = None

_PLATFORMS = {"douyin", "bilibili", "kuaishou", "xiaohongshu"}


def init(adapter_mgr, config):
    """由 main_headless.py 在启动时调用，注入依赖"""
    global _adapter_mgr, _config
    _adapter_mgr = adapter_mgr
    _config = config


def _req_id():
    return uuid.uuid4().hex[:8]


# ── 健康检查 ──

@router.get("/health")
async def health():
    return {"ok": True, "uptime": time.time() - _start_time if "_start_time" in globals() else 0}


# ═══════════════════════════════════════
#  适配器
# ═══════════════════════════════════════

@router.get("/adapter/status")
async def adapter_status():
    platforms = {}
    for p in _PLATFORMS:
        adapter = _adapter_mgr.adapters.get(p)
        platforms[p] = AdapterStatusItem(
            connected=adapter is not None and getattr(adapter, "_connected", False),
            status=_get_platform_status(p),
            name=getattr(adapter, "_my_name", None) if adapter else None,
            session_count=0,
        )
    return {"platforms": {k: v.model_dump() for k, v in platforms.items()}}


def _get_platform_status(platform: str) -> str:
    adapter = _adapter_mgr.adapters.get(platform)
    if not adapter:
        return "offline"
    if getattr(adapter, "_connected", False):
        return "online"
    return "connecting"


@router.post("/adapter/start")
async def adapter_start(req: AdapterStartRequest):
    rid = _req_id()
    logger.info("[%s] platform=%s op=adapter_start | 正在启动", rid, req.platform)
    t0 = time.time()
    try:
        _adapter_mgr.start(req.platform)
        logger.info("[%s] platform=%s op=adapter_start latency=%dms | 已触发启动",
                    rid, req.platform, int((time.time()-t0)*1000))
        return {"ok": True, "platform": req.platform, "status": "connecting"}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/adapter/stop")
async def adapter_stop(req: AdapterStopRequest):
    rid = _req_id()
    logger.info("[%s] platform=%s op=adapter_stop | 正在停止", rid, req.platform)
    _adapter_mgr.stop(req.platform)
    return {"ok": True, "platform": req.platform}


# ═══════════════════════════════════════
#  登录
# ═══════════════════════════════════════

@router.post("/login/scan")
async def login_scan(req: LoginScanRequest):
    rid = _req_id()
    logger.info("[%s] platform=%s op=login | 启动扫码", rid, req.platform)

    bridge = get_bridge()

    async def _on_qr(b64: str):
        await bridge.push_qr_code(req.platform, b64)

    async def _bg_scan():
        try:
            if req.platform == "douyin":
                from dmshoot.utils.cookie_reader import extract_douyin_cookies_sync
                import asyncio as _asyncio
                loop = _asyncio.get_event_loop()
                result = await loop.run_in_executor(None, extract_douyin_cookies_sync, None)
                if result and result.get("cookie"):
                    _config.douyin_cookie = result["cookie"]
                    _config.douyin_web_protect = result.get("web_protect", "")
                    _config.douyin_keys = result.get("keys", "")
                    from dmshoot.storage import database
                    database.update_config_fields({
                        "douyin_cookie": _config.douyin_cookie,
                        "douyin_web_protect": _config.douyin_web_protect,
                        "douyin_keys": _config.douyin_keys,
                    })
                    await bridge.push_login_ok(req.platform)
                else:
                    await bridge.push_login_fail(req.platform, "扫码失败")
            elif req.platform == "bilibili":
                from dmshoot.utils.cookie_reader import extract_bilibili_cookies_sync
                import asyncio as _asyncio
                loop = _asyncio.get_event_loop()
                cookies = await loop.run_in_executor(None, extract_bilibili_cookies_sync, None)
                if cookies and cookies.get("SESSDATA"):
                    _config.bilibili_sessdata = cookies["SESSDATA"]
                    _config.bilibili_jct = cookies["bili_jct"]
                    _config.bilibili_buvid3 = cookies["buvid3"]
                    _config.bilibili_buvid4 = cookies["buvid4"]
                    _config.bilibili_dedeuserid = cookies["dedeuserid"]
                    _config.bilibili_ac_time_value = cookies["ac_time_value"]
                    from dmshoot.storage import database
                    database.update_config_fields({
                        "bilibili_sessdata": _config.bilibili_sessdata,
                        "bilibili_jct": _config.bilibili_jct,
                        "bilibili_buvid3": _config.bilibili_buvid3,
                        "bilibili_buvid4": _config.bilibili_buvid4,
                        "bilibili_dedeuserid": _config.bilibili_dedeuserid,
                        "bilibili_ac_time_value": _config.bilibili_ac_time_value,
                    })
                    await bridge.push_login_ok(req.platform)
                else:
                    await bridge.push_login_fail(req.platform, "扫码失败")
            else:
                await bridge.push_login_fail(req.platform, f"平台 {req.platform} 暂不支持")
        except Exception as e:
            logger.error("[%s] platform=%s op=login | 扫码异常: %s", rid, req.platform, e)
            await bridge.push_login_fail(req.platform, str(e))

    asyncio.create_task(_bg_scan())
    return {"ok": True, "platform": req.platform, "status": "scanning"}


@router.post("/login/cancel")
async def login_cancel(req: LoginScanRequest):
    return {"ok": True, "platform": req.platform}


# ═══════════════════════════════════════
#  消息
# ═══════════════════════════════════════

@router.get("/sessions")
async def get_sessions(platform: Optional[str] = Query(None)):
    from dmshoot.storage import database
    sessions = database.get_sessions(platform=platform)
    items = [
        SessionItem(
            session_id=s.session_id,
            platform=s.platform,
            peer_name=s.peer_name or "",
            peer_id=s.peer_id or "",
            avatar_url=s.avatar_url or "",
            last_message=s.last_message or "",
            last_time=s.last_time or 0,
            unread=s.unread or 0,
        )
        for s in sessions
    ]
    return {"sessions": [it.model_dump() for it in items]}


@router.get("/messages/{session_id:path}")
async def get_messages(session_id: str, limit: int = Query(50, le=200), before: Optional[float] = Query(None)):
    from dmshoot.storage import database
    msgs = database.get_messages(session_id, limit=limit)
    if before:
        msgs = [m for m in msgs if (m.timestamp or 0) < before]
        msgs = msgs[:limit]
    items = [
        MessageItem(
            msg_id=m.id,
            sender_id=m.sender_id or "",
            sender_name=m.sender_name or "",
            content=m.content or "",
            msg_type=m.msg_type or "text",
            timestamp=m.timestamp or 0,
            is_self=bool(m.is_self),
        )
        for m in msgs
    ]
    return {
        "session_id": session_id,
        "peer_name": items[0].sender_name if items else "",
        "messages": [it.model_dump() for it in items],
        "has_more": len(items) >= limit,
    }


@router.post("/message/send")
async def send_message(req: MessageSendRequest):
    rid = _req_id()
    # 解析 platform
    parts = req.session_id.split(":")
    platform = parts[0] if parts else ""

    if platform not in _PLATFORMS:
        raise HTTPException(400, detail={"error": "platform_not_found", "detail": platform})

    adapter = _adapter_mgr.adapters.get(platform)
    if not adapter or not getattr(adapter, "_connected", False):
        raise HTTPException(400, detail={"error": "platform_offline", "detail": f"{platform} 未连接"})

    t0 = time.time()
    try:
        ok = adapter.send_message(req.session_id, req.text)
        latency = int((time.time() - t0) * 1000)
        if ok:
            logger.info("[%s] platform=%s op=msg_send uid=%s latency=%dms | 发送成功",
                       rid, platform, parts[2] if len(parts)>2 else "?", latency)
            return {"ok": True}
        else:
            logger.error("[%s] platform=%s op=msg_send uid=%s latency=%dms | 发送失败",
                        rid, platform, parts[2] if len(parts)>2 else "?", latency)
            raise HTTPException(400, detail={"error": "auth_expired", "detail": "Cookie 可能已过期"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[%s] platform=%s op=msg_send | 异常: %s", rid, platform, e)
        raise HTTPException(500, detail={"error": "internal_error", "detail": str(e)})


# ═══════════════════════════════════════
#  AI
# ═══════════════════════════════════════

@router.post("/ai/active")
async def ai_active(req: AIGenerateRequest):
    """AI 主动生成消息，通过 WS 流式返回"""
    from dmshoot.ai.backend import get_ai
    from dmshoot.ai.prompts import load_prompts, load_behavior_prompts
    from dmshoot.storage import database

    ai = get_ai()
    if not ai or not _config.api_key:
        raise HTTPException(500, detail={"error": "api_key_missing", "detail": "API Key 未配置"})

    # 拉取对话历史
    msgs = database.get_messages(req.session_id, limit=20)
    context = [{"role": "user" if not m.is_self else "assistant", "content": m.content}
               for m in reversed(msgs)]

    # 拉取提示词
    persona = req.persona or _config.prompt_preset or "默认助手"
    prompt_map = load_prompts()
    system_prompt = prompt_map.get(persona, _config.system_prompt or "")

    behavior_map = load_behavior_prompts()
    behavior = behavior_map.get(_config.behavior_preset or "默认", "")

    bridge = get_bridge()

    async def _gen():
        try:
            full = ""
            async for chunk in ai.chat_stream(context, system_prompt, behavior):
                if chunk:
                    full += chunk
                    await bridge.push_ai_stream(req.session_id, chunk, False)
            await bridge.push_ai_stream(req.session_id, "", True)

            # 拆分多条消息并发送
            parts = _split_messages(full)
            parts_info = [p[:30] + ("..." if len(p) > 30 else "")
                         for p in parts]
            logger.info("[%s] platform=%s op=ai_gen uid=%s | %d段 → %s",
                       _req_id(), parts[0].split(":")[0] if parts else "?",
                       "?".join(parts[:1]), len(parts), parts_info)

        except Exception as e:
            logger.error("AI 生成失败: %s", e)
            await bridge.push_system_error("ai_error", str(e))

    asyncio.create_task(_gen())
    return {"ok": True, "status": "generating"}


def _split_messages(text: str) -> list[str]:
    """拆分 AI 生成的 <msg> 标签为多条消息"""
    import re
    parts = re.findall(r"<msg>\s*(.*?)\s*</msg>", text, re.DOTALL)
    if not parts:
        # 无标签 → 整段拆分为单条
        parts = [text.strip()]
    return [p.strip() for p in parts if p.strip()]


# ═══════════════════════════════════════
#  配置
# ═══════════════════════════════════════

@router.get("/config")
async def get_config():
    return ConfigResponse(
        api_key=_config.api_key or "",
        base_url=_config.base_url or "https://api.deepseek.com",
        model=_config.model or "deepseek-v4-flash",
        auto_reply_enabled=_config.auto_reply_enabled,
        reply_delay_min=_config.reply_delay_min or 1.0,
        reply_delay_max=_config.reply_delay_max or 3.0,
        max_context_rounds=_config.max_context_rounds or 10,
        temperature=getattr(_config, "temperature", 0.7),
        max_tokens=getattr(_config, "max_tokens", 1024),
        theme=getattr(_config, "theme", "dark"),
        rate_douyin=_config.rate_douyin,
        rate_bilibili=_config.rate_bilibili,
        rate_kuaishou=_config.rate_kuaishou,
    ).model_dump()


@router.put("/config")
async def update_config(req: ConfigUpdateRequest):
    from dmshoot.storage import database
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, detail={"error": "empty_request"})
    for key in updates:
        if not hasattr(_config, key):
            raise HTTPException(400, detail={"error": "invalid_field", "detail": key})
    database.update_config_fields(updates)
    for key, value in updates.items():
        setattr(_config, key, value)
    from dmshoot.core.rate_limiter import get_limiter
    get_limiter("douyin").set_rate(_config.rate_douyin)
    get_limiter("bilibili").set_rate(_config.rate_bilibili)
    get_limiter("kuaishou").set_rate(_config.rate_kuaishou)
    return {"ok": True}


# ═══════════════════════════════════════
#  提示词
# ═══════════════════════════════════════

@router.get("/prompts")
async def get_prompts():
    from dmshoot.ai.prompts import load_prompts, load_behavior_prompts
    return PromptListResponse(
        presets=load_prompts(),
        active=_config.prompt_preset or "",
        behavior_presets=load_behavior_prompts(),
        active_behavior=_config.behavior_preset or "",
    ).model_dump()


@router.put("/prompts")
async def update_prompts(req: PromptUpdateRequest):
    from pathlib import Path
    from dmshoot.ai.prompts import load_prompts, load_behavior_prompts
    base = Path(__file__).parent.parent.parent / "prompts"
    if req.type == "behavior":
        base = base / "行为"

    # 保存为 .txt 文件
    fname = req.name.replace(" ", "_").replace("/", "_") + ".txt"
    fpath = base / fname
    fpath.write_text(req.content, encoding="utf-8")
    logger.info("提示词已更新: %s", fpath)
    return {"ok": True}


# ═══════════════════════════════════════
#  AI 测试
# ═══════════════════════════════════════

@router.get("/ai/test")
async def test_ai():
    from dmshoot.ai.backend import get_ai
    ai = get_ai()
    if not ai:
        raise HTTPException(500, detail={"error": "not_initialized"})
    t0 = time.time()
    try:
        ok, msg = ai.test_connection()
        latency = int((time.time() - t0) * 1000)
        return {"ok": ok, "model": _config.model, "latency_ms": latency, "message": msg}
    except Exception as e:
        raise HTTPException(500, detail={"error": "connection_failed", "detail": str(e)})


# ═══════════════════════════════════════
#  性能
# ═══════════════════════════════════════

@router.get("/perf/snapshot")
async def perf_snapshot():
    try:
        from dmshoot.core.perf_monitor import get_monitor
        mon = get_monitor()
        snap = mon.snapshot()
        return snap
    except Exception:
        return {"cpu_percent": 0, "memory_mb": 0, "msg_rate": 0, "adapter_status": {}, "event_breakdown": {}}
