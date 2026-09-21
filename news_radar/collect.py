"""Public news collectors (East Money columns + CLS telegraph)."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from news_radar.config import HTTP_HEADERS

log = logging.getLogger("news_radar.collect")
try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    CN_TZ = timezone(timedelta(hours=8))

# East Money news columns: finance / stock / headline / CN / global / focus.
_EM_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("350", "东财财经", "A"),
    ("344", "东财股市", "A"),
    ("351", "东财要闻", "A"),
    ("352", "东财国内", "A"),
    ("353", "东财国际", "G"),
    ("724", "东财焦点", "A"),
)


def _fp(*parts: str) -> str:
    raw = "|".join(p.strip() for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


async def fetch_eastmoney_column(
    client: httpx.AsyncClient,
    column: str,
    *,
    source: str,
    region: str = "A",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Fetch one East Money news column list."""
    url = (
        "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        f"?client=web&biz=web_news_col&column={column}&order=1"
        f"&needInteractData=0&page_index=1&page_size={limit}&req_trace=news-radar"
    )
    try:
        resp = await client.get(url, headers=HTTP_HEADERS, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("eastmoney col %s failed: %s", column, exc)
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
                "fingerprint": _fp("em", column, art_code or title),
                "source": source,
                "title": title,
                "summary": summary,
                "url": url_u,
                "published_at": show_time or None,
                "fetched_at": _now_str(),
                "region": region,
            }
        )
    return out


async def fetch_cls_telegraph(client: httpx.AsyncClient, limit: int = 40) -> list[dict[str, Any]]:
    """Best-effort CLS telegraph headlines (HTML scrape; may break)."""
    url = "https://www.cls.cn/telegraph"
    try:
        resp = await client.get(
            url, headers={**HTTP_HEADERS, "Referer": "https://www.cls.cn/"}, timeout=20.0
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        log.warning("cls telegraph failed: %s", exc)
        return []

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


async def fetch_sina_finance_roll(client: httpx.AsyncClient, limit: int = 30) -> list[dict[str, Any]]:
    """Fetch Sina finance roll headlines (best-effort public API)."""
    url = (
        "https://feed.mix.sina.com.cn/api/roll/get"
        "?pageid=153&lid=2516&k=&num=40&page=1"
    )
    try:
        resp = await client.get(
            url,
            headers={**HTTP_HEADERS, "Referer": "https://finance.sina.com.cn/"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("sina roll failed: %s", exc)
        return []

    items = (((data or {}).get("result") or {}).get("data")) or []
    out: list[dict[str, Any]] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        url_u = str(it.get("url") or it.get("link") or "").strip()
        summary = str(it.get("intro") or it.get("summary") or "").strip()
        show_time = str(it.get("ctime") or it.get("create_time") or "").strip()
        docid = str(it.get("docid") or it.get("oid") or title)
        out.append(
            {
                "fingerprint": _fp("sina", docid),
                "source": "新浪财经",
                "title": title[:200],
                "summary": summary[:400],
                "url": url_u,
                "published_at": show_time or None,
                "fetched_at": _now_str(),
                "region": "A",
            }
        )
        if len(out) >= limit:
            break
    return out


async def collect_all(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Gather articles from all configured sources."""
    coros = [
        fetch_eastmoney_column(client, col, source=src, region=region)
        for col, src, region in _EM_COLUMNS
    ]
    coros.append(fetch_cls_telegraph(client))
    coros.append(fetch_sina_finance_roll(client))
    batches = await _gather(*coros)
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
