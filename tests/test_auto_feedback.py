"""Auto push feedback from same-day ETF / board moves."""

from __future__ import annotations

from news_radar import config as cfg
from news_radar.auto_feedback import (
    auto_label_unmarked_pushes,
    parse_push_etf_codes,
    parse_push_sectors,
    score_push_day_move,
)
from news_radar.db import feedback_summary, init_db, log_push, set_push_feedback


def test_parse_sectors_and_etfs_from_digest():
    desp = (
        "## 1. 半导体 · 共振\n"
        "- 盘面 `+1.20%`\n"
        "- ETF：512480 / 159995\n"
        "## 其余留意\n"
        "- **人工智能** · 盘面 -0.5% · `159819`\n"
    )
    assert "半导体" in parse_push_sectors(desp)
    assert "人工智能" in parse_push_sectors(desp)
    assert "512480" in parse_push_etf_codes(desp)
    assert "159819" in parse_push_etf_codes(desp)


def test_score_uses_etf_pct(monkeypatch):
    monkeypatch.setattr(
        "news_radar.auto_feedback.fetch_etf_day_pct",
        lambda code, day, client=None: {"512480": 1.2, "159995": 0.8}.get(code),
    )
    out = score_push_day_move(
        {
            "created_at": "2026-11-06 09:05:00",
            "title": "盘前",
            "desp": "## 1. 半导体\n- ETF：512480 / 159995\n",
        }
    )
    assert out["label"] == "useful"
    assert out["avg_pct"] == 1.0
    assert out["reason"] == "etf_day"


def test_score_useless_and_board_fallback(monkeypatch):
    monkeypatch.setattr(
        "news_radar.auto_feedback.fetch_etf_day_pct",
        lambda code, day, client=None: None,
    )
    monkeypatch.setattr(
        "news_radar.auto_feedback._board_pct_for_sector",
        lambda day, sector: -1.5 if sector == "半导体" else None,
    )
    out = score_push_day_move(
        {
            "created_at": "2026-11-06 09:05:00",
            "desp": "## 1. 半导体 · 共振\n",
        }
    )
    assert out["label"] == "useless"
    assert out["reason"] == "board_day"


def test_auto_label_keeps_hand_marks(tmp_path, monkeypatch):
    db_path = tmp_path / "radar.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    import news_radar.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "EFFECT_OBSERVE_SINCE", "2026-11-01")
    init_db()

    hand = log_push(
        "digest:morning:2026-11-05",
        "盘前",
        desp="## 1. 半导体\n- ETF：512480\n",
        ok=True,
        kind="morning",
    )
    auto = log_push(
        "digest:midday:2026-11-05",
        "盘中",
        desp="## 1. 半导体\n- ETF：512480\n",
        ok=True,
        kind="midday",
    )
    assert hand and auto
    set_push_feedback(hand, "useless", src="hand")

    monkeypatch.setattr(
        "news_radar.auto_feedback.fetch_etf_day_pct",
        lambda code, day, client=None: 2.0,
    )
    out = auto_label_unmarked_pushes(since="2026-11-01", dry_run=False)
    assert out["useful"] >= 1
    assert out["kept_hand"] >= 1
    fb = feedback_summary(since="2026-11-01")
    assert fb["useful"] + fb["useless"] >= 2
    from news_radar.db import get_push_log

    assert get_push_log(hand)["feedback"] == "useless"
    assert get_push_log(hand)["feedback_src"] == "hand"
    assert get_push_log(auto)["feedback"] == "useful"
    assert get_push_log(auto)["feedback_src"] == "etf_day"
