"""East Money board quotes for news↔盘面 confirmation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from news_radar.config import HTTP_HEADERS
from news_radar.lexicon import BOARD_ALIASES, BOARD_BK
from news_radar.score import bks_for_sector

log = logging.getLogger("news_radar.boards")

EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"


def _clist_url(fs: str, pz: int = 100, pn: int = 1) -> str:
    fields = "f12,f13,f14,f2,f3,f20,f104,f105,f128,f140,f136"
    return (
        "https://push2delay.eastmoney.com/api/qt/clist/get"
        f"?pn={pn}&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f3"
        f"&ut={EASTMONEY_UT}&fs={fs}&fields={fields}"
    )


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    resp = await client.get(url, headers=HTTP_HEADERS, timeout=20.0)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


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
    """Fetch industry + concept board day moves from East Money."""
    out: list[dict[str, Any]] = []
    try:
        concept, industry = await _gather_boards(client)
    except Exception as exc:
        log.warning("fetch boards failed: %s", exc)
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
    return out


async def _gather_boards(client: httpx.AsyncClient) -> tuple[list[dict], list[dict]]:
    import asyncio

    c_payload, i1, i2, i3 = await asyncio.gather(
        _get_json(client, _clist_url("m:90+t:3", pz=80)),
        _get_json(client, _clist_url("m:90+t:2", pz=100, pn=1)),
        _get_json(client, _clist_url("m:90+t:2", pz=100, pn=2)),
        _get_json(client, _clist_url("m:90+t:2", pz=100, pn=3)),
    )
    concept = _rows(c_payload)
    industry = _rows(i1) + _rows(i2) + _rows(i3)
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
