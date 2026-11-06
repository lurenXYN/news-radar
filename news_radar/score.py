"""Match article text against the A-share–first lexicon."""

from __future__ import annotations

from typing import Any

from news_radar.config import SUMMARY_ONLY_MULT, WEAK_KEYWORD_MULT
from news_radar.lexicon import BOARD_BK, ENTITY_MAP, SECTOR_RULES
from news_radar.sentiment import classify_tone

_CONTEXT_SECTORS = frozenset(str(r["sector"]) for r in SECTOR_RULES if r.get("context"))


def is_context_sector(sector: str) -> bool:
    """True for background buckets (macro / US) kept out of Top ranking."""
    return str(sector or "") in _CONTEXT_SECTORS


def _placement_mult(needle: str, segments: list[tuple[str, float]]) -> float:
    """Return the best segment multiplier where ``needle`` appears (0 if absent)."""
    return max((mult for text, mult in segments if needle in text), default=0.0)


def match_sectors(
    title: str, summary: str = "", tags: list[str] | None = None
) -> list[dict[str, Any]]:
    """Return unique sector hits with keyword, tone, entity, and weight.

    A keyword found in the title or the source tags counts in full; found only
    in the summary it counts at ``SUMMARY_ONLY_MULT``. Rule ``weak`` keywords
    are further scaled by ``WEAK_KEYWORD_MULT`` and rule ``exclude`` contexts
    anywhere in the text drop the keyword.

    Args:
        title: Headline.
        summary: Body digest.
        tags: Source-provided subject / stock names (e.g. CLS subjects); they
            weigh like the title but do not feed the tone classification.
    """
    title = title or ""
    summary = summary or ""
    tag_text = " ".join(tags or [])
    text = f"{title}\n{summary}\n{tag_text}"
    segments = [(title, 1.0), (tag_text, 1.0), (summary, float(SUMMARY_ONLY_MULT))]
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
        excludes = rule.get("exclude") or {}
        weak = set(rule.get("weak") or [])
        for kw in rule.get("keywords") or []:
            if not kw or kw not in text:
                continue
            if any(c in text for c in excludes.get(kw) or []):
                continue
            key = f"{sector}|{kw}"
            if key in seen:
                continue
            seen.add(key)
            mult = _placement_mult(kw, segments)
            if kw in weak:
                mult *= float(WEAK_KEYWORD_MULT)
            hits.append(
                {
                    "sector": sector,
                    "keyword": kw,
                    "weight": round(weight * mult, 3),
                    "etfs": list(rule.get("etfs") or []),
                    "bks": list(rule.get("bks") or BOARD_BK.get(sector) or []),
                    "priority": priority,
                    "tone": tone.get("tone"),
                    "tone_label": tone.get("label"),
                    "via": "keyword",
                }
            )
    for ent in ENTITY_MAP:
        names = list(ent.get("names") or [])
        hit_name = next((n for n in names if n and n in text), None)
        if not hit_name:
            continue
        sector = str(ent.get("sector") or "")
        if not sector:
            continue
        key = f"{sector}|entity:{hit_name}"
        if key in seen:
            continue
        seen.add(key)
        weight = (
            float(ent.get("weight") or 1.2)
            * float(tone.get("mult") or 1.0)
            * _placement_mult(hit_name, segments)
        )
        etfs = etfs_for_sector(sector)
        hits.append(
            {
                "sector": sector,
                "keyword": hit_name,
                "weight": round(weight, 3),
                "etfs": etfs,
                "bks": list(BOARD_BK.get(sector) or []),
                "priority": "A",
                "tone": tone.get("tone"),
                "tone_label": tone.get("label"),
                "via": "entity",
            }
        )
    return hits


def primary_sector_names(
    hits: list[dict[str, Any]], *, limit: int = 3
) -> list[str]:
    """Pick strongest unique sectors for clustering (drop weak tail noise).

    Prefers title/tag hits over summary-only when weights tie. Empty when
    ``hits`` has nothing usable — callers should then skip cluster merge.
    """
    ranked = sorted(
        (h for h in hits if str(h.get("sector") or "").strip()),
        key=lambda h: (
            float(h.get("weight") or 0),
            1 if str(h.get("via") or "") in ("keyword", "entity") else 0,
        ),
        reverse=True,
    )
    out: list[str] = []
    seen: set[str] = set()
    for h in ranked:
        sector = str(h.get("sector") or "").strip()
        if not sector or sector in seen:
            continue
        # Drop very weak summary-only hits when stronger sectors already picked.
        if out and float(h.get("weight") or 0) < 0.55:
            continue
        seen.add(sector)
        out.append(sector)
        if len(out) >= max(1, int(limit)):
            break
    return out


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
