"""
config.py — All configuration: API keys, universe, circuit breakers.
"""
import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise EnvironmentError(f"Missing required env var: {key}")
    return v

# ---------------------------------------------------------------------------
# API credentials
# ---------------------------------------------------------------------------
ALPACA_API_KEY    = _require("ALPACA_API_KEY")
ALPACA_SECRET_KEY = _require("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

FINNHUB_API_KEY   = _require("FINNHUB_API_KEY")

TELEGRAM_TOKEN    = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID  = int(_require("TELEGRAM_CHAT_ID"))

SUPABASE_URL      = _require("SUPABASE_URL")
SUPABASE_KEY      = os.environ.get("SUPABASE_SERVICE_KEY") or _require("SUPABASE_ANON_KEY")

# ---------------------------------------------------------------------------
# Trading phase
# ---------------------------------------------------------------------------
PHASE = os.environ.get("TRADING_PHASE", "paper")   # "paper" or "live"

# ---------------------------------------------------------------------------
# Circuit breakers
# ---------------------------------------------------------------------------
MAX_POSITIONS      = int(os.environ.get("MAX_POSITIONS", 2))
MAX_POSITION_SIZE  = float(os.environ.get("MAX_POSITION_SIZE", 500))   # $ per trade
DAILY_LOSS_LIMIT   = float(os.environ.get("DAILY_LOSS_LIMIT", 200))    # $ daily stop
SPY_CIRCUIT_PCT    = float(os.environ.get("SPY_CIRCUIT_PCT", -1.5))    # % drop triggers halt
RSI_EXIT_THRESHOLD = float(os.environ.get("RSI_EXIT_THRESHOLD", 72))   # exit if RSI > this
HOLD_MAX_DAYS      = int(os.environ.get("HOLD_MAX_DAYS", 2))           # force exit after N days
MIN_SCORE          = int(os.environ.get("MIN_SCORE", 65))              # min score to recommend
NO_CHASE_PCT       = float(os.environ.get("NO_CHASE_PCT", 8.0))        # skip if already up 8%+

# ---------------------------------------------------------------------------
# Stock universe — Tier 1: always scanned
# ---------------------------------------------------------------------------
TIER1_WATCHLIST = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "AMD", "MU",
    "AVGO", "ARM", "TSM", "NFLX", "COIN", "PLTR", "SOFI", "MSTR", "SMCI",
    "PYPL", "CRM",
]

# Sector ETF checks — confirms broader sector tailwind
SECTOR_ETFS = {
    "NVDA": "SOXX", "AMD": "SOXX", "MU": "SOXX", "AVGO": "SOXX",
    "ARM": "SOXX", "TSM": "SOXX", "SMCI": "SOXX",
    "AAPL": "QQQ",  "MSFT": "QQQ", "GOOGL": "QQQ", "META": "QQQ",
    "AMZN": "QQQ",  "TSLA": "QQQ", "NFLX": "QQQ",
    "COIN": "QQQ",  "PLTR": "QQQ", "SOFI": "QQQ",
    "MSTR": "QQQ",  "PYPL": "QQQ", "CRM": "QQQ",
}

# ---------------------------------------------------------------------------
# Screening hard filters (Tier 2 Finnhub movers)
# ---------------------------------------------------------------------------
FILTER_MIN_PRICE       = float(os.environ.get("FILTER_MIN_PRICE", 10))
FILTER_MIN_MKTCAP_B    = float(os.environ.get("FILTER_MIN_MKTCAP_B", 2))    # $2B+
FILTER_MIN_CHANGE_PCT  = float(os.environ.get("FILTER_MIN_CHANGE_PCT", 1.5))
FILTER_MIN_AVG_VOLUME  = int(os.environ.get("FILTER_MIN_AVG_VOLUME", 500_000))
FILTER_MIN_VOL_RATIO   = float(os.environ.get("FILTER_MIN_VOL_RATIO", 1.5))
