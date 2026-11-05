"""Digest / export ranking: news_only must not outrank resonance."""

from __future__ import annotations

from news_radar import config as cfg
from news_radar.engine import _pick_digest_rows, _rank_key


def test_rank_key_confirm_order():
    news = {"confirm": "news_only", "delta": 9.0, "score": 99.0, "board_pct": 0.0}
    reso = {"confirm": "resonance", "delta": 0.0, "score": 1.0, "board_pct": 0.5}
    lead = {"confirm": "board_lead", "delta": 0.0, "score": 1.0, "board_pct": 2.0}
    div = {"confirm": "diverge", "delta": 5.0, "score": 50.0, "board_pct": -1.0}
    assert _rank_key(reso) > _rank_key(lead) > _rank_key(div) > _rank_key(news)


def test_pick_digest_demotes_news_only(monkeypatch):
    monkeypatch.setattr(cfg, "DIGEST_DEMOTE_NEWS_ONLY", True)

    def _fake_setting(key, default=None):
        if key == "digest_demote_news_only":
            return True
        if key == "sector_blacklist":
            return ""
        return default

    monkeypatch.setattr("news_radar.engine.setting", _fake_setting)

    sectors = [
        {
            "sector": "白酒/消费",
            "confirm": "news_only",
            "score": 40.0,
            "delta": 8.0,
            "board_pct": 0.1,
            "rising": True,
        },
        {
            "sector": "半导体",
            "confirm": "resonance",
            "score": 5.0,
            "delta": 1.0,
            "board_pct": 1.2,
            "rising": True,
        },
        {
            "sector": "军工",
            "confirm": "board_lead",
            "score": 4.0,
            "delta": 0.5,
            "board_pct": 2.0,
            "rising": False,
        },
        {
            "sector": "煤炭",
            "confirm": "news_only",
            "score": 30.0,
            "delta": 6.0,
            "board_pct": 0.0,
            "rising": True,
        },
    ]
    picked, also = _pick_digest_rows(
        sectors, min_score=3.0, detail_n=5, also_n=4
    )
    assert [r["sector"] for r in picked] == ["半导体", "军工"]
    assert all(r.get("confirm") != "news_only" for r in picked)
    assert {r["sector"] for r in also} >= {"白酒/消费", "煤炭"}


def test_pick_digest_without_demote_allows_news_only_top(monkeypatch):
    monkeypatch.setattr(cfg, "DIGEST_DEMOTE_NEWS_ONLY", False)

    def _fake_setting(key, default=None):
        if key == "digest_demote_news_only":
            return False
        if key == "sector_blacklist":
            return ""
        return default

    monkeypatch.setattr("news_radar.engine.setting", _fake_setting)

    sectors = [
        {
            "sector": "白酒/消费",
            "confirm": "news_only",
            "score": 40.0,
            "delta": 8.0,
            "board_pct": 0.1,
            "rising": True,
        },
        {
            "sector": "半导体",
            "confirm": "resonance",
            "score": 5.0,
            "delta": 1.0,
            "board_pct": 1.2,
            "rising": True,
        },
    ]
    picked, _also = _pick_digest_rows(
        sectors, min_score=3.0, detail_n=2, also_n=0
    )
    # Without demote, higher score+delta news_only can still sit in Top after
    # confirm-tier sort (resonance still wins first slot).
    assert picked[0]["confirm"] == "resonance"
    assert any(r.get("confirm") == "news_only" for r in picked)
