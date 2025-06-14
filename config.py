# Required credentials
TELEGRAM_TOKEN = "123456:ABC..."
CHAT_ID = "123456789"
ADMIN_CHAT_ID = int(CHAT_ID)
OPENAI_API_KEY = "sk-..."
COINGECKO_API_KEY = "..."
BINANCE_API_KEY = "abc..."
BINANCE_SECRET_KEY = "def..."
BINANCE_API_SECRET = BINANCE_SECRET_KEY  # alias for compatibility

# Thresholds for trading decisions
MIN_PROB_UP = 0.45
MIN_EXPECTED_PROFIT = 0.3
MIN_TRADE_AMOUNT = 10  # USDT

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = 3600

# Storage files
HISTORY_FILE = "trade_history.json"
ALERTS_FILE = "pending_alerts.json"
