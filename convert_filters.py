from __future__ import annotations

from typing import Dict, List, Tuple, Any

from convert_logger import logger, safe_log
from binance_api import get_ratio, get_lot_step, get_precision, get_token_balance
from utils_dev3 import (
    safe_float,
    safe_json_load,
    HISTORY_PATH,
    to_convert_asset,
    is_convert_supported_asset,
    mark_convert_unsupported,
)
from convert_api import get_quote_raw

CANDIDATE_WALLETS = ["SPOT_FUNDING", "SPOT", "FUNDING"]

REQUIRED_KEYS = ("from", "to", "amount_quote")


def _pair_has_required_fields(p: dict) -> bool:
    """Приймає як нові ключі (from/to/amount_quote), так і бексові (from_token/to_token/amount, amountQuote)."""
    from_sym = p.get("from") or p.get("from_token")
    to_sym = p.get("to") or p.get("to_token")
    amt = (
        p.get("amount_quote")
        or p.get("quote_amount")
        or p.get("amountQuote")
        or p.get("amount")
        or 0.0
    )
    try:
        amt = float(amt or 0.0)
    except Exception:
        amt = 0.0
    return bool(from_sym and to_sym and amt > 0)


DEFAULT_WALLET = "SPOT"
MIN_QUOTE_DEFAULT = 11.0


def normalize_pair(p: dict) -> dict:
    """Повертає пару у канонічному вигляді для конверта."""
    out = {
        "from": (p.get("from") or p.get("from_token") or "").upper(),
        "to": (p.get("to") or p.get("to_token") or "USDT").upper(),
        "wallet": (p.get("wallet") or DEFAULT_WALLET).upper(),
        "score": float(p.get("score") or 0.0),
        "prob": float(p.get("prob") or p.get("prob_up") or 0.0),
        "edge": float(p.get("edge") or p.get("expected_profit") or 0.0),
    }
    amt = (
        p.get("amount_quote")
        or p.get("quote_amount")
        or p.get("amountQuote")
        or p.get("amount")
        or 0.0
    )
    try:
        amt = float(amt)
    except Exception:
        amt = 0.0
    if amt <= 0:
        amt = MIN_QUOTE_DEFAULT
    out["amount_quote"] = amt
    return out


def _safe_pick_upper(raw: dict, keys: list[str]) -> str | None:
    """Return first non-empty value from ``raw[keys]`` stripped and uppercased."""
    for k in keys:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
    return None


def preflight_has_balance(asset: str, min_amount: float) -> bool:
    """Перевіряємо баланс перед тим, як дьоргати Convert API."""
    spot = get_token_balance(asset) or 0.0
    return spot >= (min_amount or 0.0)


def prepare_pair_for_convert(pair: dict) -> dict:
    """Нормалізація пар для Convert з уніфікацією назв."""
    raw = pair or {}
    # підтримуємо всі поширені варіанти ключів
    from_raw = _safe_pick_upper(raw, ["from_token", "from_asset", "fromAsset", "from", "fromToken"])
    to_raw = _safe_pick_upper(raw, ["to_token", "to_asset", "toAsset", "to", "toToken"])
    if not from_raw or not to_raw:
        logger.warning(
            "[dev3] ❌ prepare_pair_for_convert: відсутні токени: from=%s, to=%s; raw=%s",
            from_raw,
            to_raw,
            {k: raw.get(k) for k in ("from", "from_token", "to", "to_token")},
        )
        return {"skip": True, "reason": "pair_fields_missing"}
    if not is_convert_supported_asset(from_raw) or not is_convert_supported_asset(to_raw):
        logger.info("[dev3] skip convert (unsupported asset): %s->%s", from_raw, to_raw)
        return {"skip": True, "reason": "unsupported_convert_asset"}

    # нормалізуємо базові поля у єдині ключі
    result = {**raw}
    result["from_token"] = from_raw
    result["to_token"] = to_raw
    result["from_asset"] = to_convert_asset(from_raw)
    result["to_asset"] = to_convert_asset(to_raw)

    # дефолти, якщо відсутні
    if "wallet" not in result or not isinstance(result.get("wallet"), str):
        result["wallet"] = "SPOT"
    aq = result.get("amount_quote")
    if not isinstance(aq, (int, float)) or aq <= 0:
        result["amount_quote"] = 11.0
    return result


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
