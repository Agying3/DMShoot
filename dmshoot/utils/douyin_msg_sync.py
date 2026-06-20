"""从 get_message_by_init protobuf 提取消息并写入 DB"""
import re, time, base64
from pathlib import Path

CACHE_DIR = Path("dmshoot/data/cache")

# 系统消息/昵称过滤
SKIP_WORDS = {
    '你们已互相关注对方', '我们已互相关注', '可以开始聊天了', '打个招呼吧',
    '柁炑炑', '圡泬泬', '柁炑炑_圡泬泬',
    '造化众生', '渣渣', '昙祭', '渣渣&昙祭', '冬天的蚊子嗡嗡嗡', '蚊子',
    '应汐', '黑骏马', '豆包', '萌妹', '萌娃',
    '可爱卡通长草团子', '草团子', '表情包萌萌', '友友花朵表情包', '下午好我的朋友',
    '注', '互相关', '可以开始聊', '了', '的', '吧', '表情',
}


def sync_messages_to_db(cookie_key: str):
    """从缓存的 protobuf 提取消息并写入数据库"""
    raw_file = CACHE_DIR / f"im_init_{cookie_key}.bin"
    if not raw_file.exists():
        return 0

    raw = raw_file.read_bytes()

    from dmshoot.utils.douyin_sdk import create_auth
    from dmshoot.storage.database import load_config

    config = load_config()
    auth = create_auth(config.douyin_cookie)
    my_uid = str(auth.get_uid())

    # 找所有 conversation_id → 位置列表
    conv_positions = {}
    for m in re.finditer(rb'0:1:(\d+):(\d+)', raw):
        peer = m.group(1).decode()
        my = m.group(2).decode()
        if my != my_uid:
            continue
        if peer not in conv_positions:
            conv_positions[peer] = []
        conv_positions[peer].append(m.start())

    from dmshoot.storage import database
    from dmshoot.storage.models import ChatMessage

    total = 0
    base_ts = time.time() - 86400  # 一天前作为基准时间

    for peer, positions in conv_positions.items():
        session_id = f"douyin:0:1:{peer}:{my_uid}:0:"
        # 找昵称
        peer_name = f"用户{peer}"
        try:
            sessions = database.get_sessions("douyin") or []
            for s in sessions:
                if s.peer_id == peer:
                    peer_name = s.peer_name
                    break
        except:
            pass

        seen = set()
        msg_idx = 0
        for pos in positions[:30]:  # 每个会话最多30条
            window = raw[max(0, pos - 200):min(len(raw), pos + 2000)]
            cn = re.findall(rb'(?:[\xe4-\xe9][\x80-\xbf][\x80-\xbf]){2,}', window)

            for c in cn:
                try:
                    text = c.decode('utf-8')
                    if len(text) < 2 or len(text) > 30:
                        continue
                    if text in SKIP_WORDS or any(w in text for w in ['已互相关注', '开始聊天', '招呼', '卡通']):
                        continue
                    if text in seen:
                        continue
                    seen.add(text)

                    # 判断是否自己发的
                    is_self = my_uid.encode() in window[:200]

                    database.save_message(ChatMessage(
                        session_id=session_id,
                        sender_name=peer_name if not is_self else config.douyin_cookie[:10],
                        sender_id=peer if not is_self else my_uid,
                        content=text,
                        msg_type="text",
                        timestamp=base_ts + msg_idx * 60,  # 每条间隔1分钟
                        is_self=is_self,
                    ))
                    msg_idx += 1
                    total += 1
                except Exception:
                    pass

    return total
