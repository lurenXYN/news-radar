"""Server酱 push — same SCT API pattern as market-desk / 牛来-作战台."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("news_radar.notify")


def notify_serverchan(sendkey: str, title: str, desp: str) -> dict[str, Any]:
    """POST one message to Server酱³. Return ``{ok, error}``."""
    key = str(sendkey or "").strip()
    if not key:
        return {"ok": False, "error": "empty sendkey"}
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
                msg = str(data.get("message") or raw[:120])
                log.warning("serverchan reject: %s", msg)
                return {"ok": False, "error": msg}
        except json.JSONDecodeError:
            pass
        return {"ok": True, "error": ""}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("serverchan failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def format_sector_push(
    sector: str,
    score: float,
    articles: list[dict[str, Any]],
    *,
    etfs: list[str] | None = None,
    confirm_label: str = "",
    board_pct: float | None = None,
    delta: float | None = None,
) -> tuple[str, str]:
    """Build Server酱 title + markdown body for one hot sector."""
    tag = f" · {confirm_label}" if confirm_label else ""
    title = f"板块观察 · {sector}（热度 {score:.1f}{tag}）"
    lines = [
        f"## {sector}",
        f"- 热度分：`{score:.1f}`",
    ]
    if delta is not None:
        lines.append(f"- 相对热度：`{delta:+.1f}`（较上一窗口）")
    if board_pct is not None:
        lines.append(f"- 盘面：`{board_pct:+.2f}%`" + (f" · {confirm_label}" if confirm_label else ""))
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


def format_morning_digest(sectors: list[dict[str, Any]], *, as_of: str) -> tuple[str, str]:
    """Build one morning Server酱 digest for Top-N watch sectors."""
    return format_watch_digest(
        sectors,
        as_of=as_of,
        title_prefix="新闻雷达 · 盘前观察",
        heading="盘前板块观察",
        tip="优先看 **共振 / 盘面已动**；「仅新闻」只观察不追。",
    )


def format_watch_digest(
    sectors: list[dict[str, Any]],
    *,
    as_of: str,
    title_prefix: str = "新闻雷达 · 板块观察",
    heading: str = "板块观察汇总",
    tip: str = "优先看 **共振 / 盘面已动**；合并推送，避免刷屏。",
    extra_sections: list[str] | None = None,
) -> tuple[str, str]:
    """Build one Server酱 digest covering multiple sectors (merged push)."""
    day = as_of[:10] if as_of else ""
    n = len(sectors)
    title = f"{title_prefix} {day} · Top{n}".strip()
    lines = [
        f"# {heading}",
        f"_更新于 {as_of or '—'}_",
        "",
        tip,
        "",
    ]
    for i, row in enumerate(sectors, 1):
        sector = str(row.get("sector") or "")
        theme = str(row.get("theme") or "")
        score = float(row.get("score") or 0)
        delta = float(row.get("delta") or 0)
        label = str(row.get("confirm_label") or row.get("label") or "")
        tone = str(row.get("tone_label") or "")
        pct = row.get("board_pct")
        etfs = row.get("etfs") or []
        hint = str(row.get("action_hint") or "").strip()
        pct_s = "—" if pct is None else f"{float(pct):+.2f}%"
        head = f"## {i}. {sector}"
        if theme and theme != sector:
            head += f"（{theme}）"
        if label:
            head += f" · {label}"
        if tone and tone != "中性":
            head += f" · {tone}"
        lines.append(head)
        lines.append(f"- 热度 `{score:.1f}` · 相对 `{delta:+.1f}` · 盘面 `{pct_s}`")
        if row.get("bk_warn"):
            lines.append("- ⚠ BK 未精确命中，名称模糊匹配")
        if etfs:
            lines.append(f"- ETF：{' / '.join(str(x) for x in etfs[:3])}")
        if hint:
            lines.append(f"- 动作：{hint}")
        arts = row.get("articles") or []
        for a in arts[:2]:
            t = str(a.get("title") or "").strip()
            u = str(a.get("url") or "").strip()
            if u:
                lines.append(f"- [{t}]({u})")
            elif t:
                lines.append(f"- {t}")
        lines.append("")
    if extra_sections:
        lines.extend(extra_sections)
        lines.append("")
    lines.append("---")
    lines.append("_news-radar · 软提示，不构成投资建议_")
    return title, "\n".join(lines)


def format_change_brief(
    changes: list[dict[str, Any]], *, as_of: str
) -> tuple[str, str]:
    """Build a short trading-hours change brief (not a full digest)."""
    n = len(changes)
    title = f"新闻雷达 · 本小时变化 {n}"
    lines = [
        "# 交易时段变化简报",
        f"_更新于 {as_of or '—'}_",
        "",
        "仅列出相对上次观察有变化的板块（有变化才推 · ≥30 分钟冷却）。",
        "",
    ]
    for i, row in enumerate(changes, 1):
        sector = str(row.get("sector") or "")
        reason = str(row.get("change_reason") or "有变化")
        label = str(row.get("confirm_label") or row.get("label") or "")
        score = float(row.get("score") or 0)
        delta = float(row.get("delta") or 0)
        pct = row.get("board_pct")
        pct_s = "—" if pct is None else f"{float(pct):+.2f}%"
        lines.append(f"## {i}. {sector}" + (f" · {label}" if label else ""))
        lines.append(f"- 变化：{reason}")
        lines.append(f"- 热度 `{score:.1f}` · 相对 `{delta:+.1f}` · 盘面 `{pct_s}`")
        etfs = row.get("etfs") or []
        if etfs:
            lines.append(f"- ETF：{' / '.join(str(x) for x in etfs[:2])}")
        lines.append("")
    lines.append("---")
    lines.append("_news-radar · 软提示，不构成投资建议_")
    return title, "\n".join(lines)


def format_overnight_sections(hints: list[dict[str, Any]]) -> list[str]:
    """Split overnight cues into macro / US / commodity style sections."""
    if not hints:
        return []
    buckets = {
        "宏观/利率": [],
        "美股/情绪": [],
        "商品": [],
        "其他传导": [],
    }
    for h in hints:
        sector = str(h.get("sector") or "")
        note = str(h.get("note") or "")
        etf = (h.get("etfs") or [""])[0]
        line = f"- **{sector}**：{note}" + (f" · ETF `{etf}`" if etf else "")
        if sector in ("大盘/宏观",):
            buckets["宏观/利率"].append(line)
        elif sector in ("美股映射/风险偏好", "港股科技映射", "半导体", "人工智能"):
            buckets["美股/情绪"].append(line)
        elif sector in ("石油石化", "有色/贵金属", "煤炭"):
            buckets["商品"].append(line)
        else:
            buckets["其他传导"].append(line)
    out = ["## 隔夜/全球 → A 股传导"]
    for title, lines in buckets.items():
        if not lines:
            continue
        out.append(f"### {title}")
        out.extend(lines)
    out.append("")
    return out
