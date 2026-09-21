"""Runtime settings with defaults from config (market-desk style)."""

from __future__ import annotations

import os
from typing import Any

from news_radar import config as cfg
from news_radar.db import load_setting, save_setting

_CACHE: dict[str, Any] | None = None

_DEFAULTS: dict[str, Any] = {
    "refresh_seconds": int(cfg.REFRESH_SECONDS),
    "heat_window_hours": int(cfg.HEAT_WINDOW_HOURS),
    "push_score_min": float(cfg.PUSH_SCORE_MIN),
    "push_cooldown_seconds": int(cfg.PUSH_COOLDOWN_SECONDS),
    "digest_gap_seconds": int(cfg.DIGEST_GAP_SECONDS),
    "push_daily_max": int(cfg.PUSH_DAILY_MAX),
    "serverchan_enabled": bool(cfg.SERVERCHAN_ENABLED),
    "serverchan_sendkey": str(cfg.SERVERCHAN_SENDKEY or ""),
    "llm_enabled": bool(cfg.LLM_ENABLED),
    "morning_push_min_score": float(cfg.MORNING_PUSH_MIN_SCORE),
    "morning_push_top_n": int(cfg.MORNING_PUSH_TOP_N),
    "change_brief_enabled": bool(cfg.CHANGE_BRIEF_ENABLED),
    "sector_blacklist": "",
}


def get_settings(*, refresh: bool = False) -> dict[str, Any]:
    """Return merged settings (DB overlay + env override for SendKey)."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return dict(_CACHE)
    stored = load_setting("runtime", {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    out = dict(_DEFAULTS)
    out.update({k: stored[k] for k in _DEFAULTS if k in stored})
    # Old installs used morning_push_only; map once when new key absent.
    if "change_brief_enabled" not in stored and "morning_push_only" in stored:
        out["change_brief_enabled"] = not bool(stored.get("morning_push_only"))
    env_key = os.environ.get("NEWS_RADAR_SERVERCHAN_SENDKEY", "").strip()
    if env_key:
        out["serverchan_sendkey"] = env_key
    out = _clamp(out)
    _CACHE = dict(out)
    return dict(out)


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge patch into runtime settings and persist."""
    global _CACHE
    cur = get_settings(refresh=True)
    for k, v in patch.items():
        if k in _DEFAULTS and v is not None:
            cur[k] = v
    cur = _clamp(cur)
    save_setting("runtime", cur)
    _CACHE = dict(cur)
    return dict(cur)


def setting(key: str, default: Any = None) -> Any:
    """Read one setting value."""
    return get_settings().get(key, default)


def _clamp(out: dict[str, Any]) -> dict[str, Any]:
    out["refresh_seconds"] = max(60, min(3600, int(out["refresh_seconds"])))
    out["heat_window_hours"] = max(1, min(168, int(out["heat_window_hours"])))
    out["push_score_min"] = max(1.0, min(100.0, float(out["push_score_min"])))
    out["push_cooldown_seconds"] = max(300, min(86400, int(out["push_cooldown_seconds"])))
    out["digest_gap_seconds"] = max(600, min(7200, int(out.get("digest_gap_seconds") or cfg.DIGEST_GAP_SECONDS)))
    out["push_daily_max"] = max(1, min(30, int(out.get("push_daily_max") or cfg.PUSH_DAILY_MAX)))
    out["serverchan_enabled"] = bool(out["serverchan_enabled"])
    out["serverchan_sendkey"] = str(out.get("serverchan_sendkey") or "").strip()
    out["llm_enabled"] = bool(out["llm_enabled"])
    out["morning_push_min_score"] = max(0.5, min(50.0, float(out["morning_push_min_score"])))
    out["morning_push_top_n"] = max(1, min(10, int(out["morning_push_top_n"])))
    out["change_brief_enabled"] = bool(out.get("change_brief_enabled", True))
    out["sector_blacklist"] = str(out.get("sector_blacklist") or "").strip()
    return out


def masked_settings() -> dict[str, Any]:
    """Settings for UI with SendKey masked."""
    s = get_settings()
    key = str(s.get("serverchan_sendkey") or "")
    if len(key) > 8:
        shown = key[:4] + "****" + key[-4:]
    elif key:
        shown = "****"
    else:
        shown = ""
    out = dict(s)
    out["serverchan_sendkey"] = shown
    out["serverchan_sendkey_set"] = bool(key)
    return out
