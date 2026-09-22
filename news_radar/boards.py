"""East Money board quotes for news↔盘面 confirmation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from news_radar.config import HTTP_HEADERS
from news_radar.lexicon import BOARD_ALIASES, BOARD_BK
from news_radar.score import bks_for_sector

log = logging.getLogger("news_radar.boards")

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"

_CLIST_HOSTS: tuple[str, ...] = (
    "push2.eastmoney.com",
    "push2delay.eastmoney.com",
    "push2his.eastmoney.com",
)
_CLIST_HOST_PREF: str | None = None
# Soft board confirm does not need sub-minute freshness; cache cuts same-IP clist noise.
_BOARD_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_BOARD_CACHE_TTL_SEC = 240.0


def _clist_url(fs: str, pz: int = 100, pn: int = 1, *, host: str | None = None) -> str:
    """Build a board clist URL on the given (or preferred) East Money edge."""
    fields = "f12,f13,f14,f2,f3,f20,f104,f105,f128,f140,f136"
    h = host or _CLIST_HOST_PREF or _CLIST_HOSTS[0]
    return (
        f"https://{h}/api/qt/clist/get"
        f"?pn={pn}&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f3"
        f"&ut={EASTMONEY_UT}&fs={fs}&fields={fields}"
    )


def _host_order() -> list[str]:
    """Prefer last-good host, then the rest."""
    pref = _CLIST_HOST_PREF
    if pref and pref in _CLIST_HOSTS:
        return [pref, *[h for h in _CLIST_HOSTS if h != pref]]
    return list(_CLIST_HOSTS)


async def _get_clist_json(
    client: httpx.AsyncClient, fs: str, *, pz: int = 100, pn: int = 1
) -> dict[str, Any]:
    """GET clist with multi-host failover when one East Money edge returns 5xx."""
    global _CLIST_HOST_PREF
    last_error: Exception | None = None
    for h in _host_order():
        url = _clist_url(fs, pz=pz, pn=pn, host=h)
        try:
            resp = await client.get(url, headers=HTTP_HEADERS, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                _CLIST_HOST_PREF = h
                return data
            raise RuntimeError("clist non-dict payload")
        except Exception as exc:
            last_error = exc
            if isinstance(exc, httpx.HTTPStatusError):
                code = getattr(getattr(exc, "response", None), "status_code", 0) or 0
                if code >= 500:
                    continue
            await asyncio.sleep(0.2)
    if last_error is not None:
        raise last_error
    return {}


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    diff = ((payload.get("data") or {}).get("diff")) or []
    return [x for x in diff if isinstance(x, dict)]


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "-":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


async def fetch_board_quotes(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch board day moves: prefer market-desk export, else East Money clist."""
    import time

    global _BOARD_CACHE
    now = time.time()
    if _BOARD_CACHE and now - _BOARD_CACHE[0] < _BOARD_CACHE_TTL_SEC:
        return [dict(row) for row in _BOARD_CACHE[1]]

    desk_rows = await _fetch_boards_from_desk(client)
    if desk_rows:
        _BOARD_CACHE = (now, desk_rows)
        return [dict(row) for row in desk_rows]

    out: list[dict[str, Any]] = []
    try:
        concept, industry = await _gather_boards(client)
    except Exception as exc:
        log.warning("fetch boards failed: %s", exc)
        if _BOARD_CACHE:
            return [dict(row) for row in _BOARD_CACHE[1]]
        return []
    for item in concept + industry:
        name = str(item.get("f14") or "")
        code = str(item.get("f12") or "")
        if not name or not code.startswith("BK"):
            continue
        out.append(
            {
                "bk": code,
                "name": name,
                "pct": round(_num(item.get("f3")), 2),
                "amount": _num(item.get("f20")),
                "leader": str(item.get("f128") or ""),
            }
        )
    if out:
        _BOARD_CACHE = (now, out)
    return out


