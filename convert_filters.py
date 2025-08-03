from __future__ import annotations
import os
import json
from typing import Dict, Tuple, List, Any

from convert_logger import logger
from binance_api import get_spot_price, get_ratio, get_lot_step, get_precision
from utils_dev3 import safe_float


def get_ratio_from_spot(from_token: str, to_token: str) -> float:
    """Helper alias for spot price ratio."""
    return get_ratio(from_token, to_token)

# Allow slight negative scores and smaller toAmount for training trades
MIN_SCORE = -0.0005

HISTORY_FILE = os.path.join("logs", "convert_history.json")


_token_limits_cache: Dict[str, Dict[str, Any]] | None = None
_logged_missing_tokens: set[str] = set()


def _load_token_limits() -> Dict[str, Dict[str, Any]]:
    """Lazy-load token limits from ``quote_limits.json``."""
    global _token_limits_cache
    if _token_limits_cache is None:
        try:
            with open("quote_limits.json", "r", encoding="utf-8") as f:
                _token_limits_cache = json.load(f)
        except Exception as exc:  # pragma: no cover - file issues
            logger.warning("[dev3] ❌ Не вдалося прочитати quote_limits.json: %s", exc)
            _token_limits_cache = {}
    return _token_limits_cache


def _log_missing_token(token: str) -> None:
    """Persist the name of tokens missing from ``quote_limits.json``."""
    if not token or token in _logged_missing_tokens:
        return
    path = os.path.join("logs", "missing_tokens.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(token + "\n")
        _logged_missing_tokens.add(token)
    except Exception as exc:  # pragma: no cover - diagnostics
        logger.warning("[dev3] ❌ Не вдалося записати відсутній токен %s: %s", token, exc)


def get_token_info(token_key: str) -> Dict[str, Any] | None:
    """Return token metadata with fallback values and detailed logging."""
    if not token_key or not isinstance(token_key, str):
        logger.warning("[dev3] ⚠️ Невалідний ключ токена: %s", token_key)
        return None

    token_key = token_key.upper()
    limits = _load_token_limits()
    info = limits.get(token_key)
    if info:
        info.setdefault("symbol", token_key)
        return info

    logger.info("[dev3] ℹ️ Токен %s відсутній у quote_limits.json", token_key)
    _log_missing_token(token_key)

    try:
        lot = get_lot_step(token_key)
        step = float(lot.get("stepSize", 1))
        decimals = get_precision(token_key)
        return {"symbol": token_key, "minQty": 1, "stepSize": step, "decimals": decimals}
    except Exception as exc:  # pragma: no cover - network
        logger.warning("[dev3] ❌ Fallback для %s провалився: %s", token_key, exc)
        return {"symbol": token_key, "minQty": 1, "stepSize": 1, "decimals": 0}


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

    from_token = quote.get("fromAsset") or quote.get("fromToken")
    to_token = quote.get("toAsset") or quote.get("toToken")
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
