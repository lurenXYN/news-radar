"""Near-duplicate headline collapse (洗稿)."""

from __future__ import annotations

import re
from typing import Any, Iterable


def _norm(title: str) -> str:
    t = re.sub(r"\s+", "", str(title or ""))
    t = re.sub(r"[【】\[\]（）()《》<>\"'：:，,。.!！？?、|｜\-—_]", "", t)
    return t.lower()


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _jaccard(aa: set[str], bb: set[str]) -> float:
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, len(aa | bb))


def title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on character bigrams after normalization."""
    return _jaccard(_bigrams(_norm(a)), _bigrams(_norm(b)))


def dedupe_articles(
    rows: list[dict[str, Any]], *, threshold: float = 0.72
) -> tuple[list[dict[str, Any]], int]:
    """Drop near-duplicate titles within one fetch batch. Return kept, dropped."""
    kept: list[dict[str, Any]] = []
    kept_grams: list[set[str]] = []
    dropped = 0
    for row in rows:
        grams = _bigrams(_norm(str(row.get("title") or "")))
        if any(_jaccard(grams, prev) >= threshold for prev in kept_grams):
            dropped += 1
            continue
        kept.append(row)
        kept_grams.append(grams)
    return kept, dropped


def drop_seen_titles(
    rows: list[dict[str, Any]],
    seen_titles: Iterable[str],
    *,
    threshold: float = 0.72,
) -> tuple[list[dict[str, Any]], int]:
    """Drop rows whose title near-duplicates an already stored headline.

    Catches the same story re-listed under a new fingerprint on a later
    refresh (another column, another source, a lightly reworded flash).

    Args:
        rows: New rows of this refresh (already deduped within the batch).
        seen_titles: Headlines stored recently.
        threshold: Bigram Jaccard similarity that counts as the same story.

    Returns:
        ``(kept, dropped)``.
    """
    seen = [g for g in (_bigrams(_norm(t)) for t in seen_titles) if g]
    if not seen:
        return list(rows), 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        grams = _bigrams(_norm(str(row.get("title") or "")))
        if any(_jaccard(grams, prev) >= threshold for prev in seen):
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped
