"""Bullish / bearish tone heuristics for news weight soft-adjust."""

from __future__ import annotations

import re
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
    "复苏", "回暖", "政策支持", "补贴", "贴息", "涨停",
)

# Generic words that show up in neutral reporting (statistics, milestones, framework deals).
WEAK_WORDS = frozenset({"下降", "下滑", "调查", "突破", "订单", "签约", "回购"})
WEAK_MULT = 0.5
SUMMARY_MULT = 0.5
MIN_NET = 0.75

# Phrases resolved before single keywords; the matched span is masked afterwards.
_PHRASES: tuple[tuple[str, str | None], ...] = (
    (r"利空出尽", "bull"),
    (r"亏损收窄|减亏|扭亏", "bull"),
    (r"(降幅|跌幅|下滑幅度)[^，。；,;]{0,12}收窄", "bull"),
    (r"(终止|取消|暂停)减持|减持(计划)?(提前)?(终止|取消)", "bull"),
    (r"解除(风险控制|风险警示|处罚|管制|制裁|限制|禁令)", "bull"),
    (r"(制裁|管制|禁令|限制)(被)?(解除|取消|豁免|放宽)", "bull"),
    (r"撤销立案|(结束|终止)调查|复产|摘帽", "bull"),
    (r"(好于|高于|超出)预期", "bull"),
    (r"(不及|低于|逊于|弱于)预期", "bear"),
    (r"(未获|未能获|没有获)(批|准|通过)", "bear"),
    (r"(重组|并购|收购|上市|IPO)(申请)?(被否|终止|失败)", "bear"),
    (r"终止(重组|收购|并购|合作|签约|上市|回购|增持)", "bear"),
    (r"(回购|增持)(计划)?(终止|取消)", "bear"),
    (r"订单(取消|下滑|减少|下降)|砍单", "bear"),
    (r"首亏|预亏|由盈转亏|盈转亏", "bear"),
    (r"(评级|目标价|目标点位|盈利预测)下调|下调[^，。；,;]{0,6}(评级|目标价|目标点位|盈利预测)", "bear"),
    (r"(逆|债券|质押式|买断式)回购|回购(日均|利率|操作)", None),
    (r"(央视|记者|问卷|抽样|市场|专项)调查|调查(显示|问卷|报告|数据)", None),
    (r"获批(解散|注销)", None),
    (r"(利率|收益率|LPR|DR\d{3}|成本|费率)[^。；;]{0,16}(下降|下滑)", None),
)
_PHRASE_RES = tuple((re.compile(p), t) for p, t in _PHRASES)

# A keyword directly preceded by one of these is negated or historical.
_NEGATORS = ("没有", "未能", "尚未", "并未", "暂未", "无法", "难以", "不会", "不再", "不得", "不", "未", "没")
_PAST = ("曾经", "曾")
_MASK = "□"


def _scan(text: str, weight: float) -> tuple[float, float, list[str]]:
    """Score one text field.

    Args:
        text: Title or summary text.
        weight: Placement weight applied to every hit in this field.

    Returns:
        A tuple of (bullish score, bearish score, human-readable hit list).
    """
    bull = bear = 0.0
    hits: list[str] = []
    masked = text or ""
    for rx, tone in _PHRASE_RES:
        first = rx.search(masked)
        if not first:
            continue
        if tone == "bull":
            bull += weight
            hits.append(f"+{first.group(0)}")
        elif tone == "bear":
            bear += weight
            hits.append(f"-{first.group(0)}")
        masked = rx.sub(lambda m: _MASK * len(m.group(0)), masked)

    for kw, side in [(k, "bear") for k in BEARISH] + [(k, "bull") for k in BULLISH]:
        effects: set[str] = set()
        start = masked.find(kw)
        while start >= 0:
            head = masked[:start]
            if head.endswith(_PAST):
                pass
            elif head.endswith(_NEGATORS):
                if side == "bull":
                    effects.add("bear")
            else:
                effects.add(side)
            start = masked.find(kw, start + len(kw))
        w = weight * (WEAK_MULT if kw in WEAK_WORDS else 1.0)
        if "bull" in effects:
            bull += w
            hits.append(f"+{kw}")
        if "bear" in effects:
            bear += w
            hits.append(f"-{kw}" if side == "bear" else f"-否定{kw}")
    return bull, bear, hits


def classify_tone(title: str, summary: str = "") -> dict[str, Any]:
    """Classify a news item as bullish, bearish, or neutral.

    Title hits count fully and summary hits at ``SUMMARY_MULT``; generic words
    in ``WEAK_WORDS`` count at ``WEAK_MULT``. Reversal phrases (e.g. losses
    narrowing, missed expectations) and negated keywords are resolved before
    plain keyword counting. The net score must reach ``MIN_NET`` to leave
    neutral, so one incidental word in a long summary cannot flip the tone.

    Args:
        title: News headline.
        summary: Optional body excerpt.

    Returns:
        Dict with ``tone``, ``label``, ``mult`` (scoring multiplier),
        ``net`` (bullish minus bearish score) and ``hits``.
    """
    b1, s1, h1 = _scan(title or "", 1.0)
    b2, s2, h2 = _scan(summary or "", SUMMARY_MULT)
    net = round((b1 + b2) - (s1 + s2), 3)
    hits = h1 + [f"摘要{h}" for h in h2]
    if net <= -MIN_NET:
        return {"tone": "bearish", "label": "偏空", "mult": 0.45, "net": net, "hits": hits}
    if net >= MIN_NET:
        return {"tone": "bullish", "label": "偏多", "mult": 1.15, "net": net, "hits": hits}
    return {"tone": "neutral", "label": "中性", "mult": 1.0, "net": net, "hits": hits}
