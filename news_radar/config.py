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
# Minimum sector score before Server酱 push.
PUSH_SCORE_MIN = 8.0
# Cooldown between identical sector push keys (seconds).
PUSH_COOLDOWN_SECONDS = 3600

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
