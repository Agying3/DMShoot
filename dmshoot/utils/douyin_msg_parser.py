"""从 get_message_by_init protobuf 中提取消息内容

protobuf wire format 通用解析器，针对 cmd=2043 的响应格式。
"""

import re, json, time
from typing import Optional


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """解码 protobuf varint"""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        result |= (byte & 0x7f) << shift
        pos += 1
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos


def _find_all_conversations(raw: bytes, my_uid: str) -> dict[str, list]:
    """找到每个 conversation_id 的所有出现位置（每条消息一次）"""
    results = {}
    conv_pat = re.compile(rb'(0:1:(\d+):(\d+))')
    for m in conv_pat.finditer(raw):
        cid = m.group(1).decode()
        peer = m.group(2).decode()
        my = m.group(3).decode()
        if my != my_uid:
            continue
        if peer not in results:
            results[peer] = []
        results[peer].append(m.start())
    return results


def _extract_messages_near(raw: bytes, conv_id: str, positions: list[int]) -> list[dict]:
    """在 conversation_id 出现位置附近提取消息"""
    messages = []
    seen_content = set()

    for pos in positions[:50]:  # 最多处理50条消息
        # 看出现位置前后的数据
        window = raw[max(0, pos - 200):min(len(raw), pos + 3000)]

        # 提取 JSON content
        json_patterns = [
            rb'\{"text":"(.*?)"\}',           # 文本消息
            rb'(\{"text":".*?"\})',           # 完整 JSON content
        ]
        content_text = ""
        for pat in json_patterns:
            match = re.search(pat, window)
            if match:
                try:
                    content_obj = json.loads(match.group(1).decode())
                    content_text = content_obj.get("text", "")
                    if content_text and content_text not in seen_content:
                        seen_content.add(content_text)
                        break
                except:
                    pass

        if not content_text:
            continue

        # 尝试提取时间戳（附近的大数字，10位=秒级时间戳）
        ts = 0
        for m in re.finditer(rb'([1][5-9]\d{8})', window):
            val = int(m.group(1))
            if 1700000000 < val < 1800000000:  # 合理的时间戳范围
                ts = val
                break

        messages.append({
            "content": content_text,
            "timestamp": float(ts) if ts else time.time(),
            "is_self": False,
            "msg_type": "text",
        })

    return messages


def extract_all_messages(raw: bytes, my_uid: str) -> dict[str, list[dict]]:
    """提取所有会话的消息，返回 {peer_uid: [msg_dict, ...]}"""
    convs = _find_all_conversations(raw, my_uid)
    result = {}
    for peer, positions in convs.items():
        conv_id = f"0:1:{peer}:{my_uid}"
        msgs = _extract_messages_near(raw, conv_id, positions)
        if msgs:
            result[peer] = msgs
    return result


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], 'rb') as f:
        raw = f.read()
    msgs = extract_all_messages(raw, "7581349050324026405")
    for peer, msgs in msgs.items():
        print(f"\npeer={peer}: {len(msgs)} messages")
        for m in msgs[-5:]:  # 最近5条
            print(f"  {m['content'][:50]}")
