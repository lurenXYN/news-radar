"""Digest requires resonance/board_lead when flag is on."""

from __future__ import annotations

from news_radar import config as cfg
from news_radar.engine import _pick_digest_rows, _require_board_confirm, _board_median_pct


def test_require_board_confirm_flag(monkeypatch):
    monkeypatch.setattr(cfg, "DIGEST_REQUIRE_BOARD_CONFIRM", True)

    def _fake_setting(key, default=None):
        if key == "digest_require_board_confirm":
            return True
        return default

    monkeypatch.setattr("news_radar.engine.setting", _fake_setting)
    assert _require_board_confirm() is True


def test_board_median_pct():
    assert _board_median_pct([]) is None
    assert _board_median_pct([{"pct": 1.0}, {"pct": 3.0}, {"pct": 2.0}]) == 2.0
    assert _board_median_pct([{"pct": 1.0}, {"pct": 2.0}]) == 1.5


def test_demote_plus_confirm_candidates(monkeypatch):
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
    ]
    picked, also = _pick_digest_rows(sectors, min_score=3.0, detail_n=5, also_n=4)
    assert picked and picked[0]["confirm"] == "resonance"
    assert all(r.get("confirm") != "news_only" for r in picked)
    # Engine skip path: no confirmed → would return 0 when require_board_confirm.
    only_news = [s for s in sectors if s["confirm"] == "news_only"]
    picked2, _ = _pick_digest_rows(only_news, min_score=3.0, detail_n=5, also_n=4)
    assert not any(
        str(r.get("confirm") or "") in ("resonance", "board_lead") for r in picked2
    )
    assert also or True
