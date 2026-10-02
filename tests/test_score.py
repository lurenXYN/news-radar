"""Sector matching precision: placement weight, excludes, weak words, background buckets."""

from __future__ import annotations

import pytest

from news_radar.notify import format_macro_section
from news_radar.score import is_context_sector, match_sectors


def _w(hits, sector, kw=None):
    return next(h["weight"] for h in hits if h["sector"] == sector and (kw is None or h["keyword"] == kw))


def test_summary_only_hit_counts_half():
    in_title = match_sectors("前三季度光伏装机增长", "")
    in_summary = match_sectors("能源局发布数据", "前三季度光伏装机增长")
    assert _w(in_summary, "新能源/锂电") * 2 == pytest.approx(_w(in_title, "新能源/锂电"), abs=0.002)


def test_tags_weigh_like_title():
    title = match_sectors("半导体设备订单回暖", "")
    tagged = match_sectors("设备订单回暖", "", ["半导体"])
    assert _w(tagged, "半导体") == _w(title, "半导体")


def test_exclude_context_drops_keyword():
    assert not any(h["sector"] == "军工" for h in match_sectors("美国航空推出里程购票功能"))
    assert not any(h["sector"] == "银行" for h in match_sectors("高盛投资银行部门裁员"))
    assert not any(h["sector"] == "有色/贵金属" for h in match_sectors("锂电池快充新标尺"))
    assert not any(h["sector"] == "有色/贵金属" for h in match_sectors("国庆黄金周出游人次创新高"))
    assert any(h["sector"] == "军工" for h in match_sectors("航空发动机新型号完成试车"))
    assert any(h["sector"] == "有色/贵金属" for h in match_sectors("碳酸锂期货涨停 锂价反弹"))


def test_weak_keyword_scaled():
    weak = match_sectors("十一消费数据亮眼", "")
    strong = match_sectors("十一白酒数据亮眼", "")
    assert _w(weak, "白酒/消费", "消费") * 2 == pytest.approx(_w(strong, "白酒/消费", "白酒"), abs=0.002)


def test_generic_carrier_words_removed():
    assert not any(h["sector"] == "通信" for h in match_sectors("推动移动支付便利化"))
    assert any(h["sector"] == "通信" for h in match_sectors("中国移动发布算力网络规划"))


def test_context_sectors_and_macro_section():
    assert is_context_sector("大盘/宏观") and is_context_sector("美股映射/风险偏好")
    assert not is_context_sector("半导体") and not is_context_sector("港股科技映射")
    lines = format_macro_section([
        {"sector": "大盘/宏观", "score": 12.3, "delta": 4.0, "keywords": "美联储,非农",
         "articles": [{"title": "美国9月非农不及预期"}]},
    ])
    assert lines[0].startswith("## 宏观与外盘")
    assert "**大盘/宏观** · 热度 12.3 · 相对 +4.0 · 美联储 / 非农" in lines[1]
    assert "最新：美国9月非农不及预期" in lines[1]
    assert format_macro_section([]) == []
