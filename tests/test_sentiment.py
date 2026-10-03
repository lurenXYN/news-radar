"""Tone classification: reversal phrases, negation, weak words, summary weight."""

from __future__ import annotations

import pytest

from news_radar.sentiment import classify_tone


def _tone(title, summary=""):
    return classify_tone(title, summary)["tone"]


@pytest.mark.parametrize(
    "title",
    [
        "某公司利空出尽 股价企稳",
        "某公司三季度亏损收窄",
        "前8月商品房销售面积降幅连续6个月收窄",
        "某公司终止减持计划",
        "药监局解除风险控制措施 生产线复产",
    ],
)
def test_reversal_phrases_are_bullish(title):
    assert _tone(title) == "bullish"


@pytest.mark.parametrize(
    "title",
    [
        "某公司三季度营收不及预期",
        "某创新药未获批上市",
        "某公司终止签约 订单取消",
        "某公司重组被否",
        "机构下调某公司目标价",
    ],
)
def test_reversal_phrases_are_bearish(title):
    assert _tone(title) == "bearish"


def test_negated_bearish_word_is_dropped():
    assert _tone("央企带头不违约拖欠") == "neutral"


def test_historical_keyword_is_dropped():
    assert _tone("曾暴涨300%的新股上演过山车") == "neutral"


@pytest.mark.parametrize(
    "title",
    [
        "央行开展1650亿元7天期逆回购操作",
        "银行间市场债券回购日均成交6.5万亿元",
        "央视调查：食品背书证书乱象",
        "8月DR001加权平均利率为1.38%，环比下降1个基点",
    ],
)
def test_money_market_and_reporting_terms_are_neutral(title):
    assert _tone(title) == "neutral"


def test_single_weak_word_in_title_stays_neutral():
    assert _tone("被动指数型债基规模突破2万亿") == "neutral"


def test_one_summary_keyword_cannot_flip_tone():
    assert _tone("广东前8月社会消费品零售总额同比增长1.3%", "房地产开发投资下降20.9%") == "neutral"


def test_strong_title_keyword_still_counts():
    assert _tone("美联储官员呼吁进一步加息") == "bearish"
    assert _tone("A股龙头突发利好") == "bullish"
