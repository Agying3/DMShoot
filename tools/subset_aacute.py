"""命令行重建 AaCute UI 字体子集。

运行方式::

    python tools/subset_aacute.py

实际构建逻辑位于 ``dmshoot.core.font_builder``，GUI 同步按钮也复用同一套
逻辑，避免开发态和运行态的扫描规则发生漂移。
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dmshoot.core.font_builder import build_ui_subset  # noqa: E402


def main() -> int:
    font_dir = Path(__file__).resolve().parent / "fonts"
    try:
        result = build_ui_subset(font_dir)
    except RuntimeError as exc:
        print(f"跳过: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 1

    print(
        f"扫描文件: {result['files']}   UI 汉字: {result['chars']}   "
        f"总字形: {result['total']}"
    )
    print(f"生成: {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
