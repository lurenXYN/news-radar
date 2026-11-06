"""Excess backfill must run even when settle early-returns."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

from news_radar import config as cfg
from news_radar.db import (
    backfill_resonance_excess,
    init_db,
    save_resonance_outcome,
)
from news_radar.engine import RadarEngine


def _patch(tmp_path, monkeypatch):
    db_path = tmp_path / "radar.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    import news_radar.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    init_db()


def test_settle_backfills_when_not_trading_day(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    save_resonance_outcome(
        "2026-11-04", "半导体", next_date="2026-11-05", next_board_pct=1.0
    )
    save_resonance_outcome(
        "2026-11-04", "军工", next_date="2026-11-05", next_board_pct=-1.0
    )
    eng = RadarEngine()
    monkeypatch.setattr("news_radar.engine.is_trading_day", lambda _now: False)
    eng._settle_resonance([], now=datetime(2026, 11, 8, 12, 0, 0))
    # Already filled during settle; second call is a no-op.
    assert backfill_resonance_excess() == 0


def test_startup_runs_excess_backfill(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    save_resonance_outcome(
        "2026-11-04", "半导体", next_date="2026-11-05", next_board_pct=3.0
    )
    save_resonance_outcome(
        "2026-11-04", "军工", next_date="2026-11-05", next_board_pct=1.0
    )
    eng = RadarEngine()

    def _fake_create_task(coro, name=None):  # noqa: ARG001
        if hasattr(coro, "close"):
            coro.close()
        m = MagicMock()
        m.done = lambda: True
        return m

    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)
    eng.start()
    assert backfill_resonance_excess() == 0
