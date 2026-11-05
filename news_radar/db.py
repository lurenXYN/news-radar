"""SQLite persistence for articles, sector hits, and settings."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from news_radar.config import DATA_DIR, DB_PATH

try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001 — Windows without tzdata
    CN_TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Yield a connection with row factory and foreign keys on."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if missing and apply light migrations."""
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                url TEXT DEFAULT '',
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                region TEXT DEFAULT 'A'
            );
            CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at);
            CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);

            CREATE TABLE IF NOT EXISTS article_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                sector TEXT NOT NULL,
                keyword TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_as_sector ON article_sectors(sector);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS push_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                push_key TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_push_key ON push_log(push_key, created_at);

            CREATE TABLE IF NOT EXISTS resonance_mark (
                trade_date TEXT NOT NULL,
                sector TEXT NOT NULL,
                confirm TEXT,
                board_bk TEXT,
                board_pct REAL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (trade_date, sector)
            );

            CREATE TABLE IF NOT EXISTS resonance_outcome (
                trade_date TEXT NOT NULL,
                sector TEXT NOT NULL,
                next_date TEXT NOT NULL,
                next_board_pct REAL,
                next_bench_pct REAL,
                next_excess_pct REAL,
                settled_at TEXT NOT NULL,
                PRIMARY KEY (trade_date, sector)
            );
            """
        )
        _migrate_push_log(conn)
        _migrate_resonance_outcome(conn)


def _migrate_resonance_outcome(conn: sqlite3.Connection) -> None:
    """Add excess-return columns to resonance_outcome when missing."""
    cols = {
        str(r[1]) for r in conn.execute("PRAGMA table_info(resonance_outcome)").fetchall()
    }
    for name, sql in (
        ("next_bench_pct", "ALTER TABLE resonance_outcome ADD COLUMN next_bench_pct REAL"),
        ("next_excess_pct", "ALTER TABLE resonance_outcome ADD COLUMN next_excess_pct REAL"),
    ):
        if name not in cols:
            conn.execute(sql)


def _migrate_push_log(conn: sqlite3.Connection) -> None:
    """Add history / feedback columns to push_log when missing."""
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(push_log)").fetchall()}
    alters = [
        ("ok", "ALTER TABLE push_log ADD COLUMN ok INTEGER NOT NULL DEFAULT 1"),
        ("kind", "ALTER TABLE push_log ADD COLUMN kind TEXT DEFAULT ''"),
        ("desp", "ALTER TABLE push_log ADD COLUMN desp TEXT DEFAULT ''"),
        ("error", "ALTER TABLE push_log ADD COLUMN error TEXT DEFAULT ''"),
        ("feedback", "ALTER TABLE push_log ADD COLUMN feedback TEXT DEFAULT ''"),
    ]
    for name, sql in alters:
        if name not in cols:
            conn.execute(sql)


def load_setting(key: str, default: Any = None) -> Any:
    """Load one JSON setting."""
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def save_setting(key: str, value: Any) -> None:
    """Persist one JSON setting."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def insert_article(row: dict[str, Any]) -> int | None:
    """Insert article if fingerprint is new. Return id or None if duplicate."""
    with connect() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO articles(
                    fingerprint, source, title, summary, url,
                    published_at, fetched_at, region
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    row["fingerprint"],
                    row.get("source") or "",
                    row["title"],
                    row.get("summary") or "",
                    row.get("url") or "",
                    row.get("published_at"),
                    row.get("fetched_at") or _now(),
                    row.get("region") or "A",
                ),
            )
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None


def existing_fingerprints(fingerprints: list[str]) -> set[str]:
    """Return the subset of fingerprints already stored."""
    wanted = [f for f in dict.fromkeys(fingerprints) if f]
    found: set[str] = set()
    with connect() as conn:
        for i in range(0, len(wanted), 400):
            chunk = wanted[i : i + 400]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT fingerprint FROM articles WHERE fingerprint IN ({marks})", chunk
            ).fetchall()
            found.update(str(r["fingerprint"]) for r in rows)
    return found


