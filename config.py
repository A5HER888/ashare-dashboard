# config.py — Global constants. Edit these to tune behavior.

# ---------------------------------------------------------------------------
# Development mode
# Set DEV_MODE = True to use synthetic mock data instead of live requests.
# Useful when the network is unavailable or during UI development.
# ---------------------------------------------------------------------------
DEV_MODE = False

# ---------------------------------------------------------------------------
# Data source selection
# "yfinance"  — Yahoo Finance (recommended when outside China / in the US).
#               Reliable US servers, free, no API key, covers all A-shares.
# "akshare"   — Scrapes Chinese financial sites. Works best inside China or
#               on a CN-routed VPN. Prone to connection drops from overseas.
# ---------------------------------------------------------------------------
DATA_SOURCE = "akshare"

# ---------------------------------------------------------------------------
# Major A-share indices: display name -> 6-digit symbol
# ---------------------------------------------------------------------------
MAJOR_INDICES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "沪深300": "000300",
    "创业板指": "399006",
}

# Local file for watchlist persistence
WATCHLIST_FILE = "watchlist.json"

# Moving average periods
MA_PERIODS = [5, 10, 20, 60]

# RSI settings
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# MACD settings
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Volume ratio: average over last N days
VOLUME_AVG_PERIOD = 5
VOLUME_RATIO_MODERATE = 1.5    # Yellow highlight
VOLUME_RATIO_HIGH = 2.0        # Red highlight

# Breakout: look back N days for recent high
BREAKOUT_LOOKBACK = 20

# Streamlit cache TTL in seconds (5 minutes)
CACHE_TTL = 300

# Default historical days to fetch
DEFAULT_HISTORY_DAYS = 180

# ---------------------------------------------------------------------------
# Network retry settings
# ---------------------------------------------------------------------------
RETRY_COUNT = 3        # Number of attempts before giving up
RETRY_DELAY = 2.0      # Seconds to wait between retries (doubles each attempt)
REQUEST_TIMEOUT = 15   # Seconds before a single request times out
