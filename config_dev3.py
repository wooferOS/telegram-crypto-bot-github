BINANCE_API_KEY = "<SET_ME>"
BINANCE_API_SECRET = "<SET_ME>"
BINANCE_SECRET_KEY = BINANCE_API_SECRET

TELEGRAM_TOKEN = "<SET_ME>"
TELEGRAM_CHAT_ID = "465786073"
OPENAI_API_KEY = "<SET_ME>"

# runtime flags
DEV3_PAPER_MODE = False
DEV3_REGION_TIMER = "ASIA"
DEV3_RECV_WINDOW_MS = 5000  # default recvWindow per Binance docs (max 60000)

CONVERT_SCORE_THRESHOLD = 0.01

CHAT_ID = TELEGRAM_CHAT_ID

# weights for the composite scoring model used in :mod:`scoring`
# S = w1*edge + w2*liquidity + w3*momentum - w4*spread - w5*volatility
SCORING_WEIGHTS = {
    "edge": 1.0,
    "liquidity": 0.1,
    "momentum": 0.1,
    "spread": 0.1,
    "volatility": 0.1,
}
