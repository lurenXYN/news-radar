"""Match article text against the A-share–first lexicon."""

from __future__ import annotations

from typing import Any

from news_radar.lexicon import SECTOR_RULES


def match_sectors(title: str, summary: str = "") -> list[dict[str, Any]]:
    """Return unique sector hits with keyword and weight (A priority boost)."""
    text = f"{title or ''}\n{summary or ''}"
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in SECTOR_RULES:
        sector = str(rule["sector"])
        weight = float(rule.get("weight") or 1.0)
        priority = str(rule.get("priority") or "A")
        # Prefer A-share transmission channels in ranking.
        if priority == "A":
            weight *= 1.15
        elif priority == "HK":
            weight *= 1.0
        else:
            weight *= 0.85
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
                    "priority": priority,
                }
            )
            # One keyword per sector is enough for linking; keep scanning for more kws.
    return hits


def etfs_for_sector(sector: str) -> list[str]:
    """Return ETF codes configured for one sector."""
    for rule in SECTOR_RULES:
        if rule.get("sector") == sector:
            return list(rule.get("etfs") or [])
    return []
