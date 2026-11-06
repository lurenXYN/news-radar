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
# Sector-hit weight multiplier by CLS editorial level (A = red headline, B = bold).
CLS_LEVEL_MULT = {"A": 1.3, "B": 1.15}
# Sector matching: a keyword seen only in the summary (not title / source tags)
# counts at SUMMARY_ONLY_MULT; lexicon ``weak`` keywords are scaled again.
SUMMARY_ONLY_MULT = 0.5
WEAK_KEYWORD_MULT = 0.5
# A source returning nothing this many refreshes in a row is flagged in the UI.
SOURCE_ZERO_WARN_ROUNDS = 3
# Cross-refresh near-duplicate check looks back this many hours of stored titles.
DEDUPE_LOOKBACK_HOURS = 24
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
# Server酱 free tier allows 5 pushes per SendKey per day, shared with
# market-desk (15:05 EOD one-pager); keep news-radar to the three digests.
EMPTY_WINDOW_ALERT = False
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
# When True, 「仅新闻」stays out of digest Top / export primary slots
# (still listed under 其余留意). Override via settings key digest_demote_news_only.
DIGEST_DEMOTE_NEWS_ONLY = True
# When True, skip the whole Server酱 digest unless Top has 共振 or 盘面已动.
# Override via settings key digest_require_board_confirm.
DIGEST_REQUIRE_BOARD_CONFIRM = True

# Soft usefulness observation window (does not change ranking / gates).
# After this many calendar days, review feedback + resonance next-day stats
# before tuning thresholds again.
EFFECT_OBSERVE_SINCE = "2026-11-05"
EFFECT_OBSERVE_DAYS = 7

# Event clustering: merge same-story reprints into one cluster.
# Articles always get a cluster_id when enabled; heat ranking stays on article
# weights until EVENT_CLUSTER_HEAT is flipped on after dual-track review.
EVENT_CLUSTER_ENABLED = True
EVENT_CLUSTER_HEAT = False  # when True, sector score uses event_score
EVENT_CLUSTER_HOURS = 24
EVENT_CLUSTER_SIM = 0.55  # title bigram Jaccard to join (raised after mis-merge samples)

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
