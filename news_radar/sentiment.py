"""Bullish / bearish tone heuristics for news weight soft-adjust."""

from __future__ import annotations

from typing import Any

BEARISH = (
    "制裁", "管制", "禁令", "实体清单", "暴雷", "违约", "爆仓", "下滑", "下降",
    "亏损", "裁员", "调查", "处罚", "立案", "退市", "爆雷", "造假", "减持",
    "跌停", "大跌", "暴跌", "跳水", "利空", "风险警示", "停产", "召回",
    "战争", "冲突升级", "加息", "紧缩",
)

BULLISH = (
    "降息", "降准", "刺激", "利好", "突破", "创新高", "大涨", "暴涨",
    "获批", "中标", "签约", "订单", "扩产", "回购", "增持", "超预期",
    "复苏", "回暖", "政策支持", "补贴",
)


def classify_tone(title: str, summary: str = "") -> dict[str, Any]:
    """Return tone label and weight multiplier for scoring."""
    text = f"{title or ''} {summary or ''}"
    bear = sum(1 for k in BEARISH if k in text)
    bull = sum(1 for k in BULLISH if k in text)
    if bear > bull and bear > 0:
        return {"tone": "bearish", "label": "偏空", "mult": 0.45}
    if bull > bear and bull > 0:
        return {"tone": "bullish", "label": "偏多", "mult": 1.15}
    return {"tone": "neutral", "label": "中性", "mult": 1.0}
