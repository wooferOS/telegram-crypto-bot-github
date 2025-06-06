import logging
import requests
from typing import Optional, Dict

BASE_URL = "https://api.coingecko.com/api/v3"
logger = logging.getLogger(__name__)


def get_coin_market_data(coin_id: str) -> Optional[Dict]:
    url = f"{BASE_URL}/coins/{coin_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false",
        "sparkline": "false",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("market_data", {})
        return {
            "volume_24h": data.get("total_volume", {}).get("usd"),
            "change_24h": data.get("price_change_percentage_24h"),
            "sentiment_up": resp.json().get("sentiment_votes_up_percentage"),
            "sentiment_down": resp.json().get("sentiment_votes_down_percentage"),
        }
    except Exception as exc:
        logger.error("CoinGecko request failed for %s: %s", coin_id, exc)
        return None

