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
from news_radar.dedupe import dedupe_articles, drop_seen_titles
from news_radar.calendar import is_trading_day
from news_radar.db import (
    attach_article_cluster,
    count_pushes_today,
    effect_observe_snapshot,
    existing_fingerprints,
    heat_map,
    init_db,
    insert_article,
    link_article_sectors,
    list_push_log,
    list_recent_articles,
    backfill_resonance_excess,
    list_unsettle_resonance_marks,
    load_setting,
    log_push,
    purge_old_articles,
    query_push_log,
    recent_articles_for_sector,
    recent_titles,
    resonance_backtest_summary,
    save_resonance_outcome,
    save_setting,
    sector_heat,
    sector_heat_between,
    upsert_resonance_marks,
    was_pushed_recently,
)
from news_radar.lexicon import overnight_hints_from_text
from news_radar.notify import (
    digest_compare_line,
    digest_overview_line,
    format_macro_section,
    format_overnight_sections,
    format_watch_digest,
    notify_serverchan,
)
from news_radar.schedule import push_schedule_status
from news_radar.score import (
    action_hint,
    etfs_for_sector,
    is_context_sector,
    match_sectors,
    primary_sector_names,
)
from news_radar.sentiment import classify_tone
from news_radar.settings import setting
from news_radar.themes import merge_by_theme, theme_of

log = logging.getLogger("news_radar.engine")
try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    CN_TZ = timezone(timedelta(hours=8))

_DIGEST_PREV_KIND = {"midday": ("morning", "盘前"), "evening": ("midday", "午间")}
_ALSO_WATCH_N = 4

# Confirm rank for digest / export: resonance > board_lead > diverge > news_only.
_CONFIRM_RANK: dict[str, float] = {
    "resonance": 40.0,
    "board_lead": 30.0,
    "diverge": 20.0,
    "news_only": 10.0,
    "neutral": 5.0,
    "unknown": 0.0,
}


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = str(s or "09:00").split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _in_hhmm_window(now: datetime, start: str, end: str) -> bool:
    """True when local clock falls inside [start, end] inclusive."""
    start_h, start_m = _parse_hhmm(start)
    end_h, end_m = _parse_hhmm(end)
    minutes = now.hour * 60 + now.minute
    return (start_h * 60 + start_m) <= minutes <= (end_h * 60 + end_m)


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    """Sort key: confirm tier, then rising delta, score, board pct."""
    confirm = str(row.get("confirm") or "")
    boost = float(_CONFIRM_RANK.get(confirm, 0.0))
    return (
        boost,
        float(row.get("delta") or 0),
        float(row.get("score") or 0),
        float(row.get("board_pct") or 0),
    )


def _demote_news_only() -> bool:
    """Return True when digest/export should keep news_only out of Top slots."""
    return bool(setting("digest_demote_news_only", cfg.DIGEST_DEMOTE_NEWS_ONLY))


def _require_board_confirm() -> bool:
    """Return True when digests must include resonance / board_lead."""
    return bool(
        setting("digest_require_board_confirm", cfg.DIGEST_REQUIRE_BOARD_CONFIRM)
    )


def _board_median_pct(boards: list[dict[str, Any]]) -> float | None:
    """Median day-move across quoted boards (bench for excess)."""
    vals: list[float] = []
    for b in boards:
        try:
            if b.get("pct") is not None:
                vals.append(float(b["pct"]))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    if len(vals) % 2:
        return round(vals[mid], 4)
    return round((vals[mid - 1] + vals[mid]) / 2.0, 4)


