"""B站异步轮询验证测试 — 纯 AST 解析，零依赖，零 import"""

import ast
import sys
import os

ADAPTER_PATH = r"H:\DMShoot\dmshoot\plugins\bilibili\adapter.py"
BASEADAPTER_PATH = r"H:\DMShoot\dmshoot\core\adapter.py"

with open(ADAPTER_PATH, encoding="utf-8") as f:
    adapter_source = f.read()
adapter_ast = ast.parse(adapter_source)


def get_class(name):
    """从 AST 中提取指定类"""
    for node in ast.walk(adapter_ast):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def get_method(cls_ast, name):
    """从类 AST 中提取指定方法"""
    for node in ast.walk(cls_ast):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def classify_methods(cls_ast):
    """分类类的所有方法为 async/sync"""
    async_methods = []
    sync_methods = []
    all_methods = []
    for node in ast.walk(cls_ast):
        if isinstance(node, ast.AsyncFunctionDef):
            async_methods.append(node.name)
            all_methods.append(node.name)
        elif isinstance(node, ast.FunctionDef):
            sync_methods.append(node.name)
            all_methods.append(node.name)
    return async_methods, sync_methods, all_methods


# ── Tests ──

def test_structural():
    """L0: 结构完整性"""
    print("=== L0 结构完整性 ===")

    checks = {
        "async _async_loop": "async def _async_loop" in adapter_source,
        "async _async_poll": "async def _async_poll" in adapter_source,
        "async _sync_history": "async def _sync_history" in adapter_source,
        "async _get_user_name": "async def _get_user_name" in adapter_source,
        "asyncio.run": "asyncio.run(self._async_loop())" in adapter_source,
        "asyncio.gather concurrent": "asyncio.gather(*tasks" in adapter_source,
        "httpx.AsyncClient": "httpx.AsyncClient" in adapter_source,
        "PlatformStatus.CONNECTING": "PlatformStatus.CONNECTING" in adapter_source,
        "PlatformStatus.ONLINE": "PlatformStatus.ONLINE" in adapter_source,
        "PlatformStatus.OFFLINE": "PlatformStatus.OFFLINE" in adapter_source,
        "self._http connection pool": "self._http" in adapter_source,
        "_build_cookie extracted": "def _build_cookie" in adapter_source,
        "send_message is sync NOT async": "async def send_message" not in adapter_source,
        "NO old _poll_messages": "def _poll_messages(self):" not in adapter_source,
        "NO dead _async_send_message": "async def _async_send_message" not in adapter_source,
        "NO raw string status": 'set_status("connecting"' not in adapter_source,
        "NO sync httpx.get": "httpx.get(" not in adapter_source,
        "NO run_in_executor for user": "run_in_executor(None" not in adapter_source,
        "poll uses async sleep": "self._sleep(" in adapter_source,
    }

    all_ok = True
    for label, ok in checks.items():
        if not ok:
            print(f"  FAIL: {label}")
            all_ok = False

    lines = adapter_source.count("\n")
    print(f"  行数: {lines}")
    if 380 <= lines <= 420:
        print(f"  OK: 行数合理")
    else:
        print(f"  WARN: 行数 {lines}")

    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


def test_async_methods():
    """L1: 异步方法签名验证（AST 级）"""
    print("\n=== L1 异步方法签名 ===")

    cls = get_class("BilibiliAdapter")
    if cls is None:
        print("  FAIL: 找不到 BilibiliAdapter 类")
        return False

    async_methods, sync_methods, _ = classify_methods(cls)

    # 必须是 async 的
    must_async = ["_async_loop", "_async_poll", "_sync_history", "_get_user_name"]
    # 必须是 sync 的
    must_sync = ["send_message", "connect", "disconnect", "_parse_message", "_build_cookie"]

    all_ok = True
    for m in must_async:
        if m not in async_methods:
            print(f"  FAIL: {m} 应该是 async，实际是 sync 或不存在")
            all_ok = False

    for m in must_sync:
        if m in async_methods:
            print(f"  FAIL: {m} 应该是 sync，实际是 async")
            all_ok = False

    print(f"  async 方法 ({len(async_methods)}): {async_methods}")
    print(f"  sync 方法 ({len(sync_methods)}): {sync_methods}")
    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


def test_asyncio_gather_usage():
    """L2: 验证 asyncio.gather 的并发结构"""
    print("\n=== L2 asyncio.gather 并发结构 ===")

    method = get_method(get_class("BilibiliAdapter"), "_async_poll")
    if method is None:
        print("  FAIL: _async_poll 方法不存在")
        return False

    source = ast.get_source_segment(adapter_source, method)
    if source is None:
        print("  FAIL: 无法获取 _async_poll 源码")
        return False

    all_ok = True
    checks = {
        "asyncio.gather(*tasks": "asyncio.gather(*tasks" in source,
        "sess.fetch_session_msgs": "sess.fetch_session_msgs" in source,
        "sess.get_sessions": "sess.get_sessions" in source,
        "async sleep in poll": "self._sleep(" in source,
        "nest async poll_one": "async def poll_one" in source,
        "for s in sessions (task creation)": "for s in sessions" in source,
    }

    print(f"  _async_poll 源码行数: {source.count(chr(10))}")
    for label, ok in checks.items():
        if not ok:
            print(f"  FAIL: {label}")
            all_ok = False

    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


