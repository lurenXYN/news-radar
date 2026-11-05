"""Effect-observe snapshot: feedback counts + soft hints (no network)."""

from __future__ import annotations

from news_radar import config as cfg
from news_radar.db import (
    effect_observe_snapshot,
    feedback_summary,
    init_db,
    log_push,
    set_push_feedback,
)


def test_feedback_and_effect_snapshot(tmp_path, monkeypatch):
    db_path = tmp_path / "radar.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    # db.py binds DB_PATH at import time — patch the module copy too.
    import news_radar.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "EFFECT_OBSERVE_SINCE", "2026-11-01")
    monkeypatch.setattr(cfg, "EFFECT_OBSERVE_DAYS", 7)
    init_db()

    a = log_push("digest:morning:2026-11-05", "盘前", desp="body", ok=True, kind="morning")
    b = log_push("digest:midday:2026-11-05", "盘中", desp="body", ok=True, kind="midday")
    log_push("digest:evening:2026-11-05", "晚间", desp="body", ok=True, kind="evening")
    assert a and b
    set_push_feedback(a, "useful")
    set_push_feedback(b, "useless")

    fb = feedback_summary(since="2026-11-01")
    assert fb["useful"] == 1
    assert fb["useless"] == 1
    assert fb["unmarked"] == 1
    assert fb["useful_rate"] == 50.0

    snap = effect_observe_snapshot(30)
    assert snap["since"] == "2026-11-01"
    assert snap["feedback"]["labeled"] == 2
    assert isinstance(snap["hints"], list)
    assert "观察" in (snap.get("note") or "")
