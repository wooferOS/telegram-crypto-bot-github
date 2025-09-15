import sys, types

sys.modules["config_dev3"] = types.SimpleNamespace(
    BINANCE_API_KEY="k",
    BINANCE_API_SECRET="s",
    OPENAI_API_KEY="",
    TELEGRAM_TOKEN="",
    CHAT_ID="",
    DEV3_REGION_TIMER="ASIA",
    DEV3_RECV_WINDOW_MS=5000,
    DEV3_RECV_WINDOW_MAX_MS=60000,
    API_BASE="https://api.binance.com",
    MARKETDATA_BASE="https://data-api.binance.vision",
    SCORING_WEIGHTS={
        "edge": 1.0,
        "liquidity": 0.1,
        "momentum": 0.1,
        "spread": 0.1,
        "volatility": 0.1,
    },
)
