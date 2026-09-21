"""Near-duplicate headline collapse (洗稿)."""

from __future__ import annotations

import re
from typing import Any


def _norm(title: str) -> str:
    t = re.sub(r"\s+", "", str(title or ""))
    t = re.sub(r"[【】\[\]（）()《》<>\"'：:，,。.!！？?、|｜\-—_]", "", t)
    return t.lower()


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on character bigrams after normalization."""
    aa, bb = _bigrams(_norm(a)), _bigrams(_norm(b))
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, len(aa | bb))


def dedupe_articles(
    rows: list[dict[str, Any]], *, threshold: float = 0.72
) -> tuple[list[dict[str, Any]], int]:
    """Drop near-duplicate titles within one fetch batch. Return kept, dropped."""
    kept: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        title = str(row.get("title") or "")
        dup = False
        for prev in kept:
            if title_similarity(title, str(prev.get("title") or "")) >= threshold:
                dup = True
                break
        if dup:
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped
