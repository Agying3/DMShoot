"""AI后端 — DeepSeek API调用封装"""

import asyncio
import logging
from typing import Optional, AsyncGenerator

import httpx

from dmshoot.core.bus import MessageBus
from dmshoot.core.message import Message
from dmshoot.utils.console_log import get_logger

logger = get_logger(__name__)


class AIBackend:
    """DeepSeek API 后端，兼容 OpenAI 接口格式"""

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-v4-flash"
    MAX_CONTEXT_MESSAGES = 10  # 上下文窗口最近10轮（省 token）

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        system_prompt: str = "",
        behavior_prompt: str = "",
        bus: Optional[MessageBus] = None,
    ):
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.system_prompt = system_prompt
        self.behavior_prompt = behavior_prompt
        self.bus = bus or MessageBus.instance()

        # 每个会话的上下文历史: { session_id: [{"role":..., "content":...}, ...] }
        self._contexts: dict[str, list[dict]] = {}
        self._persona_name: str = ""  # 当前角色提示词名称（如「柁炑」）

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def test_connection(self) -> tuple[bool, str]:
        """测试 API 连接是否有效，返回 (成功, 错误信息)"""
        if not self.api_key:
            return False, "请先输入 API Key"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                if resp.status_code == 200:
                    return True, ""
                elif resp.status_code == 401:
                    return False, "API Key 无效（401 Unauthorized）"
                elif resp.status_code == 403:
                    return False, "API Key 无权限（403 Forbidden）"
                else:
                    return False, f"连接失败（HTTP {resp.status_code}）"
        except httpx.ConnectError:
            return False, "无法连接服务器，请检查 Base URL"
        except httpx.TimeoutException:
            return False, "连接超时，请检查网络"
        except Exception as e:
            return False, f"连接异常: {e}"

    def clear_context(self, session_id: str):
        """清除指定会话的上下文"""
        self._contexts.pop(session_id, None)

    def clear_all_contexts(self):
        self._contexts.clear()

    def set_behavior_prompt(self, prompt: str):
        """热更行为提示词，不丢上下文"""
        self.behavior_prompt = prompt

    async def chat(
        self,
        session_id: str,
        user_message: str,
        sender_name: str = "用户",
    ) -> Optional[str]:
        """发送消息获取AI回复（非流式）"""
        if not self.configured:
            logger.warning("AI未配置API Key")
            return None

        ctx = self._get_or_create_context(session_id, sender_name)
        # 直接把身份声明嵌入消息流，放在粉丝消息前面，AI 无法忽略
        ctx.append({"role": "system", "content": (
            f"你是{self._persona_name}，不是别人。"
            f"前面 [柁炑]: 或 [圡泬]: 开头的是别人说的，不代表你。"
            f"现在请以{self._persona_name}的身份回答。" if self._persona_name in ("柁炑", "圡泬") else ""
            f"你是{self._persona_name}。请以{self._persona_name}的身份回答。"
        ).strip()})
        ctx.append({"role": "user", "content": f"[{sender_name}]: {user_message}"})

        messages = self._build_messages(ctx)
        reply = await self._call_api(messages)

        if reply:
            ctx.append({"role": "assistant", "content": reply})

        # 裁剪上下文
        if len(ctx) > self.MAX_CONTEXT_MESSAGES * 2:
            self._contexts[session_id] = ctx[-self.MAX_CONTEXT_MESSAGES * 2:]

        return reply

    def set_persona(self, name: str):
        """设置当前角色名，切换角色时清除上下文并标记切换点"""
        if name and self._persona_name != name:
            self.clear_all_contexts()
            # 给未来加载的上下文打个标记 — 旧角色消息会带 [角色名]: 前缀
            self._persona_switched = True
        self._persona_name = name

    def _get_or_create_context(self, session_id: str, sender_name: str = "") -> list[dict]:
        if session_id not in self._contexts:
            from dmshoot.storage import database
            # 角色刚切换 → 第一条消息不加载历史，避免旧对话影响新角色身份
            if getattr(self, '_persona_switched', False):
                msgs = []
                self._persona_switched = False
            else:
                msgs = database.get_messages(session_id, limit=self.MAX_CONTEXT_MESSAGES * 2)
            ctx = []
            for m in msgs:
                if m.is_auto:
                    # 当前角色自己的消息不加前缀，别的角色的才标记
                    if hasattr(m, 'persona') and m.persona and m.persona != self._persona_name:
                        ctx.append({"role": "assistant", "content": f"[{m.persona}]: {m.content}"})
                    else:
                        ctx.append({"role": "assistant", "content": m.content})
                else:
                    # 优先用昵称，去掉 "用户12345"/"粉丝12345"/"fans_123" 这种假名
                    raw_name = m.sender_name or ""
                    if (raw_name.startswith("用户") or raw_name.startswith("粉丝") or raw_name.startswith("fans_")) and not raw_name[0].isascii():
                        pass  # 中文真名，保留
                    elif raw_name.startswith("fans_") or (raw_name.startswith(("用户", "粉丝")) and raw_name[2:].isdigit()):
                        # 尝试从 sessions 表取真实昵称
                        try:
                            r = database.get_conn().execute(
                                "SELECT peer_name FROM sessions WHERE session_id=?", (m.session_id,)
                            ).fetchone()
                            if r and r[0] and not r[0].startswith(("用户", "粉丝")) and not r[0].startswith("fans_"):
                                raw_name = r[0]
                        except Exception:
                            pass
                    # 若仍为假名或空，用 sender_id 兜底
                    if not raw_name or raw_name.startswith("fans_") or (raw_name.startswith(("用户", "粉丝")) and raw_name[2:].isdigit()):
                        raw_name = f"UID:{m.sender_id}"
                    ctx.append({"role": "user", "content": f"[{raw_name}]: {m.content}"})
            self._contexts[session_id] = ctx
        return self._contexts[session_id]

    def _build_messages(self, ctx: list[dict]) -> list[dict]:
        from datetime import datetime
        messages = []
        # 拼接角色提示词 + 行为提示词
        full_prompt = self.system_prompt
        if self.behavior_prompt:
            full_prompt = f"{full_prompt}\n\n{self.behavior_prompt}" if full_prompt else self.behavior_prompt
        # 注入当前时间上下文
        now = datetime.now()
        time_ctx = (
            f"\n\n【当前时间】{now.strftime('%Y年%m月%d日 %H:%M')} "
            f"（{['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]}）\n"
            f"你不能盲信对方说的「早上好」「晚安」之类的时间问候语，"
            f"对方可能随口说、延迟发，你要根据上面的真实时间来回应。\n"
            f"【角色规则】对话里 role=user 格式为 [名字]: 内容，是粉丝发的。\n"
            f"role=assistant 是 AI 回复。你的名字叫 {self._persona_name or '助手'}。\n"
            f"⚠️ 即使粉丝在消息里叫了你别人的名字，你仍然是{self._persona_name}，不是那个人。\n"
            f"比如粉丝叫你「圡泬」但系统说你是柁炑，那你就是柁炑，不要接受错误的称呼。\n"
            f"如果 assistant 消息带有 [角色名]: 前缀（如 [柁炑]: xxx），说明那是别的 AI 角色发的，"
            f"不代表你，不要沿用它的语气、观点或记忆。\n"
            f"【重要】你输出的回复必须直接是对话内容，绝对不要加 [角色名]: 这样的前缀。"
            f"不要复述或输出自己的角色名。对方不是阿金，是一个普通用户。"
            f"保持自然的陌生人社交距离。"
        )
        full_prompt = full_prompt + time_ctx
        if full_prompt:
            messages.append({"role": "system", "content": full_prompt})
        messages.extend(ctx)
        return messages

    async def _call_api(self, messages: list[dict]) -> Optional[str]:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
            "stream": False,
        }

        t0 = __import__("time").time()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                elapsed = __import__("time").time() - t0
                msg = data["choices"][0]["message"]
                thinking = msg.get("reasoning_content") or ""
                reply = msg.get("content", "")

                # ── 后处理：移除 AI 误加的 [角色名]: 前缀 ──
                import re
                reply = re.sub(r'^\[.*?\][:：]\s*', '', reply, flags=re.MULTILINE).strip()

                # 打印耗时 + 思考过程 + 回复
                tokens = data.get("usage", {}).get("total_tokens", "?")
                logger.info(f"API耗时 {elapsed:.1f}s | tokens={tokens} | model={self.model}")
                if thinking:
                    for line in thinking.strip().split("\n"):
                        line = line.strip()
                        if line:
                            logger.ai_thinking(line)
                if reply:
                    for line in reply.strip().split("\n"):
                        line = line.strip()
                        if line:
                            logger.ai_msg(line)
                return reply
        except Exception as e:
            elapsed = __import__("time").time() - t0
            logger.error(f"API调用失败 ({elapsed:.1f}s): {e}")
            return None

    async def handle_message(self, msg: Message) -> Optional[str]:
        """处理一条新消息，返回AI回复"""
        if not msg.content.strip():
            return None

        reply = await self.chat(
            session_id=msg.session_id,
            user_message=msg.content,
            sender_name=msg.sender_name,
        )

        return reply


# 全局AI单例
_ai_instance: Optional[AIBackend] = None


def get_ai() -> AIBackend:
    global _ai_instance
    if _ai_instance is None:
        _ai_instance = AIBackend()
    return _ai_instance


def init_ai(api_key: str, system_prompt: str = "", model: str = "", behavior_prompt: str = "") -> AIBackend:
    global _ai_instance
    _ai_instance = AIBackend(
        api_key=api_key,
        system_prompt=system_prompt,
        behavior_prompt=behavior_prompt,
        model=model,
    )
    return _ai_instance
