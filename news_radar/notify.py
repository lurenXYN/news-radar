"""Server酱 push — same SCT API pattern as market-desk / 牛来-作战台."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("news_radar.notify")


def notify_serverchan(sendkey: str, title: str, desp: str) -> bool:
    """POST one message to Server酱³. Return True on HTTP success."""
    key = str(sendkey or "").strip()
    if not key:
        return False
    url = f"https://sctapi.ftqq.com/{urllib.parse.quote(key)}.send"
    payload = urllib.parse.urlencode(
        {
            "title": str(title or "新闻雷达")[:100],
            "desp": str(desp or "")[:4000],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("code") not in (0, "0", None):
                log.warning("serverchan reject: %s", data.get("message") or raw[:120])
                return False
        except json.JSONDecodeError:
            pass
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("serverchan failed: %s", exc)
        return False


def format_sector_push(
    sector: str,
    score: float,
    articles: list[dict[str, Any]],
    *,
    etfs: list[str] | None = None,
) -> tuple[str, str]:
    """Build Server酱 title + markdown body for one hot sector."""
    title = f"板块观察 · {sector}（热度 {score:.1f}）"
    lines = [
        f"## {sector}",
        f"- 热度分：`{score:.1f}`",
    ]
    if etfs:
        lines.append(f"- 相关 ETF：{' / '.join(etfs)}")
    lines.append("")
    lines.append("### 近期相关新闻")
    for a in articles[:6]:
        t = str(a.get("title") or "").strip()
        u = str(a.get("url") or "").strip()
        src = str(a.get("source") or "").strip()
        if u:
            lines.append(f"- [{t}]({u})" + (f" · {src}" if src else ""))
        else:
            lines.append(f"- {t}" + (f" · {src}" if src else ""))
    lines.extend(
        [
            "",
            "> 仅供观察，不构成投资建议。全球催化优先映射大 A 板块。",
        ]
    )
    return title, "\n".join(lines)
