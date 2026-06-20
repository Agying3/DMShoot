"""DMShoot WAL 紧急恢复工具
用法: python tools/wal_checkpoint.py [--force]
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "dmshoot" / "data" / "dmshoot.db"


def main():
    force = "--force" in sys.argv

    if not DB_PATH.exists():
        print(f"错误: 数据库文件不存在 {DB_PATH}")
        sys.exit(1)

    wal_path = DB_PATH.with_suffix(DB_PATH.suffix + "-wal")
    wal_size_mb = wal_path.stat().st_size / 1024 / 1024 if wal_path.exists() else 0

    print(f"数据库: {DB_PATH}")
    print(f"WAL 文件: {wal_path} ({wal_size_mb:.1f} MB)")

    if wal_size_mb == 0:
        print("WAL 文件为空，无需 checkpoint")
        return

    if wal_size_mb > 10 and not force:
        print(f"\n⚠️  WAL 文件较大 ({wal_size_mb:.1f} MB)，可能包含大量未写入数据")
        print("   如果 DMShoot 仍在运行，先关闭它再执行")
        print("   添加 --force 强制执行")
        sys.exit(1)

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        busy, checkpointed, pages = result.fetchone()
        conn.close()
        print(f"\n✅ checkpoint 完成:")
        print(f"   busy={busy}, checkpointed={checkpointed}, pages={pages}")
    except sqlite3.OperationalError as e:
        print(f"\n❌ 操作失败: {e}")
        print("   可能原因: DMShoot 正在写入，稍后重试")
        sys.exit(1)


if __name__ == "__main__":
    main()
