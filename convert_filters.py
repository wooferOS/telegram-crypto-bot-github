from __future__ import annotations
import os
from typing import Dict, Tuple, List, Any

from convert_logger import logger
from convert_api import get_symbol_price

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
        if data.get("score", 0) >= score_threshold
    ]
    filtered.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    # Fallback logic: select tokens with highest score even if below threshold
    if not filtered:
        logger.info(
            "[dev3] ❕ Немає токенів з високим score. Використовуємо навчальні угоди."
        )
        sorted_tokens = sorted(
            all_tokens.items(), key=lambda x: x[1].get("score", 0), reverse=True
        )
        return sorted_tokens[:fallback_n]

    return filtered[:top_n]


def passes_filters(score: float, quote: Dict[str, Any], balance: float) -> Tuple[bool, str]:
    """Validate quote against multiple convert filters."""
    if score < MIN_SCORE:
        return False, "low_score"

    from_amount = float(quote.get("fromAmount", 0))
    to_amount = float(quote.get("toAmount", 0))
    if to_amount <= from_amount:
        return False, "no_profit"

    to_token = quote.get("toAsset")
    try:
        to_price = get_symbol_price(to_token)
        to_usdt_value = to_amount * to_price
    except Exception as e:
        return False, f"price_lookup_failed: {e}"

    if to_usdt_value < 0.5:
        return False, f"to_amount_too_low_usdt (≈{to_usdt_value:.4f})"
    if balance < from_amount:
        return False, "insufficient_balance"
    return True, ""