def recent_titles(hours: int = 24, limit: int = 3000) -> list[str]:
    """Return headlines stored within the last ``hours`` (newest first)."""
    cutoff = (datetime.now(CN_TZ) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        rows = conn.execute(
            "SELECT title FROM articles WHERE fetched_at >= ? ORDER BY id DESC LIMIT ?",
            (cutoff, int(limit)),
        ).fetchall()
    return [str(r["title"] or "") for r in rows]


def link_article_sectors(article_id: int, hits: list[dict[str, Any]]) -> None:
    """Attach sector keyword hits to one article."""
    if not hits:
        return
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO article_sectors(article_id, sector, keyword, weight)
            VALUES (?,?,?,?)
            """,
            [
                (
                    article_id,
                    h["sector"],
                    h["keyword"],
                    float(h.get("weight") or 1.0),
                )
                for h in hits
            ],
        )


def purge_old_articles(days: int) -> int:
    """Delete articles older than retention window. Return deleted count."""
    cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM articles WHERE fetched_at < ? OR "
            "(published_at IS NOT NULL AND published_at < ?)",
            (cutoff, cutoff),
        )
        return int(cur.rowcount or 0)


def list_recent_articles(limit: int = 80) -> list[dict[str, Any]]:
    """Return newest articles with joined sector labels."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, GROUP_CONCAT(DISTINCT s.sector) AS sectors
            FROM articles a
            LEFT JOIN article_sectors s ON s.article_id = a.id
            GROUP BY a.id
            ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def sector_heat(hours: int = 24) -> list[dict[str, Any]]:
    """Aggregate sector scores inside the heat window ending now."""
    end = datetime.now(CN_TZ)
    start = end - timedelta(hours=hours)
    return sector_heat_between(start, end)


def sector_heat_between(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Aggregate sector scores for articles in [start, end)."""
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                s.sector AS sector,
                COUNT(DISTINCT s.article_id) AS article_count,
                SUM(s.weight) AS raw_score,
                GROUP_CONCAT(DISTINCT s.keyword) AS keywords
            FROM article_sectors s
            JOIN articles a ON a.id = s.article_id
            WHERE COALESCE(a.published_at, a.fetched_at) >= ?
              AND COALESCE(a.published_at, a.fetched_at) < ?
            GROUP BY s.sector
            ORDER BY raw_score DESC
            """,
            (start_s, end_s),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["raw_score"] = round(float(d.get("raw_score") or 0), 2)
        d["article_count"] = int(d.get("article_count") or 0)
        out.append(d)
    return out


def heat_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Map sector → raw_score."""
    return {str(r["sector"]): float(r.get("raw_score") or 0) for r in rows}


def recent_articles_for_sector(sector: str, hours: int = 24, limit: int = 8) -> list[dict[str, Any]]:
    """Return recent articles that hit one sector."""
    cutoff = (datetime.now(CN_TZ) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT a.title, a.url, a.source, a.published_at, a.fetched_at
            FROM articles a
            JOIN article_sectors s ON s.article_id = a.id
            WHERE s.sector = ?
              AND COALESCE(a.published_at, a.fetched_at) >= ?
            ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
            LIMIT ?
            """,
            (sector, cutoff, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def was_pushed_recently(push_key: str, cooldown_sec: int) -> bool:
    """Return True if the same push_key was sent inside the cooldown window."""
    cutoff = (datetime.now(CN_TZ) - timedelta(seconds=cooldown_sec)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM push_log WHERE push_key=? AND created_at>=? AND ok=1 LIMIT 1",
            (push_key, cutoff),
        ).fetchone()
    return row is not None


def log_push(
    push_key: str,
    title: str,
    *,
    kind: str = "",
    ok: bool = True,
    desp: str = "",
    error: str = "",
) -> int:
    """Record a Server酱 attempt (success or failure). Return row id."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO push_log(push_key, title, created_at, ok, kind, desp, error, feedback) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                push_key,
                title,
                _now(),
                1 if ok else 0,
                kind or _kind_from_key(push_key),
                (desp or "")[:20000],
                (error or "")[:500],
                "",
            ),
        )
        return int(cur.lastrowid or 0)


def _kind_from_key(push_key: str) -> str:
    k = str(push_key or "")
    if k.startswith("digest:morning"):
        return "morning"
    if k.startswith("digest:midday"):
        return "midday"
    if k.startswith("digest:evening"):
        return "evening"
    if k.startswith("brief:"):
        return "brief"
    if k.startswith("alert:"):
        return "alert"
    return "other"


def list_push_log(limit: int = 30) -> list[dict[str, Any]]:
    """Return recent Server酱 push rows (newest first)."""
    return query_push_log(limit=limit)["rows"]


def query_push_log(
    *,
    kind: str = "",
    day_from: str = "",
    day_to: str = "",
    ok: str = "",
    q: str = "",
    offset: int = 0,
    limit: int = 30,
) -> dict[str, Any]:
    """Query push history with filters. ``ok``: '', '1', '0'."""
    where: list[str] = []
    args: list[Any] = []
    if kind:
        where.append("kind=?")
        args.append(kind)
    if day_from:
        where.append("created_at>=?")
        args.append(day_from[:10] + " 00:00:00")
    if day_to:
        where.append("created_at<=?")
        args.append(day_to[:10] + " 23:59:59")
    if ok in ("0", "1"):
        where.append("ok=?")
        args.append(int(ok))
    if q:
        where.append("(title LIKE ? OR push_key LIKE ? OR IFNULL(error,'') LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    with connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(1) AS n FROM push_log{clause}", args
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT id, push_key, title, created_at, ok, kind, "
            f"substr(desp,1,200) AS desp_preview, error, feedback "
            f"FROM push_log{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
    return {
        "ok": True,
        "total": int(total or 0),
        "offset": offset,
        "limit": limit,
        "rows": [dict(r) for r in rows],
    }


def get_push_log(push_id: int) -> dict[str, Any] | None:
    """Return one push row including full desp body."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, push_key, title, created_at, ok, kind, desp, error, feedback "
            "FROM push_log WHERE id=?",
            (int(push_id),),
        ).fetchone()
    return dict(row) if row else None


def set_push_feedback(push_id: int, feedback: str) -> bool:
    """Mark a push as useful / useless / clear."""
    fb = str(feedback or "").strip().lower()
    if fb not in ("", "useful", "useless"):
        return False
    with connect() as conn:
        cur = conn.execute(
            "UPDATE push_log SET feedback=? WHERE id=?",
            (fb, int(push_id)),
        )
        return cur.rowcount > 0


def count_pushes_today(*, ok_only: bool = True) -> int:
    """Count pushes created on the local calendar day."""
    day = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    sql = "SELECT COUNT(1) AS n FROM push_log WHERE created_at>=? AND created_at<=?"
    args: list[Any] = [day + " 00:00:00", day + " 23:59:59"]
    if ok_only:
        sql += " AND ok=1"
    with connect() as conn:
        return int(conn.execute(sql, args).fetchone()["n"] or 0)


def upsert_resonance_marks(trade_date: str, rows: list[dict[str, Any]]) -> int:
    """Persist today's resonance / board-lead marks for next-day settle."""
    if not rows:
        return 0
    n = 0
    stamp = _now()
    with connect() as conn:
        for r in rows:
            sector = str(r.get("sector") or "").strip()
            if not sector:
                continue
            conn.execute(
                """
                INSERT INTO resonance_mark(trade_date, sector, confirm, board_bk, board_pct, created_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(trade_date, sector) DO UPDATE SET
                    confirm=excluded.confirm,
                    board_bk=excluded.board_bk,
                    board_pct=excluded.board_pct,
                    created_at=excluded.created_at
                """,
                (
                    trade_date,
                    sector,
                    str(r.get("confirm") or ""),
                    str(r.get("board_bk") or ""),
                    r.get("board_pct"),
                    stamp,
                ),
            )
            n += 1
    return n


def list_unsettle_resonance_marks(before_date: str) -> list[dict[str, Any]]:
    """Return marks strictly before ``before_date`` that lack an outcome row."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.trade_date, m.sector, m.confirm, m.board_bk, m.board_pct
            FROM resonance_mark m
            LEFT JOIN resonance_outcome o
              ON o.trade_date = m.trade_date AND o.sector = m.sector
            WHERE m.trade_date < ? AND o.sector IS NULL
            ORDER BY m.trade_date DESC
            LIMIT 80
            """,
            (before_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_resonance_outcome(
    trade_date: str,
    sector: str,
    *,
    next_date: str,
    next_board_pct: float | None,
    next_bench_pct: float | None = None,
    next_excess_pct: float | None = None,
) -> None:
    """Store next-session day-move and excess vs board median for one mark."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO resonance_outcome(
                trade_date, sector, next_date, next_board_pct,
                next_bench_pct, next_excess_pct, settled_at
            )
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(trade_date, sector) DO UPDATE SET
                next_date=excluded.next_date,
                next_board_pct=excluded.next_board_pct,
                next_bench_pct=excluded.next_bench_pct,
                next_excess_pct=excluded.next_excess_pct,
                settled_at=excluded.settled_at
            """,
            (
                trade_date,
                sector,
                next_date,
                next_board_pct,
                next_bench_pct,
                next_excess_pct,
                _now(),
            ),
        )


def feedback_summary(*, since: str | None = None, days: int = 30) -> dict[str, Any]:
    """Count useful / useless / unmarked pushes for the observation window."""
    day_from = str(since or "").strip()[:10]
    if not day_from:
        day_from = (datetime.now(CN_TZ) - timedelta(days=max(1, days))).strftime(
            "%Y-%m-%d"
        )
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              COUNT(1) AS total,
              SUM(CASE WHEN feedback='useful' THEN 1 ELSE 0 END) AS useful,
              SUM(CASE WHEN feedback='useless' THEN 1 ELSE 0 END) AS useless,
              SUM(CASE WHEN IFNULL(feedback,'')='' THEN 1 ELSE 0 END) AS unmarked
            FROM push_log
            WHERE ok=1 AND created_at >= ?
            """,
            (day_from + " 00:00:00",),
        ).fetchone()
    total = int(rows["total"] or 0)
    useful = int(rows["useful"] or 0)
    useless = int(rows["useless"] or 0)
    unmarked = int(rows["unmarked"] or 0)
    labeled = useful + useless
    return {
        "ok": True,
        "since": day_from,
        "total": total,
        "useful": useful,
        "useless": useless,
        "unmarked": unmarked,
        "labeled": labeled,
        "useful_rate": round(100.0 * useful / labeled, 1) if labeled else None,
    }


def effect_observe_snapshot(days: int = 30) -> dict[str, Any]:
    """Bundle hand-marks + resonance next-day stats for the observe window."""
    from news_radar import config as cfg

    since = str(getattr(cfg, "EFFECT_OBSERVE_SINCE", "") or "").strip()[:10]
    horizon = int(getattr(cfg, "EFFECT_OBSERVE_DAYS", 7) or 7)
    fb = feedback_summary(since=since or None, days=days)
    bt = resonance_backtest_summary(days=days)
    # Pass/fail hints stay soft — humans decide; code only surfaces numbers.
    labeled = int(fb.get("labeled") or 0)
    useful_rate = fb.get("useful_rate")
    hit = bt.get("hit_rate")
    excess_hit = bt.get("excess_hit_rate")
    hints: list[str] = []
    if labeled < 3:
        hints.append("手标样本少：每条总报点「有用/没用」")
    elif useful_rate is not None and useful_rate < 40:
        hints.append("手标偏「没用」→ 考虑减推送或收紧阈值")
    elif useful_rate is not None and useful_rate >= 60:
        hints.append("手标偏「有用」→ 可继续常开观察")
    if int(bt.get("n") or 0) < 5:
        hints.append("共振次日样本不足，再等几日结算")
    elif excess_hit is not None and excess_hit < 45:
        hints.append("共振次日超额偏低 → 多为跟大盘，催化增量弱")
    elif excess_hit is not None and excess_hit >= 55:
        hints.append("共振次日超额尚可 → 优先看共振/盘面已动")
    elif hit is not None and hit < 45:
        hints.append("共振次日上涨率偏低 → 「共振」标签参考价值弱")
    elif hit is not None and hit >= 55:
        hints.append("共振次日上涨率尚可 → 优先看共振/盘面已动")
    return {
        "ok": True,
        "since": since or fb.get("since"),
        "horizon_days": horizon,
        "feedback": fb,
        "backtest": {
            "n": bt.get("n"),
            "hit_rate": bt.get("hit_rate"),
            "avg_next_pct": bt.get("avg_next_pct"),
            "excess_hit_rate": bt.get("excess_hit_rate"),
            "avg_excess_pct": bt.get("avg_excess_pct"),
            "by_confirm": bt.get("by_confirm"),
        },
        "hints": hints,
        "note": (
            "效果只作观察：不改买卖闸门。"
            "手标=你主观是否帮到跟单；共振次日超额=相对全板块中位数。"
        ),
    }


def resonance_backtest_summary(days: int = 30) -> dict[str, Any]:
    """Aggregate settled resonance → next-day absolute and excess board moves."""
    cutoff = (datetime.now(CN_TZ) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT o.trade_date, o.sector, o.next_date, o.next_board_pct,
                   o.next_bench_pct, o.next_excess_pct, m.confirm
            FROM resonance_outcome o
            LEFT JOIN resonance_mark m
              ON m.trade_date = o.trade_date AND m.sector = o.sector
            WHERE o.trade_date >= ?
            ORDER BY o.trade_date DESC
            """,
            (cutoff,),
        ).fetchall()
    items = [dict(r) for r in rows]

    def _stats(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        usable = [r for r in bucket if r.get("next_board_pct") is not None]
        up = [r for r in usable if float(r["next_board_pct"]) > 0]
        flat = [r for r in usable if float(r["next_board_pct"]) == 0]
        down = [r for r in usable if float(r["next_board_pct"]) < 0]
        avg = (
            round(sum(float(r["next_board_pct"]) for r in usable) / len(usable), 3)
            if usable
            else None
        )
        excess_rows = [r for r in usable if r.get("next_excess_pct") is not None]
        excess_up = [r for r in excess_rows if float(r["next_excess_pct"]) > 0]
        avg_excess = (
            round(
                sum(float(r["next_excess_pct"]) for r in excess_rows) / len(excess_rows),
                3,
            )
            if excess_rows
            else None
        )
        return {
            "n": len(usable),
            "up": len(up),
            "flat": len(flat),
            "down": len(down),
            "hit_rate": round(100.0 * len(up) / len(usable), 1) if usable else None,
            "avg_next_pct": avg,
            "excess_n": len(excess_rows),
            "excess_hit_rate": (
                round(100.0 * len(excess_up) / len(excess_rows), 1) if excess_rows else None
            ),
            "avg_excess_pct": avg_excess,
        }

    by_confirm: dict[str, dict[str, Any]] = {}
    for r in items:
        key = str(r.get("confirm") or "unknown")
        by_confirm.setdefault(key, []).append(r)
    return {
        "ok": True,
        "days": days,
        **_stats(items),
        "by_confirm": {k: _stats(v) for k, v in by_confirm.items()},
        "rows": items[:40],
    }
