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
    """Create tables if missing."""
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
                settled_at TEXT NOT NULL,
                PRIMARY KEY (trade_date, sector)
            );
            """
        )


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
            "SELECT 1 FROM push_log WHERE push_key=? AND created_at>=? LIMIT 1",
            (push_key, cutoff),
        ).fetchone()
    return row is not None


def any_push_keys_recently(push_keys: list[str], cooldown_sec: int) -> bool:
    """Return True if any of the keys was pushed inside the cooldown window."""
    keys = [str(k) for k in push_keys if k]
    if not keys:
        return False
    cutoff = (datetime.now(CN_TZ) - timedelta(seconds=cooldown_sec)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    placeholders = ",".join("?" for _ in keys)
    with connect() as conn:
        row = conn.execute(
            f"SELECT 1 FROM push_log WHERE push_key IN ({placeholders}) "
            "AND created_at>=? LIMIT 1",
            (*keys, cutoff),
        ).fetchone()
    return row is not None


def log_push(push_key: str, title: str) -> None:
    """Record a successful Server酱 push for cooldown."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO push_log(push_key, title, created_at) VALUES (?,?,?)",
            (push_key, title, _now()),
        )


def list_push_log(limit: int = 30) -> list[dict[str, Any]]:
    """Return recent Server酱 push rows (newest first)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT push_key, title, created_at FROM push_log "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(100, int(limit))),),
        ).fetchall()
    return [dict(r) for r in rows]


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
) -> None:
    """Store next-session day-move for one resonance mark."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO resonance_outcome(trade_date, sector, next_date, next_board_pct, settled_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(trade_date, sector) DO UPDATE SET
                next_date=excluded.next_date,
                next_board_pct=excluded.next_board_pct,
                settled_at=excluded.settled_at
            """,
            (trade_date, sector, next_date, next_board_pct, _now()),
        )


def resonance_backtest_summary(days: int = 30) -> dict[str, Any]:
    """Aggregate settled resonance → next-day board moves."""
    cutoff = (datetime.now(CN_TZ) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT o.trade_date, o.sector, o.next_date, o.next_board_pct, m.confirm
            FROM resonance_outcome o
            LEFT JOIN resonance_mark m
              ON m.trade_date = o.trade_date AND m.sector = o.sector
            WHERE o.trade_date >= ?
            ORDER BY o.trade_date DESC
            """,
            (cutoff,),
        ).fetchall()
    items = [dict(r) for r in rows]
    usable = [r for r in items if r.get("next_board_pct") is not None]
    up = [r for r in usable if float(r["next_board_pct"]) > 0]
    flat = [r for r in usable if float(r["next_board_pct"]) == 0]
    down = [r for r in usable if float(r["next_board_pct"]) < 0]
    avg = (
        round(sum(float(r["next_board_pct"]) for r in usable) / len(usable), 3)
        if usable
        else None
    )
    return {
        "ok": True,
        "days": days,
        "n": len(usable),
        "up": len(up),
        "flat": len(flat),
        "down": len(down),
        "hit_rate": round(100.0 * len(up) / len(usable), 1) if usable else None,
        "avg_next_pct": avg,
        "rows": items[:40],
    }
