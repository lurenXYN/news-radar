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
# Minimum sector score for legacy filters.
PUSH_SCORE_MIN = 8.0
# Max successful Server酱 pushes per calendar day (quota).
PUSH_DAILY_MAX = 8
# Soft sector blacklist (comma-separated names in settings).
SECTOR_BLACKLIST: list[str] = []
# Scheduled digests (small windows so polling can hit once/day).
MORNING_PUSH_START = "08:55"
MORNING_PUSH_END = "09:10"
MIDDAY_PUSH_START = "12:55"
MIDDAY_PUSH_END = "13:10"
EVENING_PUSH_START = "20:55"
EVENING_PUSH_END = "21:15"
MORNING_PUSH_MIN_SCORE = 3.0
# Detailed sectors per digest; a few runners-up are listed in one line each.
MORNING_PUSH_TOP_N = 5
# Deprecated alias kept for old settings rows; ignored by new schedule.
MORNING_PUSH_ONLY = False
# Relative heat: compare current window vs the previous equal window.
REL_HEAT_MIN_DELTA = 1.5
# Board day-move threshold (pct) to call 「共振」.
BOARD_CONFIRM_PCT = 0.8
# Prefer market-desk soft board export over East Money clist (same VPS).
DESK_BOARDS_URL = "http://127.0.0.1:8765/api/export/boards"

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
