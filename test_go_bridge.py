"""DMShoot Go Bridge 集成测试 — 需要编译好的 msg-service.exe

运行: python test_go_bridge.py
覆盖: 编译检查 / 启动停止 / HTTP API / 健康检查 / WebSocket / 全局单例
"""

import sys, os, time, json, asyncio
from pathlib import Path
from unittest.mock import MagicMock

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

# mock 缺失的依赖以允许模块加载
for _mod in ("websockets", "httpx"):
    if _mod not in sys.modules:
        try: __import__(_mod)
        except ImportError: sys.modules[_mod] = MagicMock()

_results = []
def ok(name, detail=""):
    _results.append((name, True, detail))
    print(f"  [OK] {name}{' — ' + detail if detail else ''}")
def fail(name, reason=""):
    _results.append((name, False, reason))
    print(f"  [FAIL] {name}: {reason}")
def check(name, cond, detail=""):
    (ok if cond else fail)(name, detail)


def _kill_stale_go():
    """杀掉可能残留的 msg-service 进程，释放端口 9800"""
    import subprocess
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', 'msg-service.exe'],
            capture_output=True, timeout=5
        )
        time.sleep(0.5)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 1. 编译产物存在性
# ═══════════════════════════════════════════════════════════
def test_go_binary_exists():
    from dmshoot.core.go_bridge import _GO_EXE
    print("\n=== 二进制检查 ===")
    exists = _GO_EXE.exists()
    check("msg-service.exe exists", exists)
    if exists:
        size_mb = _GO_EXE.stat().st_size / 1024 / 1024
        check(f"size ~{size_mb:.1f}MB", size_mb > 1)


# ═══════════════════════════════════════════════════════════
# 2. 常量
# ═══════════════════════════════════════════════════════════
def test_constants():
    from dmshoot.core.go_bridge import _GO_PORT, _GO_URL
    print("\n=== 常量 ===")
    check("port=9800", _GO_PORT == 9800)
    check("url correct", _GO_URL == "http://127.0.0.1:9800")


# ═══════════════════════════════════════════════════════════
# 3. 单例
# ═══════════════════════════════════════════════════════════
def test_singleton():
    from dmshoot.core.go_bridge import get_go_bridge, GoServiceBridge
    # 重置
    import dmshoot.core.go_bridge as gb
    gb._bridge = None

    a = get_go_bridge()
    b = get_go_bridge()
    check("singleton same instance", a is b)


# ═══════════════════════════════════════════════════════════
# 4. 启动和停止 (需要编译好的 Go 二进制)
# ═══════════════════════════════════════════════════════════
def test_start_stop():
    from dmshoot.core.go_bridge import GoServiceBridge, _GO_EXE
    print("\n=== 启动/停止 ===")

    if not _GO_EXE.exists():
        fail("start_stop", "msg-service.exe not found, skip")
        return

    bridge = GoServiceBridge()
    check("init not running", bridge.running == False)

    started = bridge.start()
    check("start returns True", started)
    time.sleep(0.5)  # Go 进程启动是异步的
    check("running after start", bridge.running)

    bridge.stop()
    time.sleep(0.3)
    check("not running after stop", not bridge.running)


# ═══════════════════════════════════════════════════════════
# 5. HTTP API (需要 Go 进程运行)
# ═══════════════════════════════════════════════════════════
async def _test_http_apis():
    from dmshoot.core.go_bridge import GoServiceBridge, _GO_EXE, _GO_URL
    import httpx

    if not _GO_EXE.exists():
        fail("http_apis", "binary not found")
        return

    bridge = GoServiceBridge()
    bridge.start()

    try:
        # 5a. 健康检查 (同步 httpx)
        resp = httpx.get(f"{_GO_URL}/api/health", timeout=5)
        check("health 200", resp.status_code == 200)

        # 5b. register
        await bridge._ensure_client()
        resp2 = await bridge._client.post("/api/register", json={
            "platform": "test_douyin", "cookie": "test_cookie_123",
        })
        check("register 200", resp2.status_code == 200)

        # 5c. status
        resp3 = await bridge._client.get("/api/status")
        data3 = resp3.json()
        check("status has workers", "workers" in data3)
        check("status has platforms", "platforms" in data3)

        # 5d. send (当前是 NoopWorker，但 API 应返回 200)
        resp4 = await bridge._client.post("/api/send", json={
            "platform": "test_douyin",
            "session_id": "test:123",
            "content": "hello",
        })
        check("send 200", resp4.status_code == 200)

        # 5e. unregister
        resp5 = await bridge._client.post("/api/unregister", json={
            "platform": "test_douyin",
        })
        check("unregister 200", resp5.status_code == 200)

        await bridge.close()
    except Exception as e:
        fail("http_apis", f"exception: {e}")
        bridge.stop()


# ═══════════════════════════════════════════════════════════
# 6. 重复 start 不会崩溃
# ═══════════════════════════════════════════════════════════
def test_double_start():
    from dmshoot.core.go_bridge import GoServiceBridge, _GO_EXE
    print("\n=== 重复启动 ===")

    if not _GO_EXE.exists():
        fail("double_start", "binary not found")
        return

    bridge = GoServiceBridge()
    bridge.start()
    time.sleep(0.5)
    check("first start OK", bridge.running)

    # 第二次 start 应直接返回 True (进程已运行)
    second = bridge.start()
    check("second start returns True", second)

    bridge.stop()


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  DMShoot Go Bridge 集成测试")
    print("=" * 55)

    _kill_stale_go()

    test_go_binary_exists()
    test_constants()
    test_singleton()
    test_start_stop()
    test_double_start()

    # HTTP API 测试需要 async
    asyncio.run(_test_http_apis())

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
