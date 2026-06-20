"""DMShoot ConcurrencyManager 测试 — 纯 Python，无需 PySide6

运行: python test_concurrency.py
覆盖: 单例 / 优先级调度 / 背压控制 / 统计 / 关闭 / 线程安全
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


# ── 准备工作 ──
from dmshoot.core.concurrency import ConcurrencyManager

def setup():
    ConcurrencyManager.reset()


# ═══════════════════════════════════════════════════════════
# 1. 单例模式
# ═══════════════════════════════════════════════════════════
def test_singleton():
    print("\n=== 单例 ===")
    setup()
    a = ConcurrencyManager.instance()
    b = ConcurrencyManager.instance()
    check("same instance", a is b)
    check("class has _lock", hasattr(ConcurrencyManager, "_lock"))


# ═══════════════════════════════════════════════════════════
# 2. 基础任务提交
# ═══════════════════════════════════════════════════════════
def test_submit_basic():
    print("\n=== 基础提交 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    results = []
    def task(x):
        results.append(x)
        return x * 2

    f = mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin", task, 42)
    check("submit returns Future", f is not None)
    val = f.result(timeout=5)
    check("future result", val == 84)
    check("task executed", 42 in results)


def test_submit_order():
    print("\n=== 提交顺序 ===")
    setup()
    mgr = ConcurrencyManager.instance()
    order = []
    lock = threading.Lock()

    def ordered_task(n):
        with lock:
            order.append(n)
        time.sleep(0.01)

    futs = []
    for i in range(5):
        f = mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin", ordered_task, i)
        if f:
            futs.append(f)
    for f in futs:
        f.result(timeout=10)
    check("all 5 submitted", len(futs) == 5)
    check("all 5 executed", len(order) == 5)


# ═══════════════════════════════════════════════════════════
# 3. 优先级调度：HIGH 永远不拒绝
# ═══════════════════════════════════════════════════════════
def test_high_priority_never_rejected():
    print("\n=== HIGH 优先级永不拒绝 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    # 填满平台队列
    for i in range(65):
        mgr.submit(ConcurrencyManager.PRIO_LOW, "douyin",
                   lambda: time.sleep(0.05))

    # HIGH 仍应被接受
    f = mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin",
                   lambda x: x, 999)
    check("HIGH accepted despite full queue", f is not None)
    if f:
        check("HIGH result", f.result(timeout=10) == 999)


# ═══════════════════════════════════════════════════════════
# 4. 背压控制：超过阈值拒绝
# ═══════════════════════════════════════════════════════════
def test_backpressure_total_queue():
    print("\n=== 背压 — 总队列 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    # 填满总队列（200 个 MEDIUM 任务分散到不同平台）
    accepted = 0
    rejected = 0
    for i in range(250):
        plat = f"p{i % 4}"
        f = mgr.submit(ConcurrencyManager.PRIO_MEDIUM, plat,
                       lambda: time.sleep(0.1))
        if f:
            accepted += 1
        else:
            rejected += 1

    check("some accepted", accepted > 0)
    check("some rejected after full", rejected > 0)
    check("total approx 200", accepted <= 210)


def test_backpressure_platform_queue():
    print("\n=== 背压 — 单平台 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    rejected = 0
    for i in range(80):
        f = mgr.submit(ConcurrencyManager.PRIO_MEDIUM, "douyin",
                       lambda: time.sleep(0.1))
        if f is None:
            rejected += 1

    check("platform queue rejected some", rejected > 0)
    # 最多 60 个被接受
    check("platform max ~60", 80 - rejected <= 61)


def test_low_priority_rejected():
    print("\n=== LOW 优先级被拒绝 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    # 填满
    for i in range(65):
        mgr.submit(ConcurrencyManager.PRIO_LOW, "douyin",
                   lambda: time.sleep(0.1))

    f = mgr.submit(ConcurrencyManager.PRIO_LOW, "douyin",
                   lambda: 42)
    check("LOW rejected when full", f is None)


# ═══════════════════════════════════════════════════════════
# 5. 统计
# ═══════════════════════════════════════════════════════════
def test_stats():
    print("\n=== 统计 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin",
               lambda: time.sleep(0.05))
    mgr.submit(ConcurrencyManager.PRIO_HIGH, "bilibili",
               lambda: time.sleep(0.05))

    import time as _time
    _time.sleep(0.02)

    s = mgr.stats()
    check("stats has total_tasks", "total_tasks" in s)
    check("stats has by_platform", "by_platform" in s)
    check("stats has max_workers", "max_workers" in s)
    check("stats by_platform is dict", isinstance(s["by_platform"], dict))
    check("max_workers > 0", s["max_workers"] > 0)


# ═══════════════════════════════════════════════════════════
# 6. shutdown
# ═══════════════════════════════════════════════════════════
def test_shutdown():
    print("\n=== 关闭 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    mgr.shutdown(wait=True)
    f = mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin",
                   lambda: 42)
    check("submit after shutdown returns None", f is None)


# ═══════════════════════════════════════════════════════════
# 7. reset
# ═══════════════════════════════════════════════════════════
def test_reset():
    print("\n=== 重置 ===")
    setup()
    mgr1 = ConcurrencyManager.instance()
    ConcurrencyManager.reset()
    mgr2 = ConcurrencyManager.instance()
    check("different after reset", mgr1 is not mgr2)


# ═══════════════════════════════════════════════════════════
# 8. 异常处理
# ═══════════════════════════════════════════════════════════
def test_exception_in_task():
    print("\n=== 任务异常 ===")
    setup()
    mgr = ConcurrencyManager.instance()

    def boom():
        raise ValueError("test error")

    f = mgr.submit(ConcurrencyManager.PRIO_HIGH, "douyin", boom)
    check("submit succeeds for exception task", f is not None)

    # 等待任务执行
    import time as _time
    _time.sleep(0.1)

    # 任务计数应恢复
    s = mgr.stats()
    check("task count back to 0 after exception",
          s["total_tasks"] == 0)


# ═══════════════════════════════════════════════════════════
# 9. 常量正确性
# ═══════════════════════════════════════════════════════════
def test_constants():
    print("\n=== 常量 ===")
    check("PRIO_HIGH=0", ConcurrencyManager.PRIO_HIGH == 0)
    check("PRIO_MEDIUM=1", ConcurrencyManager.PRIO_MEDIUM == 1)
    check("PRIO_LOW=2", ConcurrencyManager.PRIO_LOW == 2)
    check("MAX_QUEUE=200", ConcurrencyManager.MAX_QUEUE_DEPTH == 200)
    check("MAX_PLATFORM=60", ConcurrencyManager.MAX_PLATFORM_QUEUE == 60)


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  DMShoot ConcurrencyManager 测试")
    print("=" * 55)

    test_singleton()
    test_submit_basic()
    test_submit_order()
    test_high_priority_never_rejected()
    test_backpressure_total_queue()
    test_backpressure_platform_queue()
    test_low_priority_rejected()
    test_stats()
    test_shutdown()
    test_reset()
    test_exception_in_task()
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