async def _fetch_boards_from_desk(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Pull soft board quotes from market-desk when co-hosted on the same box."""
    try:
        from news_radar.settings import setting

        url = str(setting("desk_boards_url", "") or "").strip()
    except Exception:
        url = ""
    if not url:
        from news_radar import config as nr_cfg

        url = str(getattr(nr_cfg, "DESK_BOARDS_URL", "") or "")
    url = str(url or "").rstrip("/")
    if not url:
        return []
    try:
        resp = await client.get(url, timeout=4.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.info("desk boards skipped: %s", exc)
        return []
    rows = data.get("boards") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        bk = str(raw.get("bk") or "").upper()
        name = str(raw.get("name") or "")
        if not bk.startswith("BK") or not name:
            continue
        out.append(
            {
                "bk": bk,
                "name": name,
                "pct": round(_num(raw.get("pct")), 2),
                "amount": _num(raw.get("amount")),
                "leader": str(raw.get("leader") or ""),
            }
        )
    if out:
        log.info("board quotes from desk n=%s", len(out))
    return out


async def _gather_boards(client: httpx.AsyncClient) -> tuple[list[dict], list[dict]]:
    # Serialize pages: parallel clist on the same IP often coincides with desk ticks.
    c_payload = await _get_clist_json(client, "m:90+t:3", pz=80)
    i1 = await _get_clist_json(client, "m:90+t:2", pz=100, pn=1)
    i2 = await _get_clist_json(client, "m:90+t:2", pz=100, pn=2)
    concept = _rows(c_payload)
    industry = _rows(i1) + _rows(i2)
    return concept, industry


def match_board_for_sector(
    sector: str, boards: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Pick East Money board: prefer configured BK codes, then name aliases."""
    by_bk = {str(b.get("bk") or "").upper(): b for b in boards}
    for code in bks_for_sector(sector) or BOARD_BK.get(sector) or []:
        hit = by_bk.get(str(code).upper())
        if hit:
            return hit

    aliases = list(BOARD_ALIASES.get(sector) or [])
    if not aliases:
        aliases = [sector.split("/")[0]]
    best: dict[str, Any] | None = None
    best_score = -1.0
    for b in boards:
        name = str(b.get("name") or "")
        hit_n = sum(1 for a in aliases if a and a in name)
        if hit_n <= 0:
            continue
        score = hit_n * 10 + abs(float(b.get("pct") or 0))
        if score > best_score:
            best_score = score
            best = b
    return best


def confirm_label(*, news_score: float, delta: float, board_pct: float | None) -> dict[str, Any]:
    """Classify news heat vs board day move (soft labels only)."""
    rising = delta >= 1.5
    hot = news_score >= 4.0
    if board_pct is None:
        return {
            "confirm": "unknown",
            "label": "待确认",
            "note": "盘面行情暂缺",
            "board_pct": None,
        }
    pct = float(board_pct)
    if hot and rising and pct >= 0.8:
        return {
            "confirm": "resonance",
            "label": "共振",
            "note": f"新闻升温且板块 {pct:+.2f}%",
            "board_pct": pct,
        }
    if hot and pct >= 1.5:
        return {
            "confirm": "board_lead",
            "label": "盘面已动",
            "note": f"板块 {pct:+.2f}%（新闻热度一般）",
            "board_pct": pct,
        }
    if hot and rising and pct < -0.5:
        return {
            "confirm": "diverge",
            "label": "背离",
            "note": f"新闻热但板块 {pct:+.2f}%",
            "board_pct": pct,
        }
    if hot and pct < 0.3:
        return {
            "confirm": "news_only",
            "label": "仅新闻",
            "note": f"板块 {pct:+.2f}% 尚未跟",
            "board_pct": pct,
        }
    return {
        "confirm": "neutral",
        "label": "观察",
        "note": f"板块 {pct:+.2f}%",
        "board_pct": pct,
    }
