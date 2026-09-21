"""Background refresh loop: collect → score → board confirm → optional Server酱."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from news_radar import config as cfg
from news_radar.boards import confirm_label, fetch_board_quotes, match_board_for_sector
from news_radar.collect import collect_all
from news_radar.dedupe import dedupe_articles
from news_radar.db import (
    heat_map,
    init_db,
    insert_article,
    link_article_sectors,
    list_recent_articles,
    log_push,
    purge_old_articles,
    recent_articles_for_sector,
    sector_heat,
    sector_heat_between,
    was_pushed_recently,
)
from news_radar.notify import format_morning_digest, format_watch_digest, notify_serverchan
from news_radar.score import action_hint, etfs_for_sector, match_sectors
from news_radar.sentiment import classify_tone
from news_radar.settings import setting

log = logging.getLogger("news_radar.engine")
try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    CN_TZ = timezone(timedelta(hours=8))


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = str(s or "08:00").split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _in_morning_window(now: datetime) -> bool:
    start_h, start_m = _parse_hhmm(cfg.MORNING_PUSH_START)
    end_h, end_m = _parse_hhmm(cfg.MORNING_PUSH_END)
    minutes = now.hour * 60 + now.minute
    return (start_h * 60 + start_m) <= minutes <= (end_h * 60 + end_m)


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float]:
    """Sort: resonance first, then rising delta, then absolute score."""
    confirm = str(row.get("confirm") or "")
    boost = {
        "resonance": 30.0,
        "board_lead": 20.0,
        "news_only": 5.0,
        "diverge": 2.0,
        "neutral": 1.0,
        "unknown": 0.0,
    }.get(confirm, 0.0)
    return (boost + float(row.get("delta") or 0), float(row.get("score") or 0), float(row.get("board_pct") or 0))


class RadarEngine:
    """Hold latest snapshot and refresh on a timer."""

    def __init__(self) -> None:
        self.snapshot: dict[str, Any] = {
            "ok": False,
            "updated_at": None,
            "sectors": [],
            "watch": [],
            "articles": [],
            "warnings": [],
            "stats": {},
        }
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Create tables and start the polling task."""
        init_db()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="news-radar-loop")

    async def stop(self) -> None:
        """Cancel the polling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:
                log.exception("refresh failed")
                self.snapshot["ok"] = False
                self.snapshot["warnings"] = (self.snapshot.get("warnings") or [])[-8:]
            await asyncio.sleep(int(setting("refresh_seconds", cfg.REFRESH_SECONDS)))

    async def refresh(self) -> dict[str, Any]:
        """Pull news, map sectors, confirm vs boards, maybe morning-push."""
        async with self._lock:
            warnings: list[str] = []
            new_n = 0
            boards: list[dict[str, Any]] = []
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0), follow_redirects=True) as client:
                rows = await collect_all(client)
                try:
                    boards = await fetch_board_quotes(client)
                except Exception as exc:
                    warnings.append(f"boards: {exc}")
            rows, deduped = dedupe_articles(rows)
            for row in rows:
                hits = match_sectors(row.get("title") or "", row.get("summary") or "")
                tone = classify_tone(row.get("title") or "", row.get("summary") or "")
                row["tone"] = tone.get("tone")
                row["tone_label"] = tone.get("label")
                aid = insert_article(row)
                if aid is None:
                    continue
                new_n += 1
                if hits:
                    link_article_sectors(aid, hits)
            try:
                purged = purge_old_articles(int(cfg.ARTICLE_RETENTION_DAYS))
            except Exception as exc:
                purged = 0
                warnings.append(f"purge: {exc}")

            hours = int(setting("heat_window_hours", cfg.HEAT_WINDOW_HOURS))
            now = datetime.now(CN_TZ)
            cur_rows = sector_heat(hours=hours)
            prev_rows = sector_heat_between(now - timedelta(hours=hours * 2), now - timedelta(hours=hours))
            hour_rows = sector_heat_between(now - timedelta(hours=1), now)
            hour_prev = sector_heat_between(now - timedelta(hours=2), now - timedelta(hours=1))
            prev_map = heat_map(prev_rows)
            hour_map = heat_map(hour_rows)
            hour_prev_map = heat_map(hour_prev)

            sectors: list[dict[str, Any]] = []
            for h in cur_rows:
                sector = str(h["sector"])
                score = float(h.get("raw_score") or 0)
                prev = float(prev_map.get(sector) or 0)
                delta = round(score - prev, 2)
                delta_1h = round(
                    float(hour_map.get(sector) or 0) - float(hour_prev_map.get(sector) or 0),
                    2,
                )
                etfs = etfs_for_sector(sector)
                arts = recent_articles_for_sector(sector, hours=hours, limit=5)
                board = match_board_for_sector(sector, boards)
                board_pct = float(board["pct"]) if board else None
                conf = confirm_label(news_score=score, delta=delta, board_pct=board_pct)
                # Tone from newest article titles in this sector window.
                tones = [classify_tone(str(a.get("title") or "")) for a in arts[:5]]
                bear_n = sum(1 for t in tones if t.get("tone") == "bearish")
                bull_n = sum(1 for t in tones if t.get("tone") == "bullish")
                if bear_n > bull_n and bear_n > 0:
                    tone, tone_label = "bearish", "偏空"
                elif bull_n > bear_n and bull_n > 0:
                    tone, tone_label = "bullish", "偏多"
                else:
                    tone, tone_label = "neutral", "中性"
                row_out = {
                    **h,
                    "etfs": etfs,
                    "articles": arts,
                    "score": score,
                    "prev_score": prev,
                    "delta": delta,
                    "delta_1h": delta_1h,
                    "rising": delta >= float(cfg.REL_HEAT_MIN_DELTA),
                    "board_name": (board or {}).get("name"),
                    "board_bk": (board or {}).get("bk"),
                    "board_pct": board_pct,
                    "confirm": conf["confirm"],
                    "confirm_label": conf["label"],
                    "confirm_note": conf["note"],
                    "label": conf["label"],
                    "tone": tone,
                    "tone_label": tone_label,
                }
                row_out["action_hint"] = action_hint(row_out)
                sectors.append(row_out)
            sectors.sort(key=_rank_key, reverse=True)

            # Watch list: rising and/or board-confirmed — what users should stare at.
            watch = [
                s
                for s in sectors
                if s.get("rising")
                or s.get("confirm") in ("resonance", "board_lead")
                or (float(s.get("score") or 0) >= 6 and s.get("confirm") == "news_only")
            ][:12]

            pushed = 0
            try:
                pushed = self._maybe_push(sectors, now=now)
            except Exception as exc:
                log.exception("push failed")
                warnings.append(f"push: {exc}")

            stamp = now.strftime("%Y-%m-%d %H:%M:%S")
            self.snapshot = {
                "ok": True,
                "updated_at": stamp,
                "sectors": sectors[:30],
                "watch": watch,
                "articles": list_recent_articles(60),
                "warnings": warnings,
                "stats": {
                    "fetched": len(rows) + deduped,
                    "inserted": new_n,
                    "deduped": deduped,
                    "purged": purged,
                    "pushed": pushed,
                    "boards": len(boards),
                    "heat_window_hours": hours,
                },
            }
            return self.snapshot

    def export_sectors(self, *, limit: int = 8) -> dict[str, Any]:
        """Compact payload for 牛来 / external consumers."""
        snap = self.snapshot or {}
        rows = list(snap.get("watch") or snap.get("sectors") or [])[: max(1, limit)]
        out = []
        for r in rows:
            out.append(
                {
                    "sector": r.get("sector"),
                    "score": r.get("score"),
                    "delta": r.get("delta"),
                    "delta_1h": r.get("delta_1h"),
                    "rising": r.get("rising"),
                    "confirm": r.get("confirm"),
                    "confirm_label": r.get("confirm_label"),
                    "confirm_note": r.get("confirm_note"),
                    "tone": r.get("tone"),
                    "tone_label": r.get("tone_label"),
                    "action_hint": r.get("action_hint"),
                    "board_name": r.get("board_name"),
                    "board_bk": r.get("board_bk"),
                    "board_pct": r.get("board_pct"),
                    "etfs": r.get("etfs") or [],
                    "keywords": r.get("keywords"),
                    "articles": [
                        {
                            "title": a.get("title"),
                            "url": a.get("url"),
                            "source": a.get("source"),
                        }
                        for a in (r.get("articles") or [])[:3]
                    ],
                }
            )
        return {
            "ok": bool(snap.get("ok")),
            "updated_at": snap.get("updated_at"),
            "sectors": out,
            "stats": snap.get("stats") or {},
        }

    def _maybe_push(self, sectors: list[dict[str, Any]], *, now: datetime) -> int:
        """Push morning digest (default) or legacy per-sector alerts."""
        if not bool(setting("serverchan_enabled", False)):
            return 0
        key = str(setting("serverchan_sendkey", "") or "").strip()
        if not key:
            return 0
        if bool(setting("morning_push_only", True)):
            return self._push_morning(sectors, key=key, now=now)
        return self._push_intraday(sectors, key=key)

    def _push_morning(self, sectors: list[dict[str, Any]], *, key: str, now: datetime) -> int:
        if not _in_morning_window(now):
            return 0
        day = now.strftime("%Y-%m-%d")
        push_key = f"morning:{day}"
        if was_pushed_recently(push_key, 20 * 3600):
            return 0
        min_score = float(setting("morning_push_min_score", cfg.MORNING_PUSH_MIN_SCORE))
        top_n = int(setting("morning_push_top_n", cfg.MORNING_PUSH_TOP_N))
        picked = [
            s
            for s in sectors
            if float(s.get("score") or 0) >= min_score
            or s.get("confirm") in ("resonance", "board_lead")
            or s.get("rising")
        ][:top_n]
        if not picked:
            return 0
        title, desp = format_morning_digest(
            picked, as_of=now.strftime("%Y-%m-%d %H:%M")
        )
        if notify_serverchan(key, title, desp):
            log_push(push_key, title)
            log.info("serverchan morning digest n=%s", len(picked))
            return 1
        return 0

    def _push_intraday(self, sectors: list[dict[str, Any]], *, key: str) -> int:
        """Push one merged digest (never one message per sector)."""
        min_score = float(setting("push_score_min", cfg.PUSH_SCORE_MIN))
        cooldown = int(setting("push_cooldown_seconds", cfg.PUSH_COOLDOWN_SECONDS))
        top_n = int(setting("morning_push_top_n", cfg.MORNING_PUSH_TOP_N))
        picked: list[dict[str, Any]] = []
        for row in sectors[:12]:
            if row.get("confirm") not in ("resonance", "board_lead") and not row.get("rising"):
                continue
            score = float(row.get("score") or 0)
            if score < min_score:
                continue
            picked.append(row)
            if len(picked) >= max(1, top_n):
                break
        if not picked:
            return 0
        names = ",".join(sorted(str(r.get("sector") or "") for r in picked))
        push_key = f"intraday:{names}"
        if was_pushed_recently(push_key, cooldown):
            return 0
        as_of = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
        title, desp = format_watch_digest(
            picked,
            as_of=as_of,
            title_prefix="新闻雷达 · 板块观察",
            heading="板块观察汇总",
            tip="本轮合并推送（不再按板块拆条）。优先看 **共振 / 盘面已动**。",
        )
        if notify_serverchan(key, title, desp):
            log_push(push_key, title)
            log.info("serverchan intraday digest n=%s", len(picked))
            return 1
        return 0


engine = RadarEngine()
