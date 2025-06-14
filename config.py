import os

from secure_env_loader import load_env_file

# Load environment variables from the server-side .env file
load_env_file("/root/.env")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", os.environ.get("CHAT_ID", "0")))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY", "")
BINANCE_API_SECRET = BINANCE_SECRET_KEY  # alias for compatibility

# Thresholds for trading decisions
MIN_PROB_UP = float(os.environ.get("MIN_PROB_UP", "0.45"))
MIN_EXPECTED_PROFIT = float(os.environ.get("MIN_EXPECTED_PROFIT", "0.3"))
MIN_TRADE_AMOUNT = float(os.environ.get("MIN_TRADE_AMOUNT", "10"))

# Auto trading loop interval in seconds
TRADE_LOOP_INTERVAL = int(os.environ.get("TRADE_LOOP_INTERVAL", "3600"))

# Storage files
HISTORY_FILE = os.environ.get("HISTORY_FILE", "trade_history.json")
ALERTS_FILE = os.environ.get("ALERTS_FILE", "pending_alerts.json")
