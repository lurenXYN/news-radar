"""Push schedule helpers: next windows + human labels."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from news_radar import config as cfg
from news_radar.calendar import is_trading_day


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = str(s or "09:00").split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _at(day: date, hhmm: str, *, tzinfo) -> datetime:
    h, m = _parse_hhmm(hhmm)
    return datetime.combine(day, time(hour=h, minute=m), tzinfo=tzinfo)


def push_schedule_status(now: datetime) -> dict[str, Any]:
    """Describe today's windows and the next upcoming digest slot."""
    trading = is_trading_day(now)
    windows = [
        {
            "id": "morning",
            "label": "盘前总报",
            "start": cfg.MORNING_PUSH_START,
            "end": cfg.MORNING_PUSH_END,
            "needs_trading_day": True,
        },
        {
            "id": "midday",
            "label": "盘中总报",
            "start": cfg.MIDDAY_PUSH_START,
            "end": cfg.MIDDAY_PUSH_END,
            "needs_trading_day": True,
        },
        {
            "id": "evening",
            "label": "晚间总报",
            "start": cfg.EVENING_PUSH_START,
            "end": cfg.EVENING_PUSH_END,
            "needs_trading_day": True,
        },
    ]
    today = []
    for w in windows:
        active = trading if w["needs_trading_day"] else True
        start_dt = _at(now.date(), w["start"], tzinfo=now.tzinfo)
        end_dt = _at(now.date(), w["end"], tzinfo=now.tzinfo)
        state = "skip_holiday"
        if active:
            if start_dt <= now <= end_dt:
                state = "open"
            elif now < start_dt:
                state = "upcoming"
            else:
                state = "passed"
        today.append({**w, "state": state, "active_today": active})

    next_slot = None
    day = now.date()
    for i in range(16):
        d = day if i == 0 else day + timedelta(days=i)
        if not is_trading_day(d):
            continue
        for w in windows:
            start_dt = _at(d, w["start"], tzinfo=now.tzinfo)
            if start_dt > now:
                next_slot = {
                    "id": w["id"],
                    "label": w["label"],
                    "at": start_dt.strftime("%Y-%m-%d %H:%M"),
                }
                break
        if next_slot:
            break

    return {
        "trading_day": trading,
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "next": next_slot,
        "brief": {
            "enabled_default": True,
            "session": "09:30–11:30 / 13:00–15:00（仅交易日）",
            "cooldown_minutes": int(cfg.PUSH_COOLDOWN_SECONDS) // 60,
            "digest_gap_minutes": int(cfg.DIGEST_GAP_SECONDS) // 60,
        },
    }
