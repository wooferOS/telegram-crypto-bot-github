# Telegram configuration
# These values are populated on the server only and should never be committed
# with real credentials. They remain here purely as placeholders for local
# configuration.
TELEGRAM_TOKEN = ""
CHAT_ID = 0
ADMIN_CHAT_ID = 0

# API keys
BINANCE_API_KEY = ""
BINANCE_SECRET_KEY = ""
OPENAI_API_KEY = ""


# Thresholds for trading decisions
# Updated trading thresholds
MIN_PROB_UP = 0.45
# Minimum expected profit to consider a token attractive.
# Reduced to allow generation of signals even with tiny profit
MIN_EXPECTED_PROFIT = 0.01
MIN_TRADE_AMOUNT = 10.0  # USDT

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = 3600