def _pick_digest_rows(
    sectors: list[dict[str, Any]],
    *,
    min_score: float,
    detail_n: int,
    also_n: int = _ALSO_WATCH_N,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select digest detail rows + 其余留意 (blacklist + theme merge).

    When demote is on, ``news_only`` fills ``also`` only — never the Top detail
    slots — so pure-news heat cannot crowd out resonance / board_lead.
    """
    blocked = {
        x.strip()
        for x in str(setting("sector_blacklist", "") or "").replace("，", ",").split(",")
        if x.strip()
    }
    candidates = [
        s
        for s in sectors
        if str(s.get("sector") or "") not in blocked
        and (
            float(s.get("score") or 0) >= min_score
            or s.get("confirm") in ("resonance", "board_lead", "diverge")
            or s.get("rising")
        )
    ]
    candidates.sort(key=_rank_key, reverse=True)
    detail_n = max(1, int(detail_n))
    also_n = max(0, int(also_n))
    if not _demote_news_only():
        pool = merge_by_theme(candidates, limit=detail_n + also_n)
        return pool[:detail_n], pool[detail_n:]

    primary = [s for s in candidates if str(s.get("confirm") or "") != "news_only"]
    secondary = [s for s in candidates if str(s.get("confirm") or "") == "news_only"]
    picked = merge_by_theme(primary, limit=detail_n)
    seen_themes = {theme_of(str(r.get("sector") or "")) for r in picked}
    also_src = [
        s
        for s in secondary
        if theme_of(str(s.get("sector") or "")) not in seen_themes
    ]
    # If primary is short, still do not promote news_only into Top.
    also = merge_by_theme(also_src, limit=also_n)
    return picked, also


def _age_decay_mult(published_at: str | None, fetched_at: str | None) -> float:
    """Down-weight stale headlines (overnight news fades into the afternoon)."""
    raw = (published_at or fetched_at or "").strip()
    if len(raw) < 16:
        return 1.0
    try:
        ts = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
    except ValueError:
        return 1.0
    hours = max(0.0, (datetime.now(CN_TZ) - ts).total_seconds() / 3600.0)
    if hours <= 6:
        return 1.0
    if hours <= 18:
        return 0.75
    if hours <= 36:
        return 0.5
    return 0.35


def filter_new_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep only rows worth inserting this refresh.

    Drops rows published before the retention window (they would be purged
    right after insert), rows whose fingerprint is already stored, and rows
    whose headline near-duplicates one stored within ``DEDUPE_LOOKBACK_HOURS``.

    Returns:
        ``(fresh_rows, {"stale", "known", "seen_dup"})``.
    """
    cutoff = (datetime.now(CN_TZ) - timedelta(days=int(cfg.ARTICLE_RETENTION_DAYS))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    live = [r for r in rows if not (r.get("published_at") and str(r["published_at"]) < cutoff)]
    known = existing_fingerprints([str(r.get("fingerprint") or "") for r in live])
    unseen = [r for r in live if r.get("fingerprint") not in known]
    fresh, seen_dup = drop_seen_titles(
        unseen, recent_titles(hours=int(cfg.DEDUPE_LOOKBACK_HOURS))
    )
    return fresh, {
        "stale": len(rows) - len(live),
        "known": len(live) - len(unseen),
        "seen_dup": seen_dup,
    }


def _digest_picks_key(kind: str, day: str) -> str:
    """Settings key that remembers which sectors a digest listed."""
    return f"digest_picks:{kind}:{day}"


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
        self._src_zero: dict[str, int] = {}

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
                rows, src_counts = await collect_all(client)
                try:
                    boards = await fetch_board_quotes(client)
                except Exception as exc:
                    warnings.append(f"boards: {exc}")
            fetched = len(rows)
            for name, count in src_counts.items():
                self._src_zero[name] = 0 if count else self._src_zero.get(name, 0) + 1
            src_down = [
                name for name, z in self._src_zero.items() if z >= int(cfg.SOURCE_ZERO_WARN_ROUNDS)
            ]
            if src_down:
                warnings.append("新闻源无数据：" + "、".join(src_down))
            rows, deduped = dedupe_articles(rows)
            rows, filt = filter_new_rows(rows)
            for row in rows:
                hits = match_sectors(
                    row.get("title") or "", row.get("summary") or "", row.get("tags")
                )
                mult = _age_decay_mult(row.get("published_at"), row.get("fetched_at"))
                mult *= float(cfg.CLS_LEVEL_MULT.get(str(row.get("importance") or ""), 1.0))
                if mult != 1.0 and hits:
                    for h in hits:
                        h["weight"] = round(float(h.get("weight") or 1.0) * mult, 3)
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
                    attach_article_cluster(
                        aid,
                        title=str(row.get("title") or ""),
                        sectors=primary_sector_names(hits),
                        source=str(row.get("source") or ""),
                    )
                except Exception as exc:
                    warnings.append(f"cluster: {type(exc).__name__}")
            try:
                purged = purge_old_articles(int(cfg.ARTICLE_RETENTION_DAYS))
            except Exception as exc:
                purged = 0
                warnings.append(f"purge: {exc}")

            hours = int(setting("heat_window_hours", cfg.HEAT_WINDOW_HOURS))
            now = datetime.now(CN_TZ)
            use_event = bool(
                setting("event_cluster_heat", getattr(cfg, "EVENT_CLUSTER_HEAT", False))
            )
            score_key = "event_score" if use_event else "raw_score"
            cur_rows = sector_heat(hours=hours)
            prev_rows = sector_heat_between(now - timedelta(hours=hours * 2), now - timedelta(hours=hours))
            hour_rows = sector_heat_between(now - timedelta(hours=1), now)
            hour_prev = sector_heat_between(now - timedelta(hours=2), now - timedelta(hours=1))
            prev_map = heat_map(prev_rows, score_key=score_key)
            hour_map = heat_map(hour_rows, score_key=score_key)
            hour_prev_map = heat_map(hour_prev, score_key=score_key)

            sectors: list[dict[str, Any]] = []
            for h in cur_rows:
                sector = str(h["sector"])
                score = float(h.get(score_key) or h.get("raw_score") or 0)
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
                from news_radar.score import bks_for_sector

                wanted_bks = bks_for_sector(sector)
                bk_warn = bool(wanted_bks) and (
                    board is None
                    or str(board.get("bk") or "").upper()
                    not in {str(x).upper() for x in wanted_bks}
                )
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
                    "score_mode": score_key,
                    "raw_score": float(h.get("raw_score") or 0),
                    "event_score": float(h.get("event_score") or 0),
                    "event_count": int(h.get("event_count") or 0),
                    "multi_source_events": int(h.get("multi_source_events") or 0),
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
                    "bk_warn": bk_warn,
                }
                row_out["action_hint"] = action_hint(row_out)
                sectors.append(row_out)
            sectors.sort(key=_rank_key, reverse=True)
            macro = [s for s in sectors if is_context_sector(str(s.get("sector") or ""))]
            sectors = [s for s in sectors if not is_context_sector(str(s.get("sector") or ""))]

            # Watch list: rising and/or board-confirmed — what users should stare at.
            # When demote is on, high-score news_only stays off the primary watch strip.
            watch = [
                s
                for s in sectors
                if s.get("rising")
                or s.get("confirm") in ("resonance", "board_lead", "diverge")
                or (
                    not _demote_news_only()
                    and float(s.get("score") or 0) >= 6
                    and s.get("confirm") == "news_only"
                )
            ][:12]
            top3 = merge_by_theme(
                [
                    s
                    for s in sectors
                    if s.get("confirm") in ("resonance", "board_lead") or s.get("rising")
                ],
                limit=3,
            )

            pushed = 0
            try:
                pushed = self._maybe_push(sectors, now=now, boards=boards, macro=macro)
            except Exception as exc:
                log.exception("push failed")
                warnings.append(f"push: {exc}")
            try:
                self._settle_resonance(boards, now=now)
            except Exception as exc:
                warnings.append(f"resonance: {exc}")
            try:
                self._maybe_empty_window_alert(now=now)
            except Exception as exc:
                warnings.append(f"empty_alert: {exc}")

            stamp = now.strftime("%Y-%m-%d %H:%M:%S")
            self.snapshot = {
                "ok": True,
                "updated_at": stamp,
                "trading_day": is_trading_day(now),
                "sectors": sectors[:30],
                "macro": macro,
                "top3": top3,
                "watch": watch,
                "articles": list_recent_articles(60),
                "warnings": warnings,
                "push_schedule": push_schedule_status(now),
                "stats": {
                    "fetched": fetched,
                    "inserted": new_n,
                    "deduped": deduped + filt["seen_dup"],
                    "stale": filt["stale"],
                    "sources": src_counts,
                    "sources_down": src_down,
                    "purged": purged,
                    "pushed": pushed,
                    "boards": len(boards),
                    "heat_window_hours": hours,
                    "pushes_today": count_pushes_today(ok_only=True),
                    "push_daily_max": int(
                        setting("push_daily_max", cfg.PUSH_DAILY_MAX)
                    ),
                },
            }
            return self.snapshot

    def export_sectors(self, *, limit: int = 8) -> dict[str, Any]:
        """Compact payload for 牛来 / external consumers."""
        snap = self.snapshot or {}
        limit_n = max(1, int(limit))
        sectors = list(snap.get("sectors") or [])
        watch = list(snap.get("watch") or [])
        if _demote_news_only():
            # Prefer board-confirmed / rising; append news_only only to fill.
            primary = [
                r
                for r in sectors
                if str(r.get("confirm") or "") != "news_only"
                and (
                    r.get("rising")
                    or r.get("confirm") in ("resonance", "board_lead", "diverge")
                    or float(r.get("score") or 0) >= float(cfg.MORNING_PUSH_MIN_SCORE)
                )
            ]
            secondary = [
                r for r in sectors if str(r.get("confirm") or "") == "news_only"
            ]
            primary.sort(key=_rank_key, reverse=True)
            secondary.sort(key=_rank_key, reverse=True)
            rows = (primary + secondary)[:limit_n]
        else:
            rows = (watch or sectors)[:limit_n]
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

    def _maybe_push(
        self,
        sectors: list[dict[str, Any]],
        *,
        now: datetime,
        boards: list[dict[str, Any]] | None = None,
        macro: list[dict[str, Any]] | None = None,
    ) -> int:
        """Run the three scheduled digests (mute on holidays)."""
        if not bool(setting("serverchan_enabled", False)):
            return 0
        key = str(setting("serverchan_sendkey", "") or "").strip()
        if not key:
            return 0
        if not is_trading_day(now):
            return 0
        sent = 0
        sent += self._push_scheduled_digest(
            sectors,
            key=key,
            now=now,
            kind="morning",
            start=cfg.MORNING_PUSH_START,
            end=cfg.MORNING_PUSH_END,
            title_prefix="新闻雷达 · 盘前总报",
            heading="盘前总报",
            tip="开盘前对照：优先 **共振 / 盘面已动**；「仅新闻」只观察不追。",
            macro=macro,
        )
        sent += self._push_scheduled_digest(
            sectors,
            key=key,
            now=now,
            kind="midday",
            start=cfg.MIDDAY_PUSH_START,
            end=cfg.MIDDAY_PUSH_END,
            title_prefix="新闻雷达 · 盘中总报",
            heading="盘中总报（13:00）",
            tip="午前对照：热板块是否还在、是否已共振。",
            macro=macro,
        )
        sent += self._push_scheduled_digest(
            sectors,
            key=key,
            now=now,
            kind="evening",
            start=cfg.EVENING_PUSH_START,
            end=cfg.EVENING_PUSH_END,
            title_prefix="新闻雷达 · 晚间总报",
            heading="晚间总报",
            tip="当日催化收束；含隔夜/全球 → A 股传导线索（软提示）。",
            include_overnight=True,
        )
        # Mark resonance after midday for next-day settle (also refresh at evening).
        if _in_hhmm_window(now, cfg.MIDDAY_PUSH_START, "15:10") or _in_hhmm_window(
            now, cfg.EVENING_PUSH_START, cfg.EVENING_PUSH_END
        ):
            marks = [
                s
                for s in sectors
                if s.get("confirm") in ("resonance", "board_lead")
            ][:8]
            if marks:
                upsert_resonance_marks(now.strftime("%Y-%m-%d"), marks)
        return sent

    def _push_scheduled_digest(
        self,
        sectors: list[dict[str, Any]],
        *,
        key: str,
        now: datetime,
        kind: str,
        start: str,
        end: str,
        title_prefix: str,
        heading: str,
        tip: str,
        include_overnight: bool = False,
        macro: list[dict[str, Any]] | None = None,
    ) -> int:
        """Push at most one digest per kind per calendar day inside its window.

        ``macro`` background buckets get their own section (never a Top slot);
        the evening digest carries the overnight transmission section instead.
        """
        if not _in_hhmm_window(now, start, end):
            return 0
        day = now.strftime("%Y-%m-%d")
        push_key = f"digest:{kind}:{day}"
        if was_pushed_recently(push_key, 20 * 3600):
            return 0
        min_score = float(setting("morning_push_min_score", cfg.MORNING_PUSH_MIN_SCORE))
        top_n = int(setting("morning_push_top_n", cfg.MORNING_PUSH_TOP_N))
        picked, also_watch = _pick_digest_rows(
            sectors,
            min_score=min_score,
            detail_n=top_n,
            also_n=_ALSO_WATCH_N,
        )
        if not picked and not include_overnight:
            return 0
        if _require_board_confirm():
            confirmed = [
                r
                for r in picked
                if str(r.get("confirm") or "") in ("resonance", "board_lead")
            ]
            if not confirmed:
                log.info(
                    "digest %s skipped: no resonance/board_lead in Top (require_board_confirm)",
                    kind,
                )
                return 0
        compare = ""
        prev = _DIGEST_PREV_KIND.get(kind)
        if prev:
            earlier = load_setting(_digest_picks_key(prev[0], day), None)
            if isinstance(earlier, list):
                compare = digest_compare_line(picked, earlier, label=prev[1])
        extra: list[str] = []
        if include_overnight:
            blob = "\n".join(
                str(a.get("title") or "") for a in list_recent_articles(40)
            )
            for s in sectors[:12]:
                for a in (s.get("articles") or [])[:2]:
                    blob += "\n" + str(a.get("title") or "")
            hints = overnight_hints_from_text(blob, limit=5)
            if hints:
                extra.extend(format_overnight_sections(hints))
        elif macro:
            extra.extend(format_macro_section(macro))
        if not picked and not extra:
            return 0
        as_of = now.strftime("%Y-%m-%d %H:%M")
        title, desp = format_watch_digest(
            picked or [],
            as_of=as_of,
            title_prefix=title_prefix,
            heading=heading,
            tip=tip,
            extra_sections=extra or None,
            overview=digest_overview_line(
                [s for s in sectors if float(s.get("score") or 0) >= min_score]
            ),
            compare=compare,
            also_watch=also_watch or None,
        )
        if self._send_push(key, push_key, title, desp, kind=kind):
            save_setting(
                _digest_picks_key(kind, day),
                [str(r.get("sector") or "") for r in picked if r.get("sector")],
            )
            log.info("serverchan %s digest n=%s", kind, len(picked))
            return 1
        return 0

    def _send_push(
        self, key: str, push_key: str, title: str, desp: str, *, kind: str = ""
    ) -> bool:
        """Apply daily quota, call Server酱, and always write history."""
        max_n = int(setting("push_daily_max", cfg.PUSH_DAILY_MAX))
        if count_pushes_today(ok_only=True) >= max_n:
            log_push(
                push_key,
                title,
                kind=kind,
                ok=False,
                desp=desp,
                error=f"daily quota {max_n}",
            )
            log.warning("push blocked by daily quota key=%s", push_key)
            return False
        result = notify_serverchan(key, title, desp)
        ok = bool(result.get("ok"))
        log_push(
            push_key,
            title,
            kind=kind or "",
            ok=ok,
            desp=desp,
            error=str(result.get("error") or ""),
        )
        return ok

    def _maybe_empty_window_alert(self, *, now: datetime) -> None:
        """Once per day: if morning window passed with no digest, notify once."""
        if not cfg.EMPTY_WINDOW_ALERT or not is_trading_day(now):
            return
        if not bool(setting("serverchan_enabled", False)):
            return
        key = str(setting("serverchan_sendkey", "") or "").strip()
        if not key:
            return
        end_h, end_m = _parse_hhmm(cfg.MORNING_PUSH_END)
        minutes = now.hour * 60 + now.minute
        if minutes < end_h * 60 + end_m + 5:
            return
        if minutes > 10 * 60 + 30:
            return
        day = now.strftime("%Y-%m-%d")
        digest_key = f"digest:morning:{day}"
        if was_pushed_recently(digest_key, 20 * 3600):
            return
        alert_key = f"alert:empty:morning:{day}"
        if was_pushed_recently(alert_key, 20 * 3600):
            return
        title = "新闻雷达 · 盘前总报空窗"
        desp = (
            f"交易日 {day} 盘前窗口已过，但未成功发出盘前总报。\n\n"
            "请检查：热度是否过低、SendKey、配额、服务是否在窗口内在线。"
        )
        self._send_push(key, alert_key, title, desp, kind="alert")

    def _settle_resonance(
        self, boards: list[dict[str, Any]], *, now: datetime
    ) -> None:
        """Fill next-day board pct for prior resonance marks (once per mark)."""
        if not is_trading_day(now):
            return
        # Settle after open so day-move is meaningful.
        if now.hour * 60 + now.minute < 10 * 60:
            return
        today = now.strftime("%Y-%m-%d")
        pending = list_unsettle_resonance_marks(today)
        if not pending or not boards:
            return
        by_bk = {str(b.get("bk") or "").upper(): b for b in boards}
        by_name = {str(b.get("name") or ""): b for b in boards}
        bench = _board_median_pct(boards)
        for m in pending:
            bk = str(m.get("board_bk") or "").upper()
            sector = str(m.get("sector") or "")
            hit = by_bk.get(bk) if bk else None
            if hit is None:
                for name, b in by_name.items():
                    if sector and sector.split("/")[0] in name:
                        hit = b
                        break
            pct = float(hit["pct"]) if hit and hit.get("pct") is not None else None
            excess = (
                round(pct - bench, 4)
                if pct is not None and bench is not None
                else None
            )
            save_resonance_outcome(
                str(m["trade_date"]),
                sector,
                next_date=today,
                next_board_pct=pct,
                next_bench_pct=bench,
                next_excess_pct=excess,
            )
        # Older rows may lack excess columns — fill from same-day median proxy.
        try:
            backfill_resonance_excess(limit=400)
        except Exception:  # noqa: BLE001 — settle must not break refresh
            pass

    def push_status(self) -> dict[str, Any]:
        """UI/API payload: schedule + recent pushes + light backtest."""
        now = datetime.now(CN_TZ)
        return {
            "ok": True,
            "schedule": push_schedule_status(now),
            "recent": list_push_log(20),
            "backtest": resonance_backtest_summary(30),
            "effect": effect_observe_snapshot(30),
            "serverchan_enabled": bool(setting("serverchan_enabled", False)),
            "pushes_today": count_pushes_today(ok_only=True),
            "push_daily_max": int(setting("push_daily_max", cfg.PUSH_DAILY_MAX)),
        }

    def query_history(self, **kwargs: Any) -> dict[str, Any]:
        """Proxy to push history query for the API layer."""
        return query_push_log(**kwargs)


engine = RadarEngine()
