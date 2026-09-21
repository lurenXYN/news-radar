"""Display-time theme clustering for near-duplicate sectors."""

from __future__ import annotations

from typing import Any

# First matching group wins; sectors share one Top-N slot in digests / UI.
THEME_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("半导体链", ("半导体",)),
    ("算力/AI", ("人工智能", "通信")),
    ("新能源链", ("新能源/锂电",)),
    ("消费", ("白酒/消费",)),
    ("金融", ("银行", "证券", "红利/高股息")),
    ("周期资源", ("煤炭", "有色/贵金属", "石油石化")),
    ("制造/军工", ("军工",)),
    ("医药", ("创新药/医药",)),
    ("地产链", ("房地产",)),
    ("农业", ("农业",)),
    ("公用", ("电力/公用",)),
    ("海外映射", ("港股科技映射", "美股映射/风险偏好", "大盘/宏观")),
]


def theme_of(sector: str) -> str:
    """Return theme cluster name for a sector (or the sector itself)."""
    s = str(sector or "")
    for name, members in THEME_GROUPS:
        if s in members:
            return name
    return s or "其他"


def merge_by_theme(rows: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Keep highest-ranked row per theme; annotate theme on each kept row."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        theme = theme_of(str(row.get("sector") or ""))
        if theme in seen:
            continue
        seen.add(theme)
        item = dict(row)
        item["theme"] = theme
        out.append(item)
        if len(out) >= max(1, limit):
            break
    return out
