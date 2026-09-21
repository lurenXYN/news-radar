"""Match article text against the A-share–first lexicon."""

from __future__ import annotations

from typing import Any

from news_radar.lexicon import BOARD_BK, SECTOR_RULES
from news_radar.sentiment import classify_tone


def match_sectors(title: str, summary: str = "") -> list[dict[str, Any]]:
    """Return unique sector hits with keyword, tone, and weight."""
    text = f"{title or ''}\n{summary or ''}"
    tone = classify_tone(title, summary)
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in SECTOR_RULES:
        sector = str(rule["sector"])
        weight = float(rule.get("weight") or 1.0)
        priority = str(rule.get("priority") or "A")
        if priority == "A":
            weight *= 1.15
        elif priority == "HK":
            weight *= 1.0
        else:
            weight *= 0.85
        weight *= float(tone.get("mult") or 1.0)
        for kw in rule.get("keywords") or []:
            if not kw or kw not in text:
                continue
            key = f"{sector}|{kw}"
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {
                    "sector": sector,
                    "keyword": kw,
                    "weight": round(weight, 3),
                    "etfs": list(rule.get("etfs") or []),
                    "bks": list(rule.get("bks") or BOARD_BK.get(sector) or []),
                    "priority": priority,
                    "tone": tone.get("tone"),
                    "tone_label": tone.get("label"),
                }
            )
    return hits


def etfs_for_sector(sector: str) -> list[str]:
    """Return ETF codes configured for one sector."""
    for rule in SECTOR_RULES:
        if rule.get("sector") == sector:
            return list(rule.get("etfs") or [])
    return []


def bks_for_sector(sector: str) -> list[str]:
    """Return preferred East Money BK codes for one sector."""
    for rule in SECTOR_RULES:
        if rule.get("sector") == sector:
            return list(rule.get("bks") or [])
    return list(BOARD_BK.get(sector) or [])


def action_hint(row: dict[str, Any]) -> str:
    """One soft action line for pre-open checklist (never a buy order)."""
    confirm = str(row.get("confirm") or "")
    tone = str(row.get("tone") or "neutral")
    etfs = row.get("etfs") or []
    etf_s = etfs[0] if etfs else "相关ETF"
    if tone == "bearish":
        return f"偏空催化：只观察，勿追；可盯 {etf_s} 是否弱于大盘"
    if confirm == "resonance":
        return f"开盘看 {etf_s} 高开低走还是站稳；不追尖"
    if confirm == "board_lead":
        return f"盘面已动：回踩再看 {etf_s}，忌追高"
    if confirm == "news_only":
        return f"仅新闻：等盘面确认再动手；先记 {etf_s}"
    if confirm == "diverge":
        return "新闻热但板块弱：优先怀疑洗稿/利空，观望"
    return f"观察名单：对照主线后再看 {etf_s}"
