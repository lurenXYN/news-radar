"""Auto-label push feedback from same-day related ETF / board moves.

Fills unmarked ``useful`` / ``useless`` using end-of-day ETF % (preferred)
or ``resonance_mark.board_pct`` as fallback. Never overwrites hand marks.
Observation only — does not change buy gates.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from news_radar.lexicon import SECTOR_RULES, etfs_for_sector_name

log = logging.getLogger("news_radar.auto_feedback")

CN_TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"

_SECTOR_HEAD_RE = re.compile(r"^##\s*\d+\.\s*([^\n·(（]+)")
_BOLD_SECTOR_RE = re.compile(r"\*\*([^*]+)\*\*")
_ETF_CODE_RE = re.compile(r"\b([015][0-9]{5})\b")
# Ignore flat noise around zero.
_FLAT_EPS = 0.05


def _known_sectors() -> set[str]:
    return {str(r.get("sector") or "") for r in SECTOR_RULES if r.get("sector")}


def parse_push_sectors(desp: str | None, title: str | None = None) -> list[str]:
    """Extract lexicon sector names mentioned in a digest body / title."""
    known = _known_sectors()
    found: list[str] = []
    text = f"{title or ''}\n{desp or ''}"
    for line in text.splitlines():
        m = _SECTOR_HEAD_RE.match(line.strip())
        if m:
            name = m.group(1).strip()
            if name in known and name not in found:
                found.append(name)
            continue
        for bm in _BOLD_SECTOR_RE.finditer(line):
            name = bm.group(1).strip()
            if name in known and name not in found:
                found.append(name)
    if not found:
        for name in known:
            if name and name in text and name not in found:
                found.append(name)
    return found


def parse_push_etf_codes(desp: str | None) -> list[str]:
    """Return six-digit ETF codes mentioned in the digest body."""
    out: list[str] = []
    for code in _ETF_CODE_RE.findall(str(desp or "")):
        if code not in out:
            out.append(code)
    return out


def _secid(code: str) -> str:
    """Map a six-digit A-share / ETF code to East Money ``secid``."""
    c = str(code or "").zfill(6)
    # 5xxxxx Shanghai ETF/fund; 1xxxxx Shenzhen ETF/fund.
    if c.startswith(("5", "6", "9")):
        return f"1.{c}"
    return f"0.{c}"


def fetch_etf_day_pct(code: str, trade_date: str, *, client: httpx.Client | None = None) -> float | None:
    """Return one ETF's day % change on ``trade_date`` (YYYY-MM-DD), or None."""
    day = str(trade_date or "")[:10].replace("-", "")
    if len(day) != 8:
        return None
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={_secid(code)}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59"
        f"&klt=101&fqt=1&beg={day}&end={day}&ut={EASTMONEY_UT}"
    )
    own = client is None
    http = client or httpx.Client(timeout=12.0)
    try:
        resp = http.get(url)
        resp.raise_for_status()
        data = resp.json() or {}
        klines = ((data.get("data") or {}).get("klines")) or []
        if not klines:
            return None
        # f51,date,open,close,high,low,vol,amt,...,pct
        parts = str(klines[0]).split(",")
        if len(parts) >= 9:
            return float(parts[8])
        if len(parts) >= 3:
            o, c = float(parts[1]), float(parts[2])
            if o:
                return round((c / o - 1.0) * 100.0, 3)
    except Exception as exc:
        log.debug("etf day pct fail %s %s: %s", code, trade_date, exc)
        return None
    finally:
        if own:
            http.close()
    return None


def _board_pct_for_sector(trade_date: str, sector: str) -> float | None:
    """Same-day board pct from resonance_mark, if recorded."""
    from news_radar.db import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT board_pct FROM resonance_mark WHERE trade_date=? AND sector=?",
            (str(trade_date)[:10], str(sector)),
        ).fetchone()
    if not row or row["board_pct"] is None:
        return None
    try:
        return float(row["board_pct"])
    except (TypeError, ValueError):
        return None


