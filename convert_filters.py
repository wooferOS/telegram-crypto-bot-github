from __future__ import annotations
import os
import json
from typing import Dict, Tuple, List, Any

from convert_logger import logger
from binance_api import get_spot_price, get_ratio
from utils_dev3 import safe_float


def get_ratio_from_spot(from_token: str, to_token: str) -> float:
    """Helper alias for spot price ratio."""
    return get_ratio(from_token, to_token)

# Allow slight negative scores and smaller toAmount for training trades
MIN_SCORE = -0.0005

HISTORY_FILE = os.path.join("logs", "convert_history.json")


def filter_top_tokens(
    all_tokens: Dict[str, Dict],
    score_threshold: float,
    top_n: int = 3,
    fallback_n: int = 1,
) -> List[Tuple[str, Dict]]:
    """Return top tokens filtered by score with fallback for training."""

    # Filter tokens with score above threshold
    filtered = [
        (token, data)
        for token, data in all_tokens.items()
        if safe_float(data.get("score", data.get("gpt", {}).get("score", 0)))
        >= score_threshold
    ]
    filtered.sort(
        key=lambda x: safe_float(x[1].get("score", x[1].get("gpt", {}).get("score", 0))),
        reverse=True,
    )

    # Fallback logic: select tokens with highest score even if below threshold
    if not filtered:
        logger.info(
            "[dev3] ❕ Немає токенів з високим score. Використовуємо навчальні угоди."
        )
        sorted_tokens = sorted(
            all_tokens.items(),
            key=lambda x: safe_float(
                x[1].get("score", x[1].get("gpt", {}).get("score", 0))
            ),
            reverse=True,
        )
        return sorted_tokens[:fallback_n]

    # Виключаємо токени, нещодавно куплені
    filtered = [
        (token, data)
        for token, data in filtered
        if not was_token_recently_bought(token)
    ]

    return filtered[:top_n]


def passes_filters(score: float, quote: Dict[str, Any], balance: float) -> Tuple[bool, str]:
    """Validate quote against multiple convert filters."""
    if score < MIN_SCORE:
        return False, "low_score"

    from_amount = safe_float(quote.get("fromAmount", 0))
    to_amount = safe_float(quote.get("toAmount", 0))
    if to_amount <= from_amount:
        return False, "no_profit"

    from_token = quote.get("fromAsset")
    to_token = quote.get("toAsset")
    if not from_token or not to_token:
        logger.warning(
            "[dev3] ❌ Один із токенів None: from_token=%s, to_token=%s",
            from_token,
            to_token,
        )
        return False, "invalid_tokens"

    from_symbol = from_token.upper()
    to_symbol = to_token.upper()

    try:
        to_price = get_spot_price(to_symbol)
        to_usdt_value = to_amount * to_price
    except Exception as e:
        return False, f"price_lookup_failed: {e}"

    spot_ratio = get_ratio(from_symbol, to_symbol)
    if spot_ratio <= 0:
        return False, "spot_ratio_failed"
    if spot_ratio <= 1.0:
        return False, "spot_no_profit"

    if to_usdt_value < 0.5:
        return False, f"to_amount_too_low_usdt (≈{to_usdt_value:.4f})"
    if balance < from_amount:
        return False, "insufficient_balance"
    return True, ""


from datetime import datetime, timedelta


def was_token_recently_bought(to_token: str, hours: int = 72) -> bool:
    """Check if the token was bought in the last `hours` hours."""
    if not os.path.exists(HISTORY_FILE):
        return False

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return False

    threshold_time = datetime.utcnow() - timedelta(hours=hours)

    for entry in reversed(history):  # Start from most recent
        if not entry.get("accepted"):
            continue
        if entry.get("to") == to_token:
            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                continue
            try:
                trade_time = datetime.fromisoformat(timestamp_str)
                if trade_time > threshold_time:
                    return True
            except Exception:
                continue
    return False
