import os

# Thresholds for trading decisions
# Updated trading thresholds
MIN_PROB_UP = 0.5          # leave as is or lower to 0.45
MIN_EXPECTED_PROFIT = 0.5  # or even 0.3
MIN_TRADE_AMOUNT = float(os.getenv("MIN_TRADE_AMOUNT", 10))  # USDT

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = int(os.getenv("TRADE_LOOP_INTERVAL", 600))
