"""数据库自动备份 — 使用 SQLite backup API（正确处理 WAL），保留最近 N 份

用法:
  python tools/backup_db.py               # 立即备份一次
  python tools/backup_db.py --watch 3600  # 每小时循环备份（Ctrl+C 停止）

接入建议（main.py 数据库初始化后）:
  try:
      from tools.backup_db import backup
      backup()
  except Exception:
      pass
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "dmshoot" / "data"
DB_FILE = DATA_DIR / "dmshoot.db"
BACKUP_DIR = DATA_DIR / "backups"
KEEP = 20  # 保留最近多少份


def backup() -> Path:
    """用 SQLite backup API 复制数据库（自动合并 WAL，无需 checkpoint 顺序）"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_FILE.exists():
        print(f"[backup] 数据库不存在: {DB_FILE}")
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"dmshoot_{ts}.db"

    src = sqlite3.connect(str(DB_FILE))
    dest = sqlite3.connect(str(dst))
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()

    old = sorted(BACKUP_DIR.glob("dmshoot_*.db"))
    for f in old[:-KEEP]:
        f.unlink()

    print(f"[backup] OK → backups/{dst.name} (当前共 {min(len(old), KEEP)} 份)")
    return dst


def main():
    ap = argparse.ArgumentParser(description="DMShoot 数据库备份")
    ap.add_argument("--watch", type=int, default=0, help="间隔秒数，>0 则循环备份")
    args = ap.parse_args()

    if args.watch <= 0:
        backup()
        return
    while True:
        try:
            backup()
        except Exception as e:
            print(f"[backup] 失败: {e}")
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