def test_async_loop_structure():
    """L3: _async_loop 生命周期结构"""
    print("\n=== L3 _async_loop 生命周期 ===")

    method = get_method(get_class("BilibiliAdapter"), "_async_loop")
    if method is None:
        print("  FAIL: _async_loop 不存在")
        return False

    source = ast.get_source_segment(adapter_source, method)
    if source is None:
        print("  FAIL: 无法获取源码")
        return False

    all_ok = True
    checks = {
        "httpx.AsyncClient": "httpx.AsyncClient" in source,
        "async with ... as self._http": "as self._http" in source,
        "sync_history first": "_sync_history()" in source,
        "while self._running": "while self._running" in source,
        "poll loop": "_async_poll()" in source,
    }

    for label, ok in checks.items():
        if not ok:
            print(f"  FAIL: {label}")
            all_ok = False

    # 检查调用顺序：sync_history 在 poll 之前
    hist_pos = source.find("_sync_history()")
    poll_pos = source.find("_async_poll()")
    if hist_pos >= 0 and poll_pos >= 0 and hist_pos < poll_pos:
        print("  OK: sync_history 在 poll 之前调用")
    elif hist_pos >= 0 and poll_pos >= 0:
        print("  FAIL: poll 在 sync_history 之前! 顺序错误")
        all_ok = False

    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


def test_send_message_sync():
    """L4: send_message 保持同步"""
    print("\n=== L4 send_message 同步兼容 ===")

    method = get_method(get_class("BilibiliAdapter"), "send_message")
    if method is None:
        print("  FAIL: send_message 不存在")
        return False

    source = ast.get_source_segment(adapter_source, method)
    if source is None:
        print("  FAIL: 无法获取源码")
        return False

    checks = {
        "is sync (def, not async def)": "async def send_message" not in adapter_source,
        "uses bsync()": "sync as bsync" in source or "bsync(" in source,
        "session.send_msg": "session.send_msg" in source,
    }

    all_ok = True
    for label, ok in checks.items():
        status = "OK" if ok else "FAIL"
        if not ok:
            print(f"  {status}: {label}")
            all_ok = False

    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


def test_run_method():
    """L5: run() 入口验证"""
    print("\n=== L5 run() asyncio 入口 ===")

    method = get_method(get_class("BilibiliAdapter"), "run")
    if method is None:
        print("  FAIL: run() 不存在")
        return False

    source = ast.get_source_segment(adapter_source, method)
    if source is None:
        print("  FAIL: 无法获取源码")
        return False

    all_ok = True
    checks = {
        "asyncio.run": "asyncio.run(self._async_loop())" in source,
        "PlatformStatus.CONNECTING": "PlatformStatus.CONNECTING" in source,
        "PlatformStatus.ONLINE": "PlatformStatus.ONLINE" in source,
        "PlatformStatus.OFFLINE": "PlatformStatus.OFFLINE" in source,
        "PlatformStatus.ERROR": "PlatformStatus.ERROR" in source,
        "connect first": "self.connect()" in source,
        "disconnect in finally": "self.disconnect()" in source,
    }

    for label, ok in checks.items():
        if not ok:
            print(f"  FAIL: {label}")
            all_ok = False

    # 验证 connect 在 asyncio.run 之前
    conn_pos = source.find("self.connect()")
    asyncio_pos = source.find("asyncio.run")
    if conn_pos >= 0 and asyncio_pos >= 0 and conn_pos < asyncio_pos:
        print("  OK: connect 在 asyncio.run 之前")
    else:
        print("  FAIL: connect/asyncio.run 顺序异常")
        all_ok = False

    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


def test_get_user_name_async():
    """L6: _get_user_name 改用 async httpx"""
    print("\n=== L6 _get_user_name 异步化 ===")

    method = get_method(get_class("BilibiliAdapter"), "_get_user_name")
    if method is None:
        print("  FAIL: _get_user_name 不存在")
        return False

    source = ast.get_source_segment(adapter_source, method)
    if source is None:
        print("  FAIL: 无法获取源码")
        return False

    all_ok = True
    checks = {
        "is async": isinstance(method, ast.AsyncFunctionDef),
        "uses self._http": "self._http.get(" in source,
        "NO httpx.get (old sync)": "httpx.get(" not in source,
        "uses _build_cookie": "self._build_cookie()" in source,
    }

    for label, ok in checks.items():
        if not ok:
            print(f"  FAIL: {label}")
            all_ok = False

    print(f"  结果: {'ALL OK' if all_ok else 'SOME FAILED'}")
    return all_ok


# ── Main ──

if __name__ == "__main__":
    print("=" * 60)
    print("  B站异步轮询 — 代码级七层验证 (纯AST)")
    print("=" * 60)

    results = [
        ("L0 结构完整性 (19项检查)", test_structural()),
        ("L1 异步方法签名", test_async_methods()),
        ("L2 asyncio.gather 并发结构", test_asyncio_gather_usage()),
        ("L3 _async_loop 生命周期顺序", test_async_loop_structure()),
        ("L4 send_message 同步兼容", test_send_message_sync()),
        ("L5 run() asyncio 入口", test_run_method()),
        ("L6 _get_user_name 异步化", test_get_user_name_async()),
    ]

    print("\n" + "=" * 60)
    print("  总结果")
    print("=" * 60)
    passed = 0
    for name, ok in results:
        status = "OK" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"  [{status}] {name}")
    print(f"\n  {passed}/{len(results)} 通过")

    if passed == len(results):
        print("\n  全部通过 — 异步改造验证成功")
    else:
        print(f"\n  {len(results) - passed} 项未通过，请检查")
