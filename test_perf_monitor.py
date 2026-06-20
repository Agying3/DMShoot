"""DMShoot PerfMonitor + Metric 测试 — 纯 Python，无需 PySide6

运行: python test_perf_monitor.py
覆盖: Metric 环形缓冲 / 状态判断 / PerfMonitor 单例 / 指标注入点
"""

import sys, os, time
from pathlib import Path
from unittest.mock import MagicMock

PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

# 如果 psutil 未安装，注入 mock 以允许 perf_monitor 模块加载
try:
    import psutil
except ImportError:
    sys.modules['psutil'] = MagicMock()
    sys.modules['psutil'].Process = MagicMock

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
# 1. Metric 类 — 基本操作
# ═══════════════════════════════════════════════════════════
def test_metric_basic():
    from dmshoot.core.perf_monitor import Metric

    print("\n=== Metric 基本操作 ===")
    m = Metric("test", "ms", 100, 500, "0~100ms", max_points=5)

    check("name", m.name == "test")
    check("unit", m.unit == "ms")
    check("low_warn", m.low_warn == 100)
    check("high_warn", m.high_warn == 500)

    m.push(10)
    check("latest after push", m.latest == 10)
    check("values list", m.values == [10])

    m.push(20)
    m.push(30)
    check("latest after 3 pushes", m.latest == 30)
    check("values length 3", len(m.values) == 3)


def test_metric_ring_buffer():
    from dmshoot.core.perf_monitor import Metric

    print("\n=== Metric 环形缓冲 ===")
    m = Metric("buf", "条", 5, 10, max_points=3)

    for i in range(5):
        m.push(i * 10)

    check("max size 3", len(m.values) == 3)
    check("drops oldest", m.values == [20, 30, 40])


def test_metric_status():
    from dmshoot.core.perf_monitor import Metric

    print("\n=== Metric 状态判断 ===")
    m = Metric("status", "%", 1, 5, max_points=10)

    m.push(0.5)
    check("0.5 = normal", m.status == "normal")

    m.push(3.0)
    check("3.0 = warning", m.status == "warning")

    m.push(10.0)
    check("10.0 = critical", m.status == "critical")

    # 边界
    m2 = Metric("edge", "", 50, 100)
    m2.push(50)
    check("exact low_warn = warning", m2.status == "warning")
    m2.push(100)
    check("exact high_warn = critical", m2.status == "critical")


def test_metric_empty():
    from dmshoot.core.perf_monitor import Metric

    print("\n=== Metric 空缓冲 ===")
    m = Metric("empty", "", 10, 20)
    check("empty latest = 0", m.latest == 0.0)
    check("empty status = normal", m.status == "normal")
    check("empty values = []", m.values == [])


# ═══════════════════════════════════════════════════════════
# 2. PerfMonitor 单例
# ═══════════════════════════════════════════════════════════
def test_perf_monitor_singleton():
    from dmshoot.core.perf_monitor import PerfMonitor, get_monitor

    print("\n=== PerfMonitor 单例 ===")
    # 重置单例以获取干净的实例
    PerfMonitor._instance = None

    a = PerfMonitor()
    b = get_monitor()
    check("same via constructor and getter", a is b)

    c = PerfMonitor()
    check("same via constructor again", a is c)


# ═══════════════════════════════════════════════════════════
# 3. 指标注入点
# ═══════════════════════════════════════════════════════════
def test_record_api():
    from dmshoot.core.perf_monitor import PerfMonitor

    print("\n=== record_api ===")
    PerfMonitor._instance = None
    pm = PerfMonitor()

    pm.record_api(150.0, is_error=False)
    pm.record_api(300.0, is_error=True)
    pm.record_api(200.0, is_error=False)

    # 3 次 API 调用，1 次错误
    check("api_total=3", pm._api_total == 3)
    check("api_errors=1", pm._api_errors == 1)
    check("last_api_ms=200", pm._last_api_ms == 200.0)

    # 错误率
    pct = pm._get_error_pct()
    check("error_rate ~33%", abs(pct - 33.33) < 1.0)


def test_record_db_write():
    from dmshoot.core.perf_monitor import PerfMonitor

    print("\n=== record_db_write ===")
    PerfMonitor._instance = None
    pm = PerfMonitor()

    pm.record_db_write(45.0)
    check("last_db_ms=45", pm._last_db_ms == 45.0)


def test_record_msg():
    from dmshoot.core.perf_monitor import PerfMonitor

    print("\n=== record_msg + get_msg_rate ===")
    PerfMonitor._instance = None
    pm = PerfMonitor()

    pm.record_msg()
    pm.record_msg()
    pm.record_msg()

    rate = pm._get_msg_rate()
    check("msg_rate=3", rate == 3)

    # 第二次调用应重置
    rate2 = pm._get_msg_rate()
    check("msg_rate reset to 0", rate2 == 0)


def test_error_rate_zero():
    from dmshoot.core.perf_monitor import PerfMonitor

    print("\n=== 错误率 — 除零保护 ===")
    PerfMonitor._instance = None
    pm = PerfMonitor()

    pct = pm._get_error_pct()
    check("no api calls = 0%", pct == 0.0)


# ═══════════════════════════════════════════════════════════
# 4. Metrics 字典
# ═══════════════════════════════════════════════════════════
def test_metrics_dict():
    from dmshoot.core.perf_monitor import PerfMonitor

    print("\n=== Metrics 字典 ===")
    PerfMonitor._instance = None
    pm = PerfMonitor()

    expected = {"pending", "api_ms", "error_pct", "workers_pct",
                "mem_mb", "msg_rate", "db_ms"}
    check("7 metrics", set(pm.metrics.keys()) == expected)

    # 验证每个 metric 都是 Metric 实例
    from dmshoot.core.perf_monitor import Metric
    for name in expected:
        check(f"{name} is Metric", isinstance(pm.metrics[name], Metric))


# ═══════════════════════════════════════════════════════════
# 5. enabled 开关
# ═══════════════════════════════════════════════════════════
def test_enabled_toggle():
    from dmshoot.core.perf_monitor import PerfMonitor

    print("\n=== enabled 开关 ===")
    PerfMonitor._instance = None
    pm = PerfMonitor()

    check("default enabled", pm.enabled == True)
    pm.set_enabled(False)
    check("disabled", pm.enabled == False)
    pm.set_enabled(True)
    check("re-enabled", pm.enabled == True)


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  DMShoot PerfMonitor 测试")
    print("=" * 55)

    test_metric_basic()
    test_metric_ring_buffer()
    test_metric_status()
    test_metric_empty()
    test_perf_monitor_singleton()
    test_record_api()
    test_record_db_write()
    test_record_msg()
    test_error_rate_zero()
    test_metrics_dict()
    test_enabled_toggle()

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
