"""DMShoot proto_msg_parser + douyin_im_sync 缓存测试

运行: python test_proto_sync.py
覆盖: _read_varint / extract_messages_from_protobuf / _cache_key
       _load_json_cache / _save_json_cache / _parse_and_cache_messages
"""

import sys, os, json, tempfile
from pathlib import Path

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

_results = []
def ok(name, detail=""):
    _results.append((name, True, detail))
    print(f"  [OK] {name}{' — ' + detail if detail else ''}")
def fail(name, reason=""):
    _results.append((name, False, reason))
    print(f"  [FAIL] {name}: {reason}")
def check(name, cond, detail=""):
    (ok if cond else fail)(name, detail)


# ═══════════════════════════════════════════════════════════
# 1. _read_varint — 从二进制流读变长整数
# ═══════════════════════════════════════════════════════════
def test_read_varint():
    from dmshoot.utils.proto_msg_parser import _read_varint

    print("\n=== _read_varint ===")

    # 单字节 (0~127)
    check("single 0", _read_varint(b'\x00\xFF', 0) == (0, 1))
    check("single 1", _read_varint(b'\x01\xFF', 0) == (1, 1))
    check("single 127", _read_varint(b'\x7F\xFF', 0) == (127, 1))

    # 双字节 (128~16383)
    check("two bytes 128", _read_varint(b'\x80\x01', 0) == (128, 2))
    check("two bytes 300", _read_varint(b'\xAC\x02', 0) == (300, 2))
    check("two bytes max", _read_varint(b'\xFF\x7F', 0) == (16383, 2))

    # 三字节
    check("three bytes 16384", _read_varint(b'\x80\x80\x01', 0) == (16384, 3))

    # 大值
    check("triple max", _read_varint(b'\xFF\xFF\x7F', 0)[0] == 2097151)

    # 边界: 0xFF 0xFF 0xFF 0xFF 0x0F = 最大 32-bit varint
    val, consumed = _read_varint(b'\xFF\xFF\xFF\xFF\x0F', 0)
    check("uint32 max varint", val == 4294967295)
    check("uint32 max consumed", consumed == 5)


# ═══════════════════════════════════════════════════════════
# 2. extract_messages_from_protobuf — 从 im_init 提取消息
# ═══════════════════════════════════════════════════════════
def test_extract_messages():
    from dmshoot.utils.proto_msg_parser import extract_messages_from_protobuf

    print("\n=== extract_messages ===")

    # 空输入
    check("empty bytes", extract_messages_from_protobuf(b'') == [])

    # 无 field 8 tag
    check("no field8", extract_messages_from_protobuf(b'\x08\x01\x10\x02' * 20) == [])


def test_extract_messages_with_real_data():
    """使用手工构造的 Protobuf 数据测试"""
    from dmshoot.utils.proto_msg_parser import extract_messages_from_protobuf

    print("\n=== extract_messages 手工数据 ===")

    # 构造: field 7 (sender=1000000001) + field 8 (content=JSON)
    sender = b'\x38' + _encode_varint(1000000001)
    content_json = b'{"text": "hello world"}'
    content_field = b'\x42' + _encode_varint(len(content_json)) + content_json

    raw = sender + content_field
    msgs = extract_messages_from_protobuf(raw)
    check("extract single msg", len(msgs) >= 1)
    if msgs:
        check("extract sender", msgs[0]["sender_uid"] == "1000000001")
        check("extract content", msgs[0]["content"] == "hello world")

    # 验证去重
    raw2 = sender + content_field + sender + content_field
    msgs2 = extract_messages_from_protobuf(raw2)
    check("dedup duplicate", len(msgs2) == 1)

    # 同文消息只要服务端 ID 或会话序号不同，就不能误去重
    server_1 = b'\x18' + _encode_varint(101)
    server_2 = b'\x18' + _encode_varint(102)
    by_server = extract_messages_from_protobuf(
        sender + server_1 + content_field + sender + server_2 + content_field
    )
    check("same text distinct server ids", len(by_server) == 2)

    index_1 = b'\x20' + _encode_varint(1)
    index_2 = b'\x20' + _encode_varint(2)
    by_index = extract_messages_from_protobuf(
        sender + index_1 + content_field + sender + index_2 + content_field
    )
    check("same text distinct indexes", len(by_index) == 2)


