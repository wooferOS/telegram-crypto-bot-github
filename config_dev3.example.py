BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""
OPENAI_API_KEY = ""
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# Runtime flags
DEV3_REGION_TIMER = "ASIA"
DEV3_RECV_WINDOW_MS = 5000
DEV3_RECV_WINDOW_MAX_MS = 60000

# Base URLs
API_BASE = "https://api.binance.com"
MARKETDATA_BASE = "https://data-api.binance.vision"

# Trading config
PAPER_MODE = False
CONVERT_SCORE_THRESHOLD = 0.01
SCORING_WEIGHTS = {
    "edge": 1.0,
    "liquidity": 0.1,
    "momentum": 0.1,
    "spread": 0.1,
    "volatility": 0.1,
}
