"""Near-duplicate headline collapse (洗稿) and same-story event clustering."""

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


def assign_cluster(
    title: str,
    sectors: Iterable[str],
    recent: list[dict[str, Any]],
    *,
    threshold: float = 0.45,
) -> int | None:
    """Return an existing cluster id to join, or None to create a new cluster.

    A candidate must share at least one sector with ``sectors`` (or both must
    have an empty sector set) and clear the title similarity threshold. Among
    matches, the highest similarity wins (ties → newest / first in list).

    Args:
        title: Headline of the new article.
        sectors: Sector names hit by the article.
        recent: Cluster dicts with ``id``, ``title``, and ``sectors`` (iterable).
        threshold: Bigram Jaccard floor for joining (lower than wash-稿 dedupe).

    Returns:
        Existing ``cluster_id``, or ``None`` when no suitable cluster exists.
    """
    sec = {str(x).strip() for x in sectors if str(x).strip()}
    grams = _bigrams(_norm(title))
    if not grams:
        return None
    best_id: int | None = None
    best_sim = -1.0
    for row in recent:
        try:
            cid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        other = {str(x).strip() for x in (row.get("sectors") or []) if str(x).strip()}
        if sec and other and not (sec & other):
            continue
        if not sec and other:
            # Unmapped article should not join a mapped cluster.
            continue
        sim = _jaccard(grams, _bigrams(_norm(str(row.get("title") or ""))))
        if sim >= threshold and sim > best_sim:
            best_sim = sim
            best_id = cid
    return best_id