def test_extract_messages_truncated():
    from dmshoot.utils.proto_msg_parser import extract_messages_from_protobuf

    print("\n=== extract_messages 截断数据 ===")

    # content_len 声明很大但实际数据不够
    truncated = b'\x42\xFF\xFF\x0F' + b'too_short'
    msgs = extract_messages_from_protobuf(truncated)
    check("truncated returns empty", msgs == [])

    # 极小数据
    check("tiny bytes", extract_messages_from_protobuf(b'\x42') == [])


def test_extract_messages_no_sender():
    from dmshoot.utils.proto_msg_parser import extract_messages_from_protobuf

    print("\n=== extract_messages 无 sender ===")

    # 只有 content 没有 sender
    content = b'{"text": "no sender"}'
    raw = b'\x42' + _encode_varint(len(content)) + content
    msgs = extract_messages_from_protobuf(raw)
    check("no sender skipped", msgs == [])


# ═══════════════════════════════════════════════════════════
# 3. _cache_key — 从 cookie 提取缓存键
# ═══════════════════════════════════════════════════════════
def test_cache_key():
    from dmshoot.utils.douyin_im_sync import _cache_key

    print("\n=== _cache_key ===")

    # 带 sessionid
    k1 = _cache_key("sessionid=abc123; other=value")
    check("sessionid key non-empty", len(k1) == 12)
    check("sessionid key deterministic", _cache_key("sessionid=abc123; other=value") == k1)

    # 不同的 sessionid
    k2 = _cache_key("sessionid=xyz789; other=value")
    check("different sessionid = different key", k1 != k2)

    # 无 sessionid 回退到全 cookie hash
    k3 = _cache_key("no_sessionid_here=1; foo=bar")
    check("no sessionid still works", len(k3) == 12)
    check("no sessionid deterministic", _cache_key("no_sessionid_here=1; foo=bar") == k3)

    # 空 cookie
    k4 = _cache_key("")
    check("empty cookie works", len(k4) == 12)


# ═══════════════════════════════════════════════════════════
# 4. JSON 缓存读写
# ═══════════════════════════════════════════════════════════
def test_json_cache_roundtrip():
    from dmshoot.utils.douyin_im_sync import _load_json_cache, _save_json_cache, CACHE_DIR
    import tempfile, shutil

    print("\n=== JSON 缓存读写 ===")

    # 使用临时目录避免污染真实缓存
    orig_dir = CACHE_DIR
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        # monkey-patch CACHE_DIR
        import dmshoot.utils.douyin_im_sync as sync_mod
        sync_mod.CACHE_DIR = tmp_dir

        test_key = "test_abc123"
        test_data = [
            {"peer_uid": "111", "nickname": "用户A", "avatar": "http://a.jpg"},
            {"peer_uid": "222", "nickname": "用户B", "avatar": "http://b.jpg"},
        ]

        # 保存
        _save_json_cache(test_key, test_data)

        # 加载
        loaded = _load_json_cache(test_key)
        check("roundtrip not None", loaded is not None)
        check("roundtrip len", len(loaded) == 2)
        check("roundtrip peer1", loaded[0]["peer_uid"] == "111")
        check("roundtrip nickname1", loaded[0]["nickname"] == "用户A")
        check("roundtrip peer2", loaded[1]["peer_uid"] == "222")

        # 不存在的 key
        missing = _load_json_cache("nonexistent_key")
        check("missing key = None", missing is None)

    finally:
        sync_mod.CACHE_DIR = orig_dir
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 5. _parse_protobuf — 从二进制提取会话列表
# ═══════════════════════════════════════════════════════════
def test_parse_protobuf():
    from dmshoot.utils.douyin_im_sync import _parse_protobuf

    print("\n=== _parse_protobuf ===")

    # 构造包含 peer_id 的 protobuf 数据
    # 格式: 0:1:<peer_uid>:<my_uid> — 出现在原始 protobuf 中
    raw = b'0:1:1234567890:9876543210\x00\x00\x00\x00'
    convs = _parse_protobuf(raw, "9876543210")

    check("parse 1 peer", len(convs) == 1)
    check("peer uid correct", convs[0]["peer_uid"] == "1234567890")
    check("has nickname field", "nickname" in convs[0])
    check("has avatar field", "avatar" in convs[0])
    check("has sec_uid field", "sec_uid" in convs[0])

    # 多 peer
    raw2 = b'0:1:111:000 0:1:222:000 0:1:333:000'
    convs2 = _parse_protobuf(raw2, "000")
    check("parse multi peers", len(convs2) == 3)
    check("peer dedup", len({c["peer_uid"] for c in convs2}) == 3)


