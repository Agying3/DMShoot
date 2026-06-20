"""稳定版 protobuf 消息提取器 v2"""
import json
from dmshoot.utils.douyin_ws import _decode_timestamp


def _read_varint(data, offset):
    result = shift = 0
    while offset < len(data):
        byte = data[offset]; offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80): break
        shift += 7
    return result, offset

def extract_messages_from_protobuf(raw: bytes, my_uid: str = "") -> list[dict]:
    """从 im_init protobuf 提取消息列表"""
    messages = []
    i = 0
    
    while i < len(raw) - 8:
        # 找 field 8 tag (0x42 = (8<<3)|2)
        if raw[i] != 0x42:
            i += 1; continue
        
        # 读 content length
        try:
            content_len, j = _read_varint(raw, i + 1)
        except:
            i += 1; continue
        
        if content_len < 5 or content_len > 5000 or j + content_len > len(raw):
            i += 1; continue
        
        content_raw = raw[j:j + content_len]
        try:
            content_str = content_raw.decode('utf-8')
        except:
            i = j + content_len; continue
        
        if not (content_str.startswith('{') and ('text' in content_str or 'tips' in content_str)):
            i = j + content_len; continue
        
        # ── 就近扫描 sender (field 7 = 0x38) ──
        # field 7 通常就在 content 前面 10~200 字节内
        # ⚠️ 关键：0x38 字节可能是碰巧在数据载荷中，不一定是 field tag
        # 过滤器：sender_uid 必须是长整型（≥10位 = 十亿以上），过滤掉假阳性
        sender_uid = None
        server_msg_id = None
        msg_index = None
        conv_short_id = None
        
        # 扫描 i 前面 300 字节，识别关键字段
        scan = max(0, i - 300)
        potential_sender = None  # 找到的最可能的 sender
        
        while scan < i:
            b = raw[scan]
            # 只识别单字节 field tag（field 1-15）
            if b in (0x18, 0x20, 0x28, 0x30, 0x38):
                try:
                    v, next_pos = _read_varint(raw, scan + 1)
                    if b == 0x38:    # field 7 = sender
                        # 只接受 ≥10 位的长 UID，过滤掉假阳性（数据中碰巧出现的 0x38）
                        if v >= 1_000_000_000:
                            potential_sender = v
                    elif b == 0x18:  # field 3 = server_message_id
                        if not server_msg_id: server_msg_id = v
                    elif b == 0x20:  # field 4 = index
                        if not msg_index: msg_index = v
                    elif b == 0x28:  # field 5 = conversation_short_id
                        if not conv_short_id: conv_short_id = v
                    scan = next_pos
                    continue
                except:
                    pass
            scan += 1
        
        # 取最后一次（最靠近 content 的）有效 sender
        if potential_sender:
            sender_uid = potential_sender
        # 如果没找到长 UID，尝试放宽条件（回退到所有 field 7 候选中最长的）
        elif not sender_uid:
            scan = max(0, i - 300)
            best_v = 0
            while scan < i:
                if raw[scan] == 0x38:
                    try:
                        v, _ = _read_varint(raw, scan + 1)
                        if v > best_v:
                            best_v = v
                    except: pass
                scan += 1
            if best_v > 100000:  # 至少5位数才算合理
                sender_uid = best_v
        
        if sender_uid is None:
            i = j + content_len; continue
        
        # 解析 JSON
        try:
            cj = json.loads(content_str)
            text = (cj.get('text') or cj.get('tips') or '').strip()
            if not text:
                i = j + content_len; continue
            
            # 时间戳 — 使用 sid >> 32 (Snowflake编码，高32位=Unix秒)
            ts = _decode_timestamp(server_msg_id or 0, conv_short_id or 0)
            
            conv_short_str = str(conv_short_id) if conv_short_id else ""
            
            messages.append({
                'sender_uid': str(sender_uid),
                'content': text,
                'timestamp': ts,
                'is_self': str(sender_uid) == my_uid,
                'msg_index': msg_index or 0,
                'conv_short_id': conv_short_str,
                'server_message_id': server_msg_id or 0,
            })
        except (json.JSONDecodeError, KeyError):
            pass
        
        i = j + content_len
    
    # 去重 + 排序
    seen = set()
    unique = []
    for m in messages:
        key = (m['sender_uid'], m['content'][:60])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    unique.sort(key=lambda x: x.get('timestamp', 0))
    return unique
