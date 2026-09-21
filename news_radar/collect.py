"""Public news collectors (East Money finance columns + CLS telegraph HTML)."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from news_radar.config import HTTP_HEADERS

log = logging.getLogger("news_radar.collect")
CN_TZ = ZoneInfo("Asia/Shanghai")


def _fp(*parts: str) -> str:
    raw = "|".join(p.strip() for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


async def fetch_eastmoney_finance(client: httpx.AsyncClient, limit: int = 40) -> list[dict[str, Any]]:
    """Fetch East Money finance news list (public JSON API)."""
    url = (
        "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        "?client=web&biz=web_news_col&column=350&order=1"
        f"&needInteractData=0&page_index=1&page_size={limit}&req_trace=news-radar"
    )
    try:
        resp = await client.get(url, headers=HTTP_HEADERS, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("eastmoney finance failed: %s", exc)
        return []

    items = (((data or {}).get("data") or {}).get("list")) or []
    out: list[dict[str, Any]] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        art_code = str(it.get("code") or it.get("art_code") or "")
        url_u = str(it.get("url") or "").strip()
        if not url_u and art_code:
            url_u = f"https://finance.eastmoney.com/a/{art_code}.html"
        summary = str(it.get("digest") or it.get("summary") or "").strip()
        show_time = str(it.get("showTime") or it.get("publishTime") or "").strip()
        out.append(
            {
                "fingerprint": _fp("em", art_code or title),
                "source": "东财财经",
                "title": title,
                "summary": summary,
                "url": url_u,
                "published_at": show_time or None,
                "fetched_at": _now_str(),
                "region": "A",
            }
        )
    return out


async def fetch_eastmoney_stock(client: httpx.AsyncClient, limit: int = 40) -> list[dict[str, Any]]:
    """Fetch East Money stock-market news column."""
    url = (
        "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        "?client=web&biz=web_news_col&column=344&order=1"
        f"&needInteractData=0&page_index=1&page_size={limit}&req_trace=news-radar"
    )
    try:
        resp = await client.get(url, headers=HTTP_HEADERS, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("eastmoney stock failed: %s", exc)
        return []

    items = (((data or {}).get("data") or {}).get("list")) or []
    out: list[dict[str, Any]] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        art_code = str(it.get("code") or it.get("art_code") or "")
        url_u = str(it.get("url") or "").strip()
        if not url_u and art_code:
            url_u = f"https://finance.eastmoney.com/a/{art_code}.html"
        summary = str(it.get("digest") or it.get("summary") or "").strip()
        show_time = str(it.get("showTime") or it.get("publishTime") or "").strip()
        out.append(
            {
                "fingerprint": _fp("em-stock", art_code or title),
                "source": "东财股市",
                "title": title,
                "summary": summary,
                "url": url_u,
                "published_at": show_time or None,
                "fetched_at": _now_str(),
                "region": "A",
            }
        )
    return out


async def fetch_cls_telegraph(client: httpx.AsyncClient, limit: int = 30) -> list[dict[str, Any]]:
    """Best-effort CLS telegraph headlines (HTML scrape; may break)."""
    url = "https://www.cls.cn/telegraph"
    try:
        resp = await client.get(url, headers={**HTTP_HEADERS, "Referer": "https://www.cls.cn/"}, timeout=20.0)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        log.warning("cls telegraph failed: %s", exc)
        return []

    # Lightweight extract: content fields often embedded as JSON-like strings.
    titles = re.findall(r'"content"\s*:\s*"([^"]{8,200})"', html)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in titles:
        title = (
            raw.encode("utf-8")
            .decode("unicode_escape", errors="ignore")
            .replace("\\n", " ")
            .strip()
        )
        title = re.sub(r"<[^>]+>", "", title)
        if len(title) < 8 or title in seen:
            continue
        seen.add(title)
        out.append(
            {
                "fingerprint": _fp("cls", title),
                "source": "财联社电报",
                "title": title[:180],
                "summary": "",
                "url": "https://www.cls.cn/telegraph",
                "published_at": None,
                "fetched_at": _now_str(),
                "region": "A",
            }
        )
        if len(out) >= limit:
            break
    return out


async def collect_all(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Gather articles from all sources (dedupe by fingerprint later in DB)."""
    batches = await _gather(
        fetch_eastmoney_finance(client),
        fetch_eastmoney_stock(client),
        fetch_cls_telegraph(client),
    )
    merged: list[dict[str, Any]] = []
    for batch in batches:
        merged.extend(batch)
    return merged


async def _gather(*coros):
    import asyncio

    results = await asyncio.gather(*coros, return_exceptions=True)
    out = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("collector error: %s", r)
            out.append([])
        else:
            out.append(r)
    return out