def score_push_day_move(
    row: dict[str, Any],
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Score one push by related ETF / board same-day moves.

    Returns ``label`` in useful|useless|skip plus diagnostic fields.
    """
    day = str(row.get("created_at") or "")[:10]
    desp = str(row.get("desp") or "")
    title = str(row.get("title") or "")
    sectors = parse_push_sectors(desp, title)
    etfs = parse_push_etf_codes(desp)
    for sec in sectors:
        for code in etfs_for_sector_name(sec):
            if code not in etfs:
                etfs.append(code)

    samples: list[dict[str, Any]] = []
    for code in etfs[:8]:
        pct = fetch_etf_day_pct(code, day, client=client)
        if pct is None:
            continue
        samples.append({"kind": "etf", "code": code, "pct": pct})

    if not samples:
        for sec in sectors:
            pct = _board_pct_for_sector(day, sec)
            if pct is None:
                continue
            samples.append({"kind": "board", "sector": sec, "pct": pct})

    if not samples:
        return {
            "label": "skip",
            "reason": "no_day_move",
            "day": day,
            "sectors": sectors,
            "etfs": etfs,
            "samples": [],
            "avg_pct": None,
        }

    avg = sum(float(s["pct"]) for s in samples) / len(samples)
    if avg > _FLAT_EPS:
        label = "useful"
    elif avg < -_FLAT_EPS:
        label = "useless"
    else:
        label = "skip"
    return {
        "label": label,
        "reason": "etf_day" if any(s["kind"] == "etf" for s in samples) else "board_day",
        "day": day,
        "sectors": sectors,
        "etfs": etfs,
        "samples": samples,
        "avg_pct": round(avg, 3),
    }


def auto_label_unmarked_pushes(
    *,
    since: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Fill unmarked (or all if ``force``) push feedback from same-day moves.

    Hand marks (``feedback_src`` empty or ``hand``) are kept unless ``force``.
    """
    from news_radar import config as cfg
    from news_radar.db import (
        get_push_log,
        init_db,
        query_push_log,
        set_push_feedback,
    )

    init_db()
    day_from = str(since or getattr(cfg, "EFFECT_OBSERVE_SINCE", "") or "").strip()[:10]
    if not day_from:
        day_from = datetime.now(CN_TZ).strftime("%Y-%m-%d")

    pack = query_push_log(limit=200, day_from=day_from, ok="1")
    rows = list(pack.get("rows") or [])
    useful_n = useless_n = skip_n = kept_n = 0
    details: list[dict[str, Any]] = []

    with httpx.Client(timeout=12.0) as client:
        for preview in rows:
            full = get_push_log(int(preview["id"])) or preview
            row = dict(full)
            fb = str(row.get("feedback") or "").strip().lower()
            src = str(row.get("feedback_src") or "").strip().lower()
            if fb and not force:
                # Keep hand marks; allow re-run to refresh previous auto labels.
                if src in ("", "hand") and fb in ("useful", "useless"):
                    kept_n += 1
                    continue
                if src not in ("etf_day", "board_day", "auto"):
                    kept_n += 1
                    continue
            scored = score_push_day_move(row, client=client)
            label = scored["label"]
            item = {
                "id": row.get("id"),
                "title": (row.get("title") or "")[:40],
                "day": scored.get("day"),
                "label": label,
                "avg_pct": scored.get("avg_pct"),
                "reason": scored.get("reason"),
                "samples": scored.get("samples"),
            }
            details.append(item)
            if label == "skip":
                skip_n += 1
                continue
            if dry_run:
                if label == "useful":
                    useful_n += 1
                else:
                    useless_n += 1
                continue
            src_tag = "etf_day" if scored.get("reason") == "etf_day" else "board_day"
            if set_push_feedback(int(row["id"]), label, src=src_tag):
                if label == "useful":
                    useful_n += 1
                else:
                    useless_n += 1
            else:
                skip_n += 1

    return {
        "ok": True,
        "since": day_from,
        "dry_run": dry_run,
        "scanned": len(rows),
        "useful": useful_n,
        "useless": useless_n,
        "skipped": skip_n,
        "kept_hand": kept_n,
        "items": details[:40],
        "note": (
            "代理手标：相关 ETF 当日涨跌均值为正→有用、负→没用；"
            "无 ETF 价则退回共振盘面%；不覆盖人工手标。"
        ),
    }
