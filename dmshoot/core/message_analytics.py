"""消息分析 — SQLite 聚合统计每日消息量 / 回复率 / 响应时间 / 平台分布 / 时段分布"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from dmshoot.storage.database import DB_PATH, get_conn


def _conn() -> sqlite3.Connection:
    return get_conn()


# ── 每日摘要（最近7天）──

def daily_summary(days: int = 7) -> list[dict]:
    """返回 [{date, incoming, outgoing, reply_rate, avg_response_ms, platform, top_hour}]"""
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    cur = _conn().execute("""
        SELECT 
            DATE(timestamp, 'unixepoch', 'localtime') AS d,
            platform,
            SUM(CASE WHEN is_auto=0 THEN 1 ELSE 0 END) AS incoming,
            SUM(CASE WHEN is_auto=1 THEN 1 ELSE 0 END) AS outgoing
        FROM messages 
        WHERE timestamp >= ?
        GROUP BY d, platform
        ORDER BY d DESC, platform
    """, (cutoff,))
    rows = [dict(r) for r in cur.fetchall()]
    # 合并平台
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r["d"]
        if d not in by_date:
            by_date[d] = {"date": d, "incoming": 0, "outgoing": 0, "reply_rate": 0, "avg_response_ms": 0}
        by_date[d]["incoming"] += r["incoming"] or 0
        by_date[d]["outgoing"] += r["outgoing"] or 0

    result = []
    for d, v in sorted(by_date.items(), reverse=True):
        if v["incoming"] > 0:
            v["reply_rate"] = round(v["outgoing"] / v["incoming"] * 100, 1)
        else:
            v["reply_rate"] = 0
        # 平均响应时间：匹配 is_auto=0 和下一个 is_auto=1 的时间差
        v["avg_response_ms"] = _avg_response(d)
        result.append(v)
    return result


def _avg_response(date_str: str) -> float:
    """计算某天的平均 AI 回复时间（ms）"""
    start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
    end = start + 86400
    cur = _conn().execute("""
        SELECT session_id, timestamp, is_auto
        FROM messages 
        WHERE timestamp >= ? AND timestamp < ?
        ORDER BY session_id, timestamp ASC
    """, (start, end))
    rows = cur.fetchall()
    if not rows:
        return 0
    total_ms = 0
    count = 0
    pending: dict[str, float] = {}
    for r in rows:
        sid, ts, is_auto = r[0], r[1], r[2]
        if not is_auto:
            pending[sid] = ts
        elif sid in pending:
            total_ms += (ts - pending.pop(sid)) * 1000
            count += 1
    return round(total_ms / count) if count > 0 else 0


# ── 平台分布 ──

def platform_distribution(days: int = 7) -> dict[str, int]:
    """返回 {平台: 消息总数}"""
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    cur = _conn().execute("""
        SELECT platform, COUNT(*) AS cnt
        FROM messages
        WHERE timestamp >= ? AND is_auto=0
        GROUP BY platform
        ORDER BY cnt DESC
    """, (cutoff,))
    return {r[0]: r[1] for r in cur.fetchall()}


# ── 时段分布（小时级）──

def hourly_distribution(days: int = 7) -> list[dict]:
    """返回 [{hour: 0-23, count, platform}]"""
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    cur = _conn().execute("""
        SELECT 
            CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) AS h,
            platform,
            COUNT(*) AS cnt
        FROM messages
        WHERE timestamp >= ? AND is_auto=0
        GROUP BY h, platform
        ORDER BY h, platform
    """, (cutoff,))
    return [dict(r) for r in cur.fetchall()]


# ── 响应时间分平台 ──

def response_stats(days: int = 7) -> dict[str, dict]:
    """返回 {platform: {avg_ms, min_ms, max_ms, count}}"""
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    cur = _conn().execute("""
        SELECT platform, session_id, is_auto, timestamp
        FROM messages
        WHERE timestamp >= ?
        ORDER BY session_id, timestamp ASC
    """, (cutoff,))
    rows = cur.fetchall()
    # 计算每个平台的响应时间
    pending: dict[str, dict[str, float]] = {}  # platform → {session_id: ts}
    stats: dict[str, list[float]] = {}          # platform → [response_ms]
    for r in rows:
        platform = r[0]
        sid = r[1]
        is_auto = r[2]
        ts = r[3]
        if platform not in pending:
            pending[platform] = {}
        if not is_auto:
            pending[platform][sid] = ts
        elif sid in pending[platform]:
            resp_ms = (ts - pending[platform].pop(sid)) * 1000
            if resp_ms > 0:
                stats.setdefault(platform, []).append(resp_ms)
    result = {}
    for platform, vals in stats.items():
        if vals:
            result[platform] = {
                "avg_ms": round(sum(vals) / len(vals)),
                "min_ms": round(min(vals)),
                "max_ms": round(max(vals)),
                "count": len(vals),
            }
    return result
