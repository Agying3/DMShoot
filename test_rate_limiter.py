"""DMShoot RateLimiter 测试 — 纯 Python，无需任何依赖

运行: python test_rate_limiter.py
覆盖: token bucket 算法 / burst / 限流 / 统计 / 线程安全 / 多平台
"""

import sys, os, time, threading
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
# 1. 基础 acquire — token bucket
# ═══════════════════════════════════════════════════════════
def test_basic_acquire():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== 基础 acquire ===")
    rl = RateLimiter(rate=100.0, burst=10)

    # burst=10, 前10次应全部成功
    for i in range(10):
        check(f"acquire #{i+1}", rl.acquire())

    # 第11次应被限流
    check("acquire #11 rejected", not rl.acquire())


def test_refill_over_time():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== 时间恢复 ===")
    rl = RateLimiter(rate=100.0, burst=5)

    # 用完 tokens
    for _ in range(5):
        rl.acquire()
    check("empty after burst", not rl.acquire())

    # 等 0.05 秒 (rate=100/s, 应恢复 ~5 tokens)
    time.sleep(0.05)
    recovered = 0
    for _ in range(6):
        if rl.acquire():
            recovered += 1
        else:
            break
    check("refilled >= 3 tokens", recovered >= 3)


def test_burst_limit():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== burst 上限 ===")
    rl = RateLimiter(rate=1.0, burst=3)

    # 等 0.5 秒，token 不应超过 burst=3
    time.sleep(0.5)
    acquired = 0
    for _ in range(10):
        if rl.acquire():
            acquired += 1
        else:
            break
    check("never exceeds burst(3)", acquired == 3)


# ═══════════════════════════════════════════════════════════
# 2. available 属性
# ═══════════════════════════════════════════════════════════
def test_available():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== available ===")
    rl = RateLimiter(rate=10.0, burst=10)

    check("init available=10", abs(rl.available - 10.0) < 0.1)

    rl.acquire()
    check("after 1 acquire ≈9", abs(rl.available - 9.0) < 0.1)

    rl.acquire()
    check("after 2 acquire ≈8", abs(rl.available - 8.0) < 0.1)


# ═══════════════════════════════════════════════════════════
# 3. stats
# ═══════════════════════════════════════════════════════════
def test_stats():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== stats ===")
    rl = RateLimiter(rate=100.0, burst=10)

    for _ in range(10):
        rl.acquire()
    rl.acquire()  # 被拒绝
    rl.acquire()  # 被拒绝

    s = rl.stats
    check("stats sent=10", s["sent"] == 10)
    check("stats throttled=2", s["throttled"] == 2)
    check("stats rate=100", s["rate"] == 100.0)
    check("stats burst=10", s["burst"] == 10)
    check("has available", "available" in s)


# ═══════════════════════════════════════════════════════════
# 4. reset
# ═══════════════════════════════════════════════════════════
def test_reset():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== reset ===")
    rl = RateLimiter(rate=100.0, burst=10)

    for _ in range(10):
        rl.acquire()
    rl.acquire()  # 拒绝

    rl.reset()
    s = rl.stats
    check("reset sent=0", s["sent"] == 0)
    check("reset throttled=0", s["throttled"] == 0)
    check("reset available=10", abs(rl.available - 10.0) < 0.1)
    check("reset allows acquire", rl.acquire())


# ═══════════════════════════════════════════════════════════
# 5. set_rate 动态调速
# ═══════════════════════════════════════════════════════════
def test_set_rate():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== set_rate ===")
    rl = RateLimiter(rate=100.0, burst=5)

    rl.set_rate(1.0)
    check("rate changed to 1.0", rl._rate == 1.0)

    # 用完 burst
    for _ in range(5):
        rl.acquire()

    # 新 rate=1.0/s, 等 0.1s 只能恢复 0.1 token
    time.sleep(0.1)
    check("slow rate rejects", not rl.acquire())

    # 等够 1s
    time.sleep(1.0)
    check("slow rate allows after 1s", rl.acquire())


def test_set_rate_minimum():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== set_rate 最小值 ===")
    rl = RateLimiter(rate=10.0)
    rl.set_rate(0.0)
    check("rate clamped to 0.1", rl._rate == 0.1)
    rl.set_rate(-5.0)
    check("negative clamped to 0.1", rl._rate == 0.1)


# ═══════════════════════════════════════════════════════════
# 6. 线程安全
# ═══════════════════════════════════════════════════════════
def test_thread_safety():
    from dmshoot.core.rate_limiter import RateLimiter
    print("\n=== 线程安全 ===")
    rl = RateLimiter(rate=1000.0, burst=200)
    acquired = [0]
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            if rl.acquire():
                with lock:
                    acquired[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("4 threads acquired 200 total", acquired[0] == 200)
    check("stats match", rl.stats["sent"] == 200)


# ═══════════════════════════════════════════════════════════
# 7. 平台限流器
# ═══════════════════════════════════════════════════════════
def test_platform_limiter():
    from dmshoot.core.rate_limiter import get_limiter, _limiters
    print("\n=== 平台限流器 ===")

    # 清理之前的状态
    _limiters.clear()

    dy = get_limiter("douyin")
    check("douyin rate=5", dy._rate == 5.0)
    check("douyin burst=10", dy._burst == 10)

    bl = get_limiter("bilibili")
    check("bilibili rate=10", bl._rate == 10.0)
    check("bilibili burst=20", bl._burst == 20)

    # 相同平台返回同一个实例
    dy2 = get_limiter("douyin")
    check("same platform same instance", dy is dy2)

    # 未知平台回退到默认 rate=5
    unknown = get_limiter("wechat")
    check("unknown platform rate=5", unknown._rate == 5.0)


def test_platform_limiter_isolation():
    from dmshoot.core.rate_limiter import get_limiter, _limiters
    print("\n=== 平台隔离 ===")
    _limiters.clear()

    dy = get_limiter("douyin")
    bl = get_limiter("bilibili")

    # 耗尽抖音的 tokens
    for _ in range(10):
        dy.acquire()
    check("douyin empty", not dy.acquire())

    # B站不受影响
    check("bilibili still has tokens", bl.acquire())


def test_get_all_stats():
    from dmshoot.core.rate_limiter import get_limiter, get_all_stats, _limiters
    print("\n=== get_all_stats ===")
    _limiters.clear()

    get_limiter("douyin")
    get_limiter("bilibili")

    all_stats = get_all_stats()
    check("all_stats has douyin", "douyin" in all_stats)
    check("all_stats has bilibili", "bilibili" in all_stats)
    check("stats are dicts", isinstance(all_stats["douyin"], dict))


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  DMShoot RateLimiter 测试 (L1 单元测试)")
    print("=" * 55)

    test_basic_acquire()
    test_refill_over_time()
    test_burst_limit()
    test_available()
    test_stats()
    test_reset()
    test_set_rate()
    test_set_rate_minimum()
    test_thread_safety()
    test_platform_limiter()
    test_platform_limiter_isolation()
    test_get_all_stats()

    total = len(_results)
    passed = sum(1 for _, ok_, _ in _results if ok_)
    failed_list = [(n, r) for n, ok_, r in _results if not ok_]
    print(f"\n{'=' * 55}")
    print(f"  {passed}/{total} 通过 ({100 * passed // total}%)" if total else "")
    if failed_list:
        print(f"  {len(failed_list)} 失败:")
        for name, reason in failed_list:
            print(f"    [{name}] {reason}")
    print("=" * 55)
    sys.exit(0 if not failed_list else 1)
