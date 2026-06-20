"""DMShoot 自动化测试入口

用法:
    python run_tests.py              # 运行全部可自动化的测试
    python run_tests.py --core       # 仅核心逻辑（无需 GUI）
    python run_tests.py --gui        # 仅 GUI 相关（需要 PySide6）
    python run_tests.py --quick      # 仅快速测试（跳过含 sleep 的测试）

退出码: 0=全部通过, 1=有失败
"""

import subprocess
import sys
import time
import os
from pathlib import Path

PROJECT = Path(__file__).parent
VENV_PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"
MANAGED_PYTHON = Path(sys.executable)

# ── 测试分类 ──
CORE_TESTS = [
    "test_concurrency.py",
    "test_perf_monitor.py",
    "test_proto_sync.py",
    "test_icons.py",
    "test_xhs.py",
    "test_bilibili_async.py",
]

GUI_TESTS = [
    "test_dmshoot.py",
    "test_dmshoot_gui.py",
    "test_integration.py",
    "test_new_features.py",
    "test_rate_limiter.py",
    "test_go_bridge.py",
]

MANUAL_TESTS = [
    "test_dmshoot_douyin.py",   # 需要抖音 cookie
    "test_screenshot.py",       # 需要显示屏
    "test_douyin_client.py",    # 需要真实连接
]

# 哪个 Python 有 PySide6
HAS_PYSIDE6 = VENV_PYTHON.exists()

# 慢测试需要更长超时
SLOW_TESTS = {"test_rate_limiter.py", "test_dmshoot.py", "test_dmshoot_gui.py"}


def get_python(needs_gui=False):
    """选择合适的 Python 解释器"""
    if needs_gui and HAS_PYSIDE6:
        return str(VENV_PYTHON)
    return str(MANAGED_PYTHON)


def run_test(test_file, python=None, timeout=30):
    """运行单个测试文件，返回 (passed, total, output, elapsed_ms)"""
    py = python or str(MANAGED_PYTHON)
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            [py, "-u", str(PROJECT / test_file)],
            capture_output=True, timeout=timeout,
            cwd=str(PROJECT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            encoding="utf-8", errors="replace",
        )
        elapsed = int((time.perf_counter() - t0) * 1000)
        output = (r.stdout or "") + "\n" + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 0, 0, "TIMEOUT", timeout * 1000

    # 统计结果
    passed = output.count("[OK]")
    # 兼容 [FAIL] 和 ✗ 等各种标记
    failed = output.count("[FAIL]") + output.count("\u2717")

    # 有些测试用 Passed: X/Y 格式
    import re
    m = re.search(r'(\d+)/(\d+)\s+通过', output)
    if m:
        passed = int(m.group(1))
        failed = int(m.group(2)) - passed

    # bilibili_async 用 "通过" 关键字
    m = re.search(r'(\d+)/(\d+)\s+通过', output)
    if m:
        passed = int(m.group(1))
        failed = int(m.group(2)) - passed

    return passed, passed + failed, output, elapsed


def main():
    args = set(sys.argv[1:])
    core_only = "--core" in args
    gui_only = "--gui" in args
    quick = "--quick" in args
    verbose = "-v" in args

    if core_only:
        test_list = CORE_TESTS
    elif gui_only:
        test_list = GUI_TESTS
    elif quick:
        test_list = [t for t in CORE_TESTS + GUI_TESTS
                     if t not in SLOW_TESTS]
    else:
        test_list = CORE_TESTS + GUI_TESTS

    print("=" * 60)
    print("  DMShoot 自动化测试")
    print(f"  Python: {MANAGED_PYTHON.name if core_only else 'auto'}")
    print(f"  模式: {'核心' if core_only else 'GUI' if gui_only else '快速' if quick else '全部'}")
    print(f"  测试数: {len(test_list)}")
    print("=" * 60)

    results = []
    total_passed = 0
    total_tests = 0
    t0 = time.perf_counter()

    for test_file in test_list:
        needs_gui = test_file in GUI_TESTS
        py = get_python(needs_gui)
        py_name = "venv" if "venv" in py else "core"
        timeout = 120 if test_file in SLOW_TESTS else 30

        passed, total, output, elapsed = run_test(test_file, py, timeout)
        pct = f"{100*passed//total}%" if total > 0 else "N/A"
        status = "OK" if passed == total else ("ERR" if passed == 0 else "PART")
        marker = { "OK": "+", "ERR": "!", "PART": "~" }.get(status, "?")

        print(f"  [{marker}] {test_file:<28s} {passed}/{total} ({pct})  {elapsed}ms  [{py_name}]")

        results.append((test_file, passed, total, status, output))
        total_passed += passed
        total_tests += total
        total_pct = f"{100*total_passed//total_tests}%" if total_tests > 0 else "N/A"

    elapsed_total = int((time.perf_counter() - t0) * 1000)

    print()
    print("=" * 60)
    print(f"  总计: {total_passed}/{total_tests} ({total_pct})  {elapsed_total}ms")
    print("=" * 60)

    # ── 失败详情 ──
    failed_tests = [(n, p, t, s, o) for n, p, t, s, o in results if s != "OK"]
    if failed_tests:
        print(f"\n  {len(failed_tests)} 个测试未全通过:")
        for name, passed, total, status, output in failed_tests:
            print(f"    [{status}] {name} ({passed}/{total})")
            if verbose and "Error" in output:
                for line in output.split("\n")[-5:]:
                    if line.strip():
                        print(f"      {line.strip()[:100]}")

    # ── 提示手动测试 ──
    if not (core_only or gui_only or quick):
        print(f"\n  手动测试（需 cookie/显示屏）: {', '.join(MANUAL_TESTS)}")

    # 退出码
    sys.exit(0 if not failed_tests else 1)


if __name__ == "__main__":
    main()
