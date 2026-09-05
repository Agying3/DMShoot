"""抖音历史消息会话归属回归测试。"""

import json


MY_UID = "7581349050324026405"
PEER_UID = "3441909973131363"


def _varint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _message_frame(sender_uid: str, peer_uid: str, text: str, index: int) -> bytes:
    """构造包含真实会话字符串的最小 protobuf 缓存片段。"""
    metadata = (
        f"0:1:{peer_uid}:{MY_UID}".encode()
        + b"\x38" + _varint(int(sender_uid))
        + b"\x18" + _varint(7_650_000_000_000_000_000 + index)
        + b"\x20" + _varint(index)
        + b"\x28" + _varint(7_645_908_031_682_871_862)
    )
    content = json.dumps({"text": text}, ensure_ascii=False).encode()
    return metadata + b"\x42" + _varint(len(content)) + content


def test_protobuf_history_messages_keep_the_real_peer_uid():
    from dmshoot.utils.proto_msg_parser import extract_messages_from_protobuf

    raw = b"".join([
        _message_frame(PEER_UID, PEER_UID, "incoming", 1),
        _message_frame(MY_UID, PEER_UID, "outgoing", 2),
    ])

    messages = extract_messages_from_protobuf(raw, MY_UID)

    assert [message["is_self"] for message in messages] == [False, True]
    assert {message["peer_uid"] for message in messages} == {PEER_UID}
    assert {message["conv_short_id"] for message in messages} == {"7645908031682871862"}


def test_history_peer_resolution_puts_both_directions_in_one_session():
    from dmshoot.plugins.douyin.adapter import _history_peer_uid

    messages = [
        {"sender_uid": PEER_UID, "is_self": False, "conv_short_id": "c1"},
        {"sender_uid": MY_UID, "is_self": True, "peer_uid": PEER_UID, "conv_short_id": "c1"},
    ]
    peer_map = {"c1": PEER_UID}

    peer_uids = [_history_peer_uid(message, MY_UID, peer_map) for message in messages]
    session_ids = {f"douyin:0:1:{peer_uid}:{MY_UID}:0:" for peer_uid in peer_uids}

    assert peer_uids == [PEER_UID, PEER_UID]
    assert len(session_ids) == 1


def test_history_peer_resolution_skips_unmapped_self_message():
    from dmshoot.plugins.douyin.adapter import _history_peer_uid

    assert _history_peer_uid(
        {"sender_uid": MY_UID, "is_self": True, "conv_short_id": "unknown"},
        MY_UID,
        {},
    ) == ""
