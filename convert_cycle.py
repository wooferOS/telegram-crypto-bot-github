from __future__ import annotations

import json
import os
from typing import List, Dict, Any

from convert_api import get_quote, accept_quote, get_balances
from convert_filters import passes_filters
from convert_logger import (
    logger,
    save_convert_history,
    log_prediction,
    log_quote_skipped,
    log_conversion_success,
    log_conversion_error,
    log_skipped_quotes,
)
from quote_counter import should_throttle, reset_cycle
from convert_model import _hash_token

MAX_QUOTES_PER_CYCLE = 20
TOP_N_PAIRS = 5


def _load_top_pairs() -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    if not os.path.exists(path):
        logger.warning("[dev3] top_tokens.json not found")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover - file issues
        logger.warning("[dev3] failed to read top_tokens.json: %s", exc)
        return []


def process_top_pairs() -> None:
    """Process top pairs from daily analysis."""
    reset_cycle()
    pairs = _load_top_pairs()
    if not pairs:
        logger.warning("[dev3] No pairs to process")
        return

    balances = get_balances()
    pairs.sort(key=lambda x: x.get("score", 0), reverse=True)
    quote_count = 0

    for item in pairs[:TOP_N_PAIRS]:
        if quote_count >= MAX_QUOTES_PER_CYCLE:
            log_skipped_quotes()
            break

        from_token = item.get("from_token")
        to_token = item.get("to_token")
        score = float(item.get("score", 0))
        amount = balances.get(from_token, 0)

        log_prediction(from_token, to_token, score)

        if amount <= 0:
            log_quote_skipped(from_token, to_token, "no_balance")
            continue

        if should_throttle(from_token, to_token):
            log_quote_skipped(from_token, to_token, "throttled")
            continue

        quote = get_quote(from_token, to_token, amount)
        quote_count += 1

        if not quote:
            log_quote_skipped(from_token, to_token, "invalid_quote")
            continue

        valid, reason = passes_filters(score, quote, amount)
        if not valid:
            log_quote_skipped(from_token, to_token, reason)
            continue

        resp = accept_quote(quote.get("quoteId"))
        if resp and isinstance(resp, dict) and "code" not in resp:
            profit = float(resp.get("toAmount", 0)) - float(resp.get("fromAmount", 0))
            log_conversion_success(from_token, to_token, profit)
            features = [
                float(quote.get("ratio", 0)),
                float(quote.get("inverseRatio", 0)),
                float(amount),
                _hash_token(from_token),
                _hash_token(to_token),
            ]
            save_convert_history(
                {
                    "from": from_token,
                    "to": to_token,
                    "features": features,
                    "profit": profit,
                    "accepted": True,
                }
            )
        else:
            log_conversion_error(from_token, to_token, str(resp))
            save_convert_history(
                {
                    "from": from_token,
                    "to": to_token,
                    "features": [
                        float(quote.get("ratio", 0)),
                        float(quote.get("inverseRatio", 0)),
                        float(amount),
                        _hash_token(from_token),
                        _hash_token(to_token),
                    ],
                    "profit": 0.0,
                    "accepted": False,
                }
            )

    logger.info("[dev3] ✅ Цикл завершено")

