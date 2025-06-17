import os

# Telegram configuration
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = int(os.environ.get("CHAT_ID", "0"))


# Thresholds for trading decisions
# Updated trading thresholds
MIN_PROB_UP = 0.45
# Minimum expected profit to consider a token attractive.
# Reduced to allow generation of signals even with tiny profit
MIN_EXPECTED_PROFIT = 0.01
MIN_TRADE_AMOUNT = float(os.environ.get("MIN_TRADE_AMOUNT", 10))  # USDT

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = int(os.environ.get("TRADE_LOOP_INTERVAL", 3600))
