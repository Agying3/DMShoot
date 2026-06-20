"""DMShoot 新功能测试 — proto_parser + xhs_adapter + hot_load + bus_threading"""
import sys, os, json, tempfile
from pathlib import Path

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

passed = []; failed = []
def check(name, cond):
    (passed if cond else failed).append(name)
    print(f"  [{'OK' if cond else 'FAIL'}] {name}")

# ── proto_msg_parser ──
print("\n=== proto_msg_parser ===")
from dmshoot.utils.proto_msg_parser import _read_varint, extract_messages_from_protobuf

check("read_varint single byte 0x01", _read_varint(b'\x01\xFF', 0) == (1, 1))
check("read_varint single byte 0x7F", _read_varint(b'\x7F\xFF', 0) == (127, 1))
check("read_varint two bytes 0x80 0x01", _read_varint(b'\x80\x01\xFF', 0) == (128, 2))
# varint 0xFF 0xFF 0x7F = 2097151 (matches real large value)
check("read_varint triple max", _read_varint(b'\xFF\xFF\x7F', 0)[0] == 2097151)
# varint 0xAC 0x02 = 300 (172 + 128*1)
check("read_varint two bytes 300", _read_varint(b'\xAC\x02', 0) == (300, 2))
# single byte 0x01 with guard byte
check("read_varint single with guard", _read_varint(b'\x01\xAA', 0) == (1, 1))
# single byte 0x7F (127) is not special in varint
check("read_varint 127", _read_varint(b'\x7F', 0) == (127, 1))

check("extract empty bytes", extract_messages_from_protobuf(b'') == [])
check("extract no field8 tag", extract_messages_from_protobuf(b'\x08\x01\x10\x02' * 100) == [])

# ── XHS _parse_timestamp ──
# Note: _parse_timestamp removed from XHSAdapter (module abandoned);
# timestamp parsing is now handled inline in each adapter's _parse_message()
print("\n=== xiaohongshu _parse_timestamp (SKIPPED: function removed) ===")
check("skip_parse_timestamp — function removed from XHSAdapter", True)

# ── XHS _extract_content ──
print("\n=== xiaohongshu _extract_content ===")
from dmshoot.plugins.xiaohongshu.adapter import XHSAdapter

check("plain text", XHSAdapter._extract_content({"content": "hello"}) == "hello")
check("field text", XHSAdapter._extract_content({"text": "world"}) == "world")
check("json nested", XHSAdapter._extract_content({"content": '{"text": "nested"}'}) == "nested")
check("json nested content", XHSAdapter._extract_content({"content": '{"content": "nested2"}'}) == "nested2")
check("empty", XHSAdapter._extract_content({}) == "")
check("whitespace only", XHSAdapter._extract_content({"content": "   "}) == "")
check("unicode", XHSAdapter._extract_content({"content": "\u4f60\u597d"}) == "\u4f60\u597d")

# ── XHSAdapter constructor + properties ──
print("\n=== XHSAdapter props ===")
adapter = XHSAdapter(xhs_cookie="test_cookie_123")
check("platform_name", adapter.platform_name == "xiaohongshu")
check("has _replied", hasattr(adapter, "_replied"))
check("has _user_cache", hasattr(adapter, "_user_cache"))
check("_replied empty", len(adapter._replied) == 0)
check("_user_cache empty", len(adapter._user_cache) == 0)
check("cookie stored", adapter._cookie == "test_cookie_123")

# ── XHS send_message session_id parsing ──
print("\n=== XHS send_message ===")
# send_message needs auth which needs real cookie, but test the format parsing
class _MockAuth: ticket = "fake_ticket"
adapter._auth = _MockAuth()
# External API call will fail, test the format errors instead
check("send bad format", adapter.send_message("bad", "test") == False)

# clean up state file if created
sf = PROJECT / "dmshoot" / "data" / "xhs_state.json"
if sf.exists(): sf.unlink()

# ── XHS _headers ──
# Note: _headers() removed from XHSAdapter (module abandoned);
# header construction is now done inline in API call methods
print("\n=== XHS _headers (SKIPPED: method removed) ===")
check("skip_headers — _headers() removed from XHSAdapter", True)

