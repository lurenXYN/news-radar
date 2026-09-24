"""FastAPI app for news-radar."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from news_radar.config import STATIC_DIR
from news_radar.engine import engine
from news_radar.settings import get_settings, masked_settings, update_settings


class SettingsIn(BaseModel):
    """Patchable runtime knobs."""

    refresh_seconds: int | None = None
    heat_window_hours: int | None = None
    push_score_min: float | None = None
    serverchan_enabled: bool | None = None
    serverchan_sendkey: str | None = Field(default=None, description="SCT... SendKey")
    morning_push_min_score: float | None = None
    morning_push_top_n: int | None = None
    push_daily_max: int | None = None
    sector_blacklist: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start refresh loop; wait briefly for first snapshot."""
    engine.start()
    for _ in range(80):
        if engine.snapshot.get("updated_at"):
            break
        await asyncio.sleep(0.25)
    yield
    await engine.stop()


app = FastAPI(title="新闻雷达 news-radar", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    """Serve the dashboard page."""
    return FileResponse(Path(STATIC_DIR) / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness probe with light snapshot stats for desk status dots."""
    snap = engine.snapshot or {}
    st = snap.get("stats") or {}
    return {
        "ok": True,
        "updated_at": snap.get("updated_at"),
        "trading_day": snap.get("trading_day"),
        "sectors": len(snap.get("sectors") or []),
        "watch": len(snap.get("watch") or []),
        "fetched": st.get("fetched"),
        "inserted": st.get("inserted"),
        "deduped": st.get("deduped"),
        "boards": st.get("boards"),
    }


@app.get("/api/push/status")
def push_status() -> dict[str, Any]:
    """Push self-check: schedule windows, recent log, resonance backtest."""
    return engine.push_status()


@app.get("/api/push/history")
def push_history(
    kind: str = Query(default=""),
    day_from: str = Query(default=""),
    day_to: str = Query(default=""),
    ok: str = Query(default=""),
    q: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    """Query Server酱 push history with filters."""
    return engine.query_history(
        kind=kind,
        day_from=day_from,
        day_to=day_to,
        ok=ok,
        q=q,
        offset=offset,
        limit=limit,
    )


@app.get("/api/push/history/{push_id}")
def push_history_one(push_id: int) -> dict[str, Any]:
    """Return one push including full body."""
    from news_radar.db import get_push_log

    row = get_push_log(push_id)
    if not row:
        raise HTTPException(404, "not found")
    return {"ok": True, "row": row}


class PushFeedbackIn(BaseModel):
    """Mark a historical push as useful / useless."""

    feedback: str = Field(description="useful | useless | empty to clear")


@app.post("/api/push/history/{push_id}/feedback")
def push_feedback(push_id: int, body: PushFeedbackIn) -> dict[str, Any]:
    """Record user feedback on a push."""
    from news_radar.db import set_push_feedback

    if not set_push_feedback(push_id, body.feedback):
        raise HTTPException(400, "invalid feedback or missing row")
    return {"ok": True}


@app.get("/api/backtest/resonance")
def backtest_resonance(days: int = Query(default=30, ge=5, le=120)) -> dict[str, Any]:
    """Resonance → next-day board move summary."""
    from news_radar.db import resonance_backtest_summary

    return resonance_backtest_summary(days)


@app.get("/api/snapshot")
def snapshot() -> JSONResponse:
    """Latest sectors + articles."""
    return JSONResponse(engine.snapshot)


@app.get("/api/export/sectors")
def export_sectors(limit: int = Query(default=8, ge=1, le=30)) -> dict[str, Any]:
    """Compact sector watchlist for 牛来 / external soft integration."""
    return engine.export_sectors(limit=limit)


@app.post("/api/refresh")
async def refresh_now() -> dict[str, Any]:
    """Force one collection round."""
    snap = await engine.refresh()
    return {"ok": True, "stats": snap.get("stats"), "updated_at": snap.get("updated_at")}


@app.get("/api/settings")
def settings_get() -> dict[str, Any]:
    """Return settings with SendKey masked."""
    return masked_settings()


@app.post("/api/settings")
def settings_post(body: SettingsIn) -> dict[str, Any]:
    """Update settings. Empty sendkey string means leave unchanged."""
    patch = body.model_dump(exclude_none=True)
    if "serverchan_sendkey" in patch and not str(patch["serverchan_sendkey"]).strip():
        patch.pop("serverchan_sendkey")
    update_settings(patch)
    return {"ok": True, "settings": masked_settings()}


@app.post("/api/settings/test-push")
def test_push() -> dict[str, Any]:
    """Send a test Server酱 message with current SendKey."""
    from news_radar.notify import notify_serverchan

    s = get_settings(refresh=True)
    key = str(s.get("serverchan_sendkey") or "").strip()
    if not key:
        raise HTTPException(400, "未配置 Server酱 SendKey")
    result = notify_serverchan(
        key,
        "新闻雷达 · 测试推送",
        "这是一条测试消息。若收到，说明 SendKey 配置正确。\n\n> news-radar",
    )
    from news_radar.db import log_push

    log_push(
        "alert:test",
        "新闻雷达 · 测试推送",
        kind="alert",
        ok=bool(result.get("ok")),
        desp="测试推送",
        error=str(result.get("error") or ""),
    )
    if not result.get("ok"):
        raise HTTPException(502, f"Server酱 发送失败：{result.get('error') or '未知错误'}")
    return {"ok": True}
