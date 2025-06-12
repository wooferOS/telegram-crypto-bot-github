import os

# Thresholds for trading decisions
MIN_PROB_UP = float(os.getenv("MIN_PROB_UP", 0.55))
MIN_EXPECTED_PROFIT = float(os.getenv("MIN_EXPECTED_PROFIT", 0.001))
MIN_TRADE_AMOUNT = float(os.getenv("MIN_TRADE_AMOUNT", 10))  # USDT

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = int(os.getenv("TRADE_LOOP_INTERVAL", 600))
