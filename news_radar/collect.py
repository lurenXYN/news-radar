"""Public news collectors (East Money columns + CLS telegraph + Sina roll)."""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
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
CLS_SOURCE = "财联社电报"
SINA_SOURCE = "新浪财经"
SOURCE_NAMES: tuple[str, ...] = tuple(src for _, src, _ in _EM_COLUMNS) + (CLS_SOURCE, SINA_SOURCE)

_CLS_URL = "https://www.cls.cn/v1/roll/get_roll_list"
_CLS_PARAMS = {"app": "CailianpressWeb", "os": "web", "sv": "8.4.6"}


def _fp(*parts: str) -> str:
    raw = "|".join(p.strip() for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def norm_time(raw: Any) -> str | None:
    """Normalize a source timestamp to ``YYYY-MM-DD HH:MM:SS`` in China time.

    Accepts Unix seconds / milliseconds and ``-`` / ``/`` / ``T`` separated
    date-times. Stored times are compared as strings, so anything that cannot
    be parsed returns None (callers then fall back to the fetch time).

    Args:
        raw: Timestamp as delivered by the source.

    Returns:
        Normalized string, or None.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        if value > 10**12:
            value //= 1000
        if value < 10**9:
            return None
        return datetime.fromtimestamp(value, CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    text = text.replace("T", " ").replace("/", "-")
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            return datetime.strptime(text[:size], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


async def fetch_eastmoney_column(
    client: httpx.AsyncClient,
    column: str,
    *,
    source: str,
    region: str = "A",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Fetch one East Money news column list.

    The fingerprint uses the article code alone, so the same article listed
    under several columns is stored once.
    """
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
        out.append(
            {
                "fingerprint": _fp("em", art_code) if art_code else _fp("em", column, title),
                "source": source,
                "title": title,
                "summary": summary,
                "url": url_u,
                "published_at": norm_time(it.get("showTime") or it.get("publishTime")),
                "fetched_at": _now_str(),
                "region": region,
            }
        )
    return out


def cls_sign(params: dict[str, str]) -> str:
    """Return the CLS web API signature: md5(sha1(sorted query string))."""
    query = urllib.parse.urlencode(sorted(params.items()))
    return hashlib.md5(hashlib.sha1(query.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()


_CLS_HEAD_RE = re.compile(r"^【([^】]{4,120})】")
_CLS_DATELINE_RE = re.compile(r"^财联社\d{1,2}月\d{1,2}日电[，,]?")


def parse_cls_items(items: list[dict[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    """Convert CLS ``roll_data`` entries into article rows.

    Untitled telegraphs take the bracketed lead (or the first 80 chars) as the
    title. Subject and stock names go to ``tags`` for sector matching and the
    editorial level (A / B / C) to ``importance``.
    """
    out: list[dict[str, Any]] = []
    for it in items or []:
        body = re.sub(r"<[^>]+>", "", str(it.get("brief") or it.get("content") or "")).strip()
        title = str(it.get("title") or "").strip()
        head = _CLS_HEAD_RE.match(body)
        if not title:
            title = head.group(1) if head else _CLS_DATELINE_RE.sub("", body)[:80]
        body = _CLS_DATELINE_RE.sub("", _CLS_HEAD_RE.sub("", body)).strip()
        if len(title) < 6:
            continue
        tags = [
            str(s.get("subject_name") or s.get("name") or "").strip()
            for s in (it.get("subjects") or [])
        ] + [
            str(s.get("name") or s.get("secu_name") or "").strip()
            for s in (it.get("stock_list") or [])
        ]
        art_id = str(it.get("id") or "")
        out.append(
            {
                "fingerprint": _fp("cls", art_id) if art_id else _fp("cls", title),
                "source": CLS_SOURCE,
                "title": title[:180],
                "summary": body[:400],
                "url": f"https://www.cls.cn/detail/{art_id}" if art_id else "https://www.cls.cn/telegraph",
                "published_at": norm_time(it.get("ctime")),
                "fetched_at": _now_str(),
                "region": "A",
                "tags": [t for t in tags if t][:12],
                "importance": str(it.get("level") or "").strip().upper() or None,
            }
        )
        if len(out) >= limit:
            break
    return out


async def fetch_cls_telegraph(client: httpx.AsyncClient, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch the latest CLS telegraphs from the signed web roll API."""
    params = {**_CLS_PARAMS, "rn": str(limit), "category": "", "last_time": "", "refresh_type": "1"}
    params["sign"] = cls_sign(params)
    try:
        resp = await client.get(
            _CLS_URL,
            params=params,
            headers={**HTTP_HEADERS, "Referer": "https://www.cls.cn/telegraph", "Origin": "https://www.cls.cn"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("cls telegraph failed: %s", exc)
        return []
    if (data or {}).get("errno") not in (0, None):
        log.warning("cls telegraph errno=%s msg=%s", data.get("errno"), data.get("msg"))
        return []
    return parse_cls_items(((data or {}).get("data") or {}).get("roll_data") or [], limit=limit)


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
        docid = str(it.get("docid") or it.get("oid") or title)
        out.append(
            {
                "fingerprint": _fp("sina", docid),
                "source": SINA_SOURCE,
                "title": title[:200],
                "summary": summary[:400],
                "url": url_u,
                "published_at": norm_time(it.get("ctime") or it.get("create_time")),
                "fetched_at": _now_str(),
                "region": "A",
            }
        )
        if len(out) >= limit:
            break
    return out


async def collect_all(client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Gather articles from all configured sources.

    Returns:
        ``(rows, counts)`` where ``counts`` maps every source in
        ``SOURCE_NAMES`` to the rows it returned this round (0 on failure).
    """
    coros = [
        fetch_eastmoney_column(client, col, source=src, region=region)
        for col, src, region in _EM_COLUMNS
    ]
    coros.append(fetch_cls_telegraph(client))
    coros.append(fetch_sina_finance_roll(client))
    batches = await _gather(*coros)
    merged: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for name, batch in zip(SOURCE_NAMES, batches):
        counts[name] = len(batch)
        merged.extend(batch)
    return merged, counts


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
