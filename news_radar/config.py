"""Runtime configuration for news-radar (mirrors market-desk style)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "radar.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"
PORT = 8770
BROWSER_HOST = "127.0.0.1"

# Poll public news sources on this cadence (seconds).
REFRESH_SECONDS = 300
# How far back to keep articles (days).
ARTICLE_RETENTION_DAYS = 14
# Heat window for sector ranking (hours).
HEAT_WINDOW_HOURS = 24
# Minimum sector score before Server酱 push (intraday; morning uses morning_push_min).
PUSH_SCORE_MIN = 8.0
# Cooldown between identical sector push keys (seconds) — used only if morning_only is off.
PUSH_COOLDOWN_SECONDS = 3600
# Prefer one Server酱 digest in the morning window instead of per-sector spam.
MORNING_PUSH_ONLY = True
MORNING_PUSH_START = "08:00"
MORNING_PUSH_END = "09:25"
MORNING_PUSH_MIN_SCORE = 3.0
MORNING_PUSH_TOP_N = 3
# Relative heat: compare current window vs the previous equal window.
REL_HEAT_MIN_DELTA = 1.5
# Board day-move threshold (pct) to call 「共振」.
BOARD_CONFIRM_PCT = 0.8

# Server酱³ SendKey (SCT...). Empty = push disabled until set in settings / env.
# Prefer env NEWS_RADAR_SERVERCHAN_SENDKEY or UI settings over hardcoding.
SERVERCHAN_SENDKEY = ""
SERVERCHAN_ENABLED = False

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}

# Optional LLM later (off by default).
LLM_ENABLED = False
LLM_API_BASE = ""
LLM_API_KEY = ""
LLM_MODEL = ""
