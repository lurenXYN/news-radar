"""Backfill missing resonance excess + effect hint gate on excess_n."""

from __future__ import annotations

from news_radar import config as cfg
from news_radar.db import (
    backfill_resonance_excess,
    effect_observe_snapshot,
    init_db,
    save_resonance_outcome,
    upsert_resonance_marks,
)


def _patch(tmp_path, monkeypatch):
    db_path = tmp_path / "radar.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    import news_radar.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "EFFECT_OBSERVE_SINCE", "2026-11-01")
    init_db()


def test_backfill_fills_excess_from_same_day_median(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    upsert_resonance_marks(
        "2026-11-04",
        [
            {"sector": "半导体", "confirm": "resonance", "board_bk": "BK0481", "board_pct": 1.0},
            {"sector": "军工", "confirm": "resonance", "board_bk": "BK0480", "board_pct": 0.5},
            {"sector": "农业", "confirm": "board_lead", "board_bk": "BK0433", "board_pct": 0.2},
        ],
    )
    # Absolute settle only (legacy rows).
    save_resonance_outcome(
        "2026-11-04", "半导体", next_date="2026-11-05", next_board_pct=1.0
    )
    save_resonance_outcome(
        "2026-11-04", "军工", next_date="2026-11-05", next_board_pct=-1.0
    )
    save_resonance_outcome(
        "2026-11-04", "农业", next_date="2026-11-05", next_board_pct=0.5
    )
    n = backfill_resonance_excess()
    assert n == 3
    snap = effect_observe_snapshot(30)
    assert snap["backtest"]["excess_n"] == 3
    # excess_n < 10 → do not surface excess_hit_rate in observe payload
    assert snap["backtest"]["excess_hit_rate"] is None
    assert any("超额样本不足" in h for h in snap["hints"])


def test_charging_maps_to_new_energy_not_baijiu():
    from news_radar.score import match_sectors, primary_sector_names

    title = "国家能源局：2030年我国充电基础设施将超4000万个 支撑超过1.1亿辆电动汽车的充电服务"
    hits = match_sectors(title, "")
    sectors = {h["sector"] for h in hits}
    assert "新能源/锂电" in sectors
    assert "白酒/消费" not in sectors
    assert "新能源/锂电" in primary_sector_names(hits)

    power = match_sectors("国家能源局：用电需预计年均增量将达到6000亿度左右", "")
    ps = {h["sector"] for h in power}
    assert "电力/公用" in ps
    assert "人工智能" not in ps