# ═══════════════════════════════════════════════════════════
# 6. _parse_and_cache_messages
# ═══════════════════════════════════════════════════════════
def test_parse_and_cache_messages():
    from dmshoot.utils.douyin_im_sync import (
        _parse_and_cache_messages, get_cached_messages
    )
    import dmshoot.utils.douyin_im_sync as sync_mod

    print("\n=== _parse_and_cache_messages ===")

    # 保存旧缓存
    old_cache = sync_mod._cached_messages[:]
    sync_mod._cached_messages = []

    try:
        # 空 protobuf
        _parse_and_cache_messages(b'', "100")
        check("empty raw = empty cache", len(get_cached_messages()) == 0)

        # 构造一条带 field 8 content 的 protobuf
        sender = b'\x38' + _encode_varint(2000000001)
        content = b'{"text": "test message"}'
        content_field = b'\x42' + _encode_varint(len(content)) + content
        raw = sender + content_field

        _parse_and_cache_messages(raw, "100")
        cached = get_cached_messages()
        check("cached has msg", len(cached) >= 1)
        if cached:
            check("cached content", cached[0]["content"] == "test message")
            check("cached is_self=False", not cached[0].get("is_self", True))

    finally:
        sync_mod._cached_messages = old_cache


# ═══════════════════════════════════════════════════════════
# 7. 常量正确性
# ═══════════════════════════════════════════════════════════
def test_constants():
    from dmshoot.utils.douyin_im_sync import CACHE_DIR

    print("\n=== 常量 ===")
    check("CACHE_DIR ends with cache", str(CACHE_DIR).endswith("cache"))


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════
def _encode_varint(value):
    """将整数编码为 protobuf varint 字节"""
    result = []
    while value > 127:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  DMShoot Protobuf + 抖音缓存 测试")
    print("=" * 55)

    test_read_varint()
    test_extract_messages()
    test_extract_messages_with_real_data()
    test_extract_messages_truncated()
    test_extract_messages_no_sender()
    test_cache_key()
    test_json_cache_roundtrip()
    test_parse_protobuf()
    test_parse_and_cache_messages()
    test_constants()

    total = len(_results)
    passed = sum(1 for _, ok_, _ in _results if ok_)
    failed_list = [(n, r) for n, ok_, r in _results if not ok_]
    print(f"\n{'=' * 55}")
    print(f"  {passed}/{total} 通过 ({100 * passed // total}%)" if total else "无测试")
    if failed_list:
        print(f"  {len(failed_list)} 失败:")
        for name, reason in failed_list:
            print(f"    [{name}] {reason}")
    print("=" * 55)
    sys.exit(0 if not failed_list else 1)
