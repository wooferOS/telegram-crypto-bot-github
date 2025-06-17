import os

# Thresholds for trading decisions
# Updated trading thresholds
MIN_PROB_UP = 0.45
# Minimum expected profit to consider a token attractive.
# Reduced to allow generation of signals even with tiny profit
MIN_EXPECTED_PROFIT = 0.01
MIN_TRADE_AMOUNT = float(os.getenv("MIN_TRADE_AMOUNT", 10))  # USDT

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = int(os.getenv("TRADE_LOOP_INTERVAL", 3600))
