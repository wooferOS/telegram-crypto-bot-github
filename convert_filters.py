from __future__ import annotations

from typing import Dict, List, Tuple, Any

from convert_logger import logger, safe_log
from binance_api import get_ratio, get_lot_step, get_precision
from utils_dev3 import (
    safe_float,
    safe_json_load,
    HISTORY_PATH,
    to_convert_asset,
    is_convert_supported_asset,
    mark_convert_unsupported,
)
from convert_api import get_quote_raw

import logging

CANDIDATE_WALLETS = ["SPOT_FUNDING", "SPOT", "FUNDING"]

log = logging.getLogger(__name__)

REQUIRED_KEYS = ("from", "to", "amount_quote")


def normalize_pair(raw: Dict[str, Any], min_quote: float) -> Dict[str, Any]:
    """Приводимо різні варіанти ключів до єдиних."""
    sym_from = (
        raw.get("from")
        or raw.get("from_token")
        or raw.get("base")
        or raw.get("symbol_from")
    )
    sym_to = (
        raw.get("to")
        or raw.get("to_token")
        or raw.get("quote")
        or raw.get("symbol_to")
        or "USDT"
    )
    wallet = (raw.get("wallet") or "SPOT").upper()

    aq = (
        raw.get("amount_quote")
        or raw.get("amountQuote")
        or raw.get("quote_amount")
        or raw.get("amount")
        or 0.0
    )
    try:
        aq = float(aq or 0.0)
    except Exception:
        aq = 0.0

    pair = {
        "from": (sym_from or "").upper(),
        "to": (sym_to or "").upper(),
        "wallet": wallet,
        "amount_quote": aq if aq > 0 else float(min_quote),
    }
    return pair


def validate_pair(pair: Dict[str, Any]) -> Tuple[bool, str]:
    """Перевіряємо присутність ключів та позитивну суму."""
    for k in REQUIRED_KEYS:
        if k not in pair:
            return False, f"missing_{k}"
    if not pair["from"] or not pair["to"]:
        return False, "empty_symbol"
    if pair["amount_quote"] is None:
        return False, "amount_none"
    if float(pair["amount_quote"]) <= 0:
        return False, "amount_zero"
    return True, "ok"


def find_wallet_with_quote_id(from_asset: str, to_asset: str, from_amount: float):
    """Пробуємо кілька walletType — повертаємо перший респонс із quoteId."""
    amt = f"{from_amount:.10f}".rstrip('0').rstrip('.') if from_amount else "0"
    for w in CANDIDATE_WALLETS:
        resp = get_quote_raw(from_asset, to_asset, from_amount=amt, wallet_type=w)
        js = resp.get("json", {})
        qid = js.get("quoteId")
        if qid:
            return w, js
        msg = js if isinstance(js, dict) else {}
        logger.debug(
            "[dev3] getQuote no quoteId %s→%s amount=%s wallet=%s resp=%s",
            from_asset,
            to_asset,
            amt,
            w,
            msg,
        )
        if '"code":-1002' in str(msg) or "not supported" in str(msg).lower():
            mark_convert_unsupported(from_asset)
    return None


def get_ratio_from_spot(from_token: str, to_token: str) -> float:
    """Helper alias for spot price ratio."""
    return get_ratio(from_token, to_token)

# Allow slight negative scores and smaller toAmount for training trades
MIN_SCORE = -0.0005


def _compute_edge(spot_inverse: float, quote_inverse: float) -> float:
    """Positive edge if convert better than spot."""
    if spot_inverse <= 0:
        return -1.0
    return (spot_inverse - quote_inverse) / spot_inverse

HISTORY_FILE = str(HISTORY_PATH)


def _score(item: Dict[str, Any]) -> float:
    try:
        return float(item.get("score", item.get("gpt", {}).get("score", 0)))
    except Exception:
        return 0.0


def sort_by_score(candidates: List[Dict[str, Any]]):
    return sorted(candidates or [], key=_score, reverse=True)


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
    context: str,
    explore_min_edge: float,
    min_lot_factor: float,
) -> Tuple[bool, str, float]:
    """Validate quote against multiple convert filters."""
    try:
        _from = quote.get("fromToken") or quote.get("fromAsset")
        _to = quote.get("toToken") or quote.get("toAsset")
        ratio = safe_float(quote.get("ratio", 0))
        inv = safe_float(quote.get("inverseRatio", 0))
        fa = safe_float(quote.get("fromAmount", 0))
        ta = safe_float(quote.get("toAmount", 0))
        logger.info(
            safe_log(
                f"[dev3] \U0001f50e passes_filters dbg: {_from}->{_to} score={score:.4f} "
                f"ratio={ratio:.6f} inv={inv:.6f} fromAmount={fa:.6f} toAmount={ta:.6f} "
                f"min_edge={explore_min_edge:.6f}"
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
        return False, "invalid_tokens", -1.0

    r_convert = safe_float(quote.get("ratio", 0))
    r_spot = get_ratio(from_token, to_token)
    if r_convert <= 0 or r_spot <= 0:
        return False, "price_zero", -1.0

    spot_inv = 1 / r_spot if r_spot else 0
    quote_inv = 1 / r_convert if r_convert else 0
    edge = _compute_edge(spot_inv, quote_inv)
    logger.debug(
        "edge_dbg: spot_inv={:.6f} quote_inv={:.6f} edge={:.6f} min_edge={:.6f}",
        spot_inv,
        quote_inv,
        edge,
        explore_min_edge,
    )

    lot = get_lot_step(from_token)
    min_qty = safe_float(lot.get("minQty", lot.get("stepSize", 0)))
    if from_amount < min_qty * min_lot_factor:
        return False, "min_lot", edge

    if score < MIN_SCORE:
        return False, "low_score", edge

    if context == "explore" and edge < explore_min_edge:
        return False, "edge_too_small_explore", edge

    if to_amount <= 0 or from_amount <= 0:
        return False, "price_zero", edge

    if balance < from_amount:
        return False, "insufficient_balance", edge

    return True, "ok", edge


from datetime import datetime, timedelta


def was_token_recently_bought(to_token: str, hours: int = 72) -> bool:
    """Check if the token was bought in the last `hours` hours."""
    history = safe_json_load(HISTORY_FILE, default=[])
    if not isinstance(history, list):
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
