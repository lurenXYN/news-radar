"""Background refresh loop: collect → score → optional Server酱."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from news_radar import config as cfg
from news_radar.collect import collect_all
from news_radar.db import (
    init_db,
    insert_article,
    link_article_sectors,
    list_recent_articles,
    log_push,
    purge_old_articles,
    recent_articles_for_sector,
    sector_heat,
    was_pushed_recently,
)
from news_radar.notify import format_sector_push, notify_serverchan
from news_radar.score import etfs_for_sector, match_sectors
from news_radar.settings import setting

log = logging.getLogger("news_radar.engine")
try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    CN_TZ = timezone(timedelta(hours=8))


class RadarEngine:
    """Hold latest snapshot and refresh on a timer."""

    def __init__(self) -> None:
        self.snapshot: dict[str, Any] = {
            "ok": False,
            "updated_at": None,
            "sectors": [],
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
        first = True
        while True:
            try:
                await self.refresh()
            except Exception:
                log.exception("refresh failed")
                self.snapshot["ok"] = False
                self.snapshot["warnings"] = (self.snapshot.get("warnings") or [])[-8:]
            first = False
            await asyncio.sleep(int(setting("refresh_seconds", cfg.REFRESH_SECONDS)))

    async def refresh(self) -> dict[str, Any]:
        """Pull news, map sectors, update snapshot, maybe push."""
        async with self._lock:
            warnings: list[str] = []
            new_n = 0
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0), follow_redirects=True) as client:
                rows = await collect_all(client)
            for row in rows:
                hits = match_sectors(row.get("title") or "", row.get("summary") or "")
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
            heat = sector_heat(hours=hours)
            # Enrich with ETF + sample headlines.
            sectors: list[dict[str, Any]] = []
            for h in heat:
                sector = str(h["sector"])
                etfs = etfs_for_sector(sector)
                arts = recent_articles_for_sector(sector, hours=hours, limit=5)
                # A-share priority already baked into weights; keep label.
                sectors.append(
                    {
                        **h,
                        "etfs": etfs,
                        "articles": arts,
                        "score": float(h.get("raw_score") or 0),
                    }
                )
            sectors.sort(key=lambda x: float(x.get("score") or 0), reverse=True)

            pushed = 0
            try:
                pushed = self._maybe_push(sectors)
            except Exception as exc:
                log.exception("push failed")
                warnings.append(f"push: {exc}")

            now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
            self.snapshot = {
                "ok": True,
                "updated_at": now,
                "sectors": sectors[:30],
                "articles": list_recent_articles(60),
                "warnings": warnings,
                "stats": {
                    "fetched": len(rows),
                    "inserted": new_n,
                    "purged": purged,
                    "pushed": pushed,
                    "heat_window_hours": hours,
                },
            }
            return self.snapshot

    def _maybe_push(self, sectors: list[dict[str, Any]]) -> int:
        """Push top hot A-priority sectors via Server酱 with cooldown."""
        if not bool(setting("serverchan_enabled", False)):
            return 0
        key = str(setting("serverchan_sendkey", "") or "").strip()
        if not key:
            return 0
        min_score = float(setting("push_score_min", cfg.PUSH_SCORE_MIN))
        cooldown = int(setting("push_cooldown_seconds", cfg.PUSH_COOLDOWN_SECONDS))
        ok_n = 0
        for row in sectors[:5]:
            score = float(row.get("score") or 0)
            if score < min_score:
                continue
            sector = str(row.get("sector") or "")
            push_key = f"sector:{sector}"
            if was_pushed_recently(push_key, cooldown):
                continue
            title, desp = format_sector_push(
                sector,
                score,
                list(row.get("articles") or []),
                etfs=list(row.get("etfs") or []),
            )
            if notify_serverchan(key, title, desp):
                log_push(push_key, title)
                ok_n += 1
                log.info("serverchan ok | %s | %.1f", sector, score)
        return ok_n


engine = RadarEngine()