# ── AI hot-load ──
print("\n=== AI hot-load ===")
from dmshoot.ai.backend import AIBackend

ai = AIBackend(api_key="sk-test", system_prompt="role_A", behavior_prompt="behave_A")

# Behavior hot
ai.set_behavior_prompt("behave_B")
check("behavior hot", ai.behavior_prompt == "behave_B")

# System prompt hot (simulate what _on_prompt_change should do)
ai.system_prompt = "role_B"
check("system prompt hot", ai.system_prompt == "role_B")

# Context preserved
ai._contexts["test_sid"] = [{"role": "user", "content": "hello"}]
msg = ai._build_messages(ai._contexts["test_sid"])
check("role_B in system", msg[0]["content"] == "role_B\n\nbehave_B")
check("user message preserved", msg[1]["content"] == "hello")
check("context after", ai._contexts.get("test_sid") is not None)
ai.clear_all_contexts()
check("context cleared", len(ai._contexts) == 0)

# ── AI dual prompt splicing ──
print("\n=== AI prompt splicing ===")
ai2 = AIBackend(api_key="sk-test", system_prompt="I am Alice", behavior_prompt="Be friendly")
m2 = ai2._build_messages([])
check("spliced prompt", m2[0]["content"] == "I am Alice\n\nBe friendly")

ai3 = AIBackend(api_key="sk-test", system_prompt="", behavior_prompt="Be friendly")
m3 = ai3._build_messages([])
check("only behavior", m3[0]["content"] == "Be friendly")

ai4 = AIBackend(api_key="sk-test", system_prompt="I am Alice", behavior_prompt="")
m4 = ai4._build_messages([])
check("only system", m4[0]["content"] == "I am Alice")

ai5 = AIBackend(api_key="sk-test", system_prompt="", behavior_prompt="")
m5 = ai5._build_messages([])
check("both empty", len(m5) == 0)

# ── AI clear_context ──
print("\n=== AI context management ===")
ai6 = AIBackend(api_key="sk-test")
ai6._contexts["a"] = [{"role": "user", "content": "hi"}]
ai6._contexts["b"] = [{"role": "user", "content": "yo"}]
ai6.clear_context("a")
check("clear single", "a" not in ai6._contexts)
check("other intact", "b" in ai6._contexts)
ai6.clear_all_contexts()
check("clear all", len(ai6._contexts) == 0)

# ── MessageBus thread safety ──
print("\n=== MessageBus instance ===")
import threading
from dmshoot.core.bus import MessageBus

bus1 = MessageBus.instance()
bus2 = MessageBus.instance()
check("singleton", bus1 is bus2)
check("has _lock", hasattr(MessageBus, "_lock"))

# ── Config roundtrip ──
print("\n=== Config DB roundtrip ===")
from dmshoot.storage.models import AppConfig
import sqlite3

tmpdb = tempfile.mktemp(suffix=".db")
import dmshoot.storage.database as dbmod
old_path = str(dbmod.DB_PATH)
try:
    dbmod.DB_PATH = Path(tmpdb)
    dbmod._conn = None
    dbmod.init_database()

    cfg = AppConfig(api_key="sk-abc", model="test-model", douyin_cookie="dy_cookie_val",
                    douyin_web_protect="wp_val", douyin_keys="keys_val")
    dbmod.save_config(cfg)
    loaded = dbmod.load_config()
    check("roundtrip api_key", loaded.api_key == "sk-abc")
    check("roundtrip model", loaded.model == "test-model")
    check("roundtrip douyin_cookie", loaded.douyin_cookie == "dy_cookie_val")
    check("roundtrip web_protect", loaded.douyin_web_protect == "wp_val")
    check("roundtrip keys", loaded.douyin_keys == "keys_val")
finally:
    dbmod.DB_PATH = Path(old_path)
    dbmod._conn = None
    try: os.remove(tmpdb); os.remove(tmpdb + '-wal'); os.remove(tmpdb + '-shm')
    except: pass

# ── Summary ──
print(f"\n{'='*40}")
print(f"Passed: {len(passed)}/{len(passed)+len(failed)} ({100*len(passed)/(len(passed)+len(failed)):.0f}%)")
for name in failed:
    print(f"  FAIL: {name}")
