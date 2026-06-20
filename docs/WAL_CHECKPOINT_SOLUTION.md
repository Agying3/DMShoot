# DMShoot SQLite WAL 长期稳定方案

## 问题描述

DMShoot 使用 SQLite WAL (Write-Ahead Logging) 模式。当程序崩溃或非正常退出时，
`.db-wal` 文件中积压的未合并写入不会自动写回主 `.db` 文件，导致：

1. **SQLiteStudio 等外部工具无法正常打开** `.db` 文件
2. **数据丢失风险** — WAL 文件被删除或损坏时，未合并的写入永久丢失

实测案例：`dmshoot.db` 144KB，`dmshoot.db-wal` 4MB — 大部分数据都在 WAL 里。

## 根本原因

```
┌─────────────────────────────────────────────────────┐
│                  DMShoot 架构                         │
│                                                      │
│  Python (PySide6 GUI)          Go (msg-service)      │
│  ┌──────────────┐            ┌──────────────┐       │
│  │ database.py  │            │  batch.go    │       │
│  │ WAL 模式     │            │  WAL 模式    │       │
│  │ _get_conn()  │            │  sql.Open()  │       │
│  └──────┬───────┘            └──────┬───────┘       │
│         │                           │               │
│         └───────────┬───────────────┘               │
│                     ▼                               │
│           dmshoot.db  (WAL mode)                    │
│           ├── dmshoot.db      (主文件)              │
│           ├── dmshoot.db-wal  (积压写入 ⚠️)        │
│           └── dmshoot.db-shm  (共享内存索引)        │
└─────────────────────────────────────────────────────┘
```

两个进程（Python + Go）同时打开同一个 WAL 数据库。任何一方崩溃，WAL 都不会自动合并。

## 解决方案：五层防御

```
Layer 1: PRAGMA 调优        ← 降低 WAL 阈值，更多自动合并
Layer 2: Python atexit      ← 正常退出时强制合并
Layer 3: Go 定期 checkpoint ← Go 存活时每60秒合并一次
Layer 4: Go 关闭 checkpoint ← Go 优雅关闭时强制合并
Layer 5: 紧急恢复脚本       ← 手动运行，无需停止程序
```

| 层级 | 防护场景 | 位置 | 依赖程序运行 |
|------|----------|------|-------------|
| L1 PRAGMA | WAL 文件过大 | SQLite 引擎 | 不需要 |
| L2 atexit | Python 正常关闭 | database.py | Python |
| L3 定期 | Python 崩溃 | Go batch.go | Go |
| L4 关闭 | Go 正常关闭 | Go batch.go | Go |
| L5 紧急 | 全部崩溃 | tools/wal_checkpoint.py | 无 |

---

## Layer 1: SQLite PRAGMA 调优

### 改动点：Python `database.py`

```python
# _get_conn() 函数中，添加 WAL 自动 checkpoint 阈值
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA wal_autocheckpoint=200")   # ← 新增：200页(800KB)即自动合并
_conn.execute("PRAGMA synchronous=NORMAL")        # ← 新增：平衡性能和安全
```

### 改动点：Go `internal/writer/batch.go`

```go
// initSQL 切片中添加
`PRAGMA wal_autocheckpoint=200`,
`PRAGMA synchronous=NORMAL`,
```

### 效果
- 默认 `wal_autocheckpoint=1000` (4096KB=4MB)
- 改为 `200` (819KB=800KB)
- WAL 文件最大从 4MB 降到 800KB，外部工具更易打开

---

## Layer 2: Python atexit 钩子

### 改动点：`database.py` 新增

```python
import atexit
import signal

def _checkpoint_on_exit():
    """退出时强制将 WAL 写回主文件"""
    if _conn is not None:
        try:
            _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint 完成")
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败: {e}")

def _checkpoint_signal_handler(signum, frame):
    """SIGTERM/SIGINT 信号处理"""
    _checkpoint_on_exit()

atexit.register(_checkpoint_on_exit)
signal.signal(signal.SIGTERM, _checkpoint_signal_handler)
signal.signal(signal.SIGINT, _checkpoint_signal_handler)
```

---

## Layer 3: Go 定期 checkpoint

### 改动点：`internal/writer/batch.go` — `Run()` 方法

在 `Run()` 的 goroutine 中添加定时 checkpoint：

```go
// 定期 WAL checkpoint（每 60 秒）
checkpointTicker := time.NewTicker(60 * time.Second)
defer checkpointTicker.Stop()

go func() {
    for range checkpointTicker.C {
        bw.DB.Exec("PRAGMA wal_checkpoint(PASSIVE)")
    }
}()
```

**为什么用 PASSIVE？** 不会阻塞读写操作，最安全。

---

## Layer 4: Go 关闭前 checkpoint

### 改动点：`internal/writer/batch.go` — `Shutdown()` → `Run()`

Go 的 `Shutdown()` 调用 `bw.cancel()`，触发 `Run()` 中的 `<-bw.ctx.Done()`，
然后 `bw.flush()` 后 `return bw.DB.Close()`。

在 `DB.Close()` 之前加一步：

```go
case <-bw.ctx.Done():
    bw.flush()
    // 关闭前强制 checkpoint
    if _, err := bw.DB.Exec("PRAGMA wal_checkpoint(TRUNCATE)"); err != nil {
        log.Printf("关闭前 WAL checkpoint 失败: %v", err)
    }
    return bw.DB.Close()
```

---

## Layer 5: 紧急恢复脚本

### 新文件：`tools/wal_checkpoint.py`

独立脚本，不依赖 DMShoot 任何模块：

```python
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
```

---

## 验证方法

部署后验证各层是否生效：

### 验证 L1 PRAGMA
```powershell
python -c "
import sqlite3
conn = sqlite3.connect(r'H:\DMShoot\dmshoot\data\dmshoot.db')
c = conn.cursor()
c.execute('PRAGMA wal_autocheckpoint')
print(f'wal_autocheckpoint: {c.fetchone()[0]}')  # 期望: 200
conn.close()
"
```

### 验证 L2 atexit
```powershell
# 启动 DMShoot 然后正常关闭，检查 WAL 大小
ls H:\DMShoot\dmshoot\data\dmshoot.db-wal
```

### 验证 L3 Go 定期 checkpoint
```powershell
# Go 服务运行超过 60 秒后，WAL 应保持较小
watch -n 5 "ls -la H:\DMShoot\dmshoot\data\dmshoot.db-wal"
```

### 验证 L5 紧急恢复
```powershell
python tools/wal_checkpoint.py
```

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| WAL 文件被手动删除 | 低 | 丢失未合并数据 | 降低 auto checkpoint 阈值 |
| 两个进程同时 checkpoint | 低 | 无影响 | WAL 模式支持并发读 |
| Go 定期 checkpoint 性能影响 | 低 | PASSIVE 模式零阻塞 | 60秒间隔，开销可忽略 |
| Python crash 超过 60s 无 Go | 低 | WAL 最多积压 800KB | L1 阈值已降低 |

---

## 所需工具/库

| 组件 | 语言 | 第三方依赖 | 说明 |
|------|------|-----------|------|
| database.py 修改 | Python | 无 | 标准库 `atexit`, `signal` |
| batch.go 修改 | Go | 无 | 标准库 `time`, `log` |
| wal_checkpoint.py | Python | 无 | 纯标准库独立脚本 |

**无需安装任何新依赖。**
