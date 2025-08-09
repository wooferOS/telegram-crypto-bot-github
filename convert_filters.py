from __future__ import annotations

import os
import json
from typing import Dict, List, Tuple, Any

from convert_logger import logger, safe_log
from binance_api import get_spot_price, get_ratio, get_lot_step, get_precision
from utils_dev3 import safe_float
import os


def get_ratio_from_spot(from_token: str, to_token: str) -> float:
    """Helper alias for spot price ratio."""
    return get_ratio(from_token, to_token)

# Allow slight negative scores and smaller toAmount for training trades
MIN_SCORE = -0.0005

EXPLORE_MODE = int(os.getenv("EXPLORE_MODE", "0"))
EXPLORE_PAPER = int(os.getenv("EXPLORE_PAPER", "0"))
EXPLORE_MIN_EDGE = float(os.getenv("EXPLORE_MIN_EDGE", "0.001"))


def _compute_edge(spot_inverse: float, quote_inverse: float) -> float:
    """Positive edge if convert better than spot."""
    if spot_inverse <= 0:
        return -1.0
    return (spot_inverse - quote_inverse) / spot_inverse

HISTORY_FILE = os.path.join("logs", "convert_history.json")


def get_token_info(token_key: str) -> Dict[str, Any] | None:
    """Return token metadata with fallback values and detailed logging."""
    if not token_key or not isinstance(token_key, str):
        logger.warning("[dev3] ⚠️ Невалідний ключ токена: %s", token_key)
        return None

    token_key = token_key.upper()
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


def passes_filters(
    score: float,
    quote: Dict[str, Any],
    balance: float,
    *,
    force_spot: bool = False,
    min_edge: float = 0.0,
) -> Tuple[bool, str]:
    """Validate quote against multiple convert filters."""
    # --- Diagnostic log for quote evaluation ---
    try:
        _from = quote.get("fromToken") or quote.get("fromAsset")
        _to = quote.get("toToken") or quote.get("toAsset")
        ratio = safe_float(quote.get("ratio", 0))
        inv = safe_float(quote.get("inverseRatio", 0))
        fa = safe_float(quote.get("fromAmount", 0))
        ta = safe_float(quote.get("toAmount", 0))
        spot = None
        try:
            spot = get_ratio(_from, _to)
        except Exception:
            spot = None
        logger.info(
            safe_log(
                f"[dev3] 🔎 passes_filters dbg: {_from}->{_to} "
                f"score={score:.4f} ratio={ratio} inv={inv} "
                f"fromAmount={fa} toAmount={ta} spot={spot} min_edge={min_edge:.4f}"
            )
        )
    except Exception as e:
        logger.warning(safe_log(f"[dev3] ⚠️ passes_filters dbg failed: {e}"))

    from_amount = safe_float(quote.get("fromAmount", 0))
    to_amount = safe_float(quote.get("toAmount", 0))

    from_token = quote.get("fromAsset") or quote.get("fromToken")
    to_token = quote.get("toAsset") or quote.get("toToken")
    if not from_token or not to_token:
        logger.warning(
            "[dev3] ❌ Один із токенів None: from_token=%s, to_token=%s",
            from_token,
            to_token,
        )
        return False, "invalid_tokens"

    r_convert = safe_float(quote.get("ratio", 0))
    r_spot = get_ratio(from_token, to_token)
    spot_inv = 1 / r_spot if r_spot else 0
    quote_inv = 1 / r_convert if r_convert else 0
    edge = _compute_edge(spot_inv, quote_inv)

    if EXPLORE_MODE:
        if edge >= EXPLORE_MIN_EDGE:
            return True, "ok_explore"
        return False, "edge_too_small_explore"

    if score < MIN_SCORE:
        return False, "low_score"

    if edge <= 0 and not force_spot:
        return False, "no_profit"

    if r_spot and r_convert and r_convert < r_spot:
        if not force_spot:
            return False, "spot_no_profit"
        if (r_spot - r_convert) <= min_edge * max(r_spot, r_convert):
            edge_val = (r_spot - r_convert) / max(r_spot, r_convert)
            logger.info(
                safe_log(
                    f"[dev3] \U0001F515 spot_edge too small: edge={edge_val:.6f} < min_edge={min_edge:.6f}"
                )
            )
            return False, "spot_edge_too_small"
        return True, "explore_spot_positive"

    if to_amount <= from_amount:
        logger.info(safe_log("[dev3] ⛔️ passes_filters вирок: no_profit"))
        return False, "no_profit"

    from_symbol = from_token.upper()
    to_symbol = to_token.upper()

    try:
        to_price = get_spot_price(to_symbol)
        to_usdt_value = to_amount * to_price
    except Exception as e:
        return False, f"price_lookup_failed: {e}"

    if to_usdt_value < 0.5:
        return False, f"to_amount_too_low_usdt (≈{to_usdt_value:.4f})"
    if balance < from_amount:
        return False, "insufficient_balance"
    return True, "ok"


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
