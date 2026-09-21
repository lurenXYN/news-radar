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
    push_cooldown_seconds: int | None = None
    serverchan_enabled: bool | None = None
    serverchan_sendkey: str | None = Field(default=None, description="SCT... SendKey")
    morning_push_only: bool | None = None
    morning_push_min_score: float | None = None
    morning_push_top_n: int | None = None


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
        "sectors": len(snap.get("sectors") or []),
        "watch": len(snap.get("watch") or []),
        "fetched": st.get("fetched"),
        "inserted": st.get("inserted"),
        "deduped": st.get("deduped"),
        "boards": st.get("boards"),
    }


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
    ok = notify_serverchan(
        key,
        "新闻雷达 · 测试推送",
        "这是一条测试消息。若收到，说明 SendKey 配置正确。\n\n> news-radar",
    )
    if not ok:
        raise HTTPException(502, "Server酱 发送失败，请检查 SendKey / 配额")
    return {"ok": True}
