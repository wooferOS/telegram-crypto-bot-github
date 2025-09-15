import requests
from urllib.parse import urlencode
import os, time, hmac, hashlib
import math
from decimal import Decimal, ROUND_DOWN
from convert_api import get_binance_api_keys
from config_dev3 import API_BASE

_precision_cache = None
_pairs_cache = None

def _load_convert_meta():
    global _precision_cache, _pairs_cache
    if _precision_cache is None:
        # asset-precision MARKET_DATA: data: [{asset, fraction}, ...]
        try:
            _precision_cache = {e['asset']: int(e['fraction']) for e in asset_precision().get('data', [])}
        except Exception:
            _precision_cache = {}
    if _pairs_cache is None:
        # exchangeInfo MARKET_DATA: data: [{fromAsset,toAsset,...min/max...}, ...]
        _pairs_cache = {}
        try:
            for it in convert_pairs().get('data', []):
                _pairs_cache[(it.get('fromAsset'), it.get('toAsset'))] = it
        except Exception:
            _pairs_cache = {}
    return _precision_cache, _pairs_cache

def _quantize(asset: str, amount):
    from decimal import Decimal
    prec, _ = _load_convert_meta()
    frac = int(prec.get(asset, 8))  # дефолт: 8 знаків
    q = Decimal(1) / (Decimal(10) ** frac)
    # підрізаємо вниз, щоб не вилізти за precision
    return (amount // q) * q

def _min_max_ok(fromAsset: str, toAsset: str, amount):
    from decimal import Decimal
    _, pairs = _load_convert_meta()
    info = pairs.get((fromAsset, toAsset))
    if not info:
        return False
    # Поля min/max у Convert залежать від пари. Найчастіше є quote-межі.
    mn = info.get('minQuote') or info.get('fromAssetMinQty') or '0'
    mx = info.get('maxQuote') or info.get('toAssetMaxQty') or '1e50'
    mn = Decimal(str(mn)); mx = Decimal(str(mx))
    return (amount >= mn) and (amount <= mx)

from typing import List, Dict, Tuple

import convert_api
from convert_api import get_quote, accept_quote, get_order_status
from convert_logger import (
    logger,
    log_conversion_result,
)
from convert_filters import filter_top_tokens
from exchange_filters import load_symbol_filters, get_last_price_usdt
from convert_notifier import send_telegram
import config_dev3
from quote_counter import (
    can_request_quote,
    should_throttle,
    reset_cycle,
    log_cycle_summary,
    set_cycle_limit,
)
from risk_off import check_risk
import scoring
import time
# === legal money helper BEGIN ===
_LEGAL_MONEY_CACHE = {'ts': 0.0, 'data': set()}

def _get_legal_money_set(ttl_seconds: int = 3600):
    # Use /sapi/v1/capital/config/getall (USER_DATA) to detect fiat coins
    now = time.time()
    if _LEGAL_MONEY_CACHE['data'] and (now - _LEGAL_MONEY_CACHE['ts'] < ttl_seconds):
        return _LEGAL_MONEY_CACHE['data']

    api_key, api_secret = get_binance_api_keys()

    if not api_key or not api_secret:
        return _LEGAL_MONEY_CACHE['data']

    base = API_BASE.rstrip('/')
    endpoint = '/sapi/v1/capital/config/getall'
    params = {'timestamp': int(time.time() * 1000)}
    qs = urlencode(params)
    signature = hmac.new(api_secret.encode('utf-8'), qs.encode('utf-8'), hashlib.sha256).hexdigest()
    url = f"{base}{endpoint}?{qs}&signature={signature}"
    headers = {'X-MBX-APIKEY': api_key}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            fiats = set()
            for item in data:
                coin = str(item.get('coin', '')).upper()
                if coin and item.get('isLegalMoney') is True:
                    fiats.add(coin)
            if fiats:
                _LEGAL_MONEY_CACHE['data'] = fiats
                _LEGAL_MONEY_CACHE['ts'] = now
    except Exception:
        # fail-quietly: не блокуємо торг-цикл, якщо API недоступне
        pass
    return _LEGAL_MONEY_CACHE['data']
# === legal money helper END ===




# Allow executing quotes with low score for model training
allow_learning_quotes = True

MIN_CONVERT_TOAMOUNT = 0.0
EXPLORE_MIN_EDGE = 0.0



def process_pair(from_token: str, to_tokens: List[str], amount: float, score_threshold: float) -> bool:
    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(to_tokens)} токенів")
    quotes_map: Dict[str, Dict] = {}
    scores: Dict[str, float] = {}
    all_tokens: Dict[str, Dict] = {}
    skipped_pairs: List[Tuple[str, float, str]] = []  # (token, score, reason)

    reset_cycle()
    risk_level, drawdown = check_risk()
    valid_time = "30s"
    if risk_level >= 2:
        logger.warning(
            "[dev3] 🛑 Risk-off: drawdown %.1f%% — пауза", drawdown * 100
        )
        log_cycle_summary()
        return False
    if risk_level == 1:
        set_cycle_limit(5)
        valid_time = "10s"
        logger.warning(
            "[dev3] ⚠️ Risk-off: drawdown %.1f%% — зменшення активності",
            drawdown * 100,
        )
        time.sleep(5)
    # Convert: нормалізуємо amount за precision from_token
    amount = _quantize(from_token, Decimal(str(amount)))

    # Оціночна нотаціональність за останньою ціною (для логів; не фільтруємо по ній)
    px = get_last_price_usdt(from_token)
    if px is None:
        logger.warning("[dev3] ⚠️ Не вдалося отримати ціну %sUSDT", from_token)
    est_notional = (amount * px) if px is not None else None

    step_str = None  # більше не використовуємо step_size зі spot
    min_str = None   # більше не використовуємо min_notional зі spot
    px_str = str(px) if px is not None else None
    est_str = str(est_notional) if est_notional is not None else None

    # --- USDT fiat-deny filter (ідемпотентно) ---
    if from_token == 'USDT':
        _deny = {'BRL','COP','ARS','PLN','MXN','UAH','TRY','ZAR','CZK','EUR'}
        try:
            to_tokens = [t for t in to_tokens if t not in _deny]
        except Exception:
            pass
        logger.info("[dev3] 🔎 to_tokens(filtered) для %s: %s", from_token, to_tokens)
    # --- end filter ---
    # --- dynamic fiat filter (Capital isLegalMoney) ---
    try:
        fiat_set = _get_legal_money_set()
        if fiat_set:
            _before = len(to_tokens)
            to_tokens = [t for t in to_tokens if t not in fiat_set]
            if len(to_tokens) != _before:
                logger.info("[dev3] 🔎 to_tokens(filtered by legalMoney): %s", to_tokens)
    except Exception as _e:
        logger.warning("[dev3] legalMoney filter error: %s", _e)
    # --- end dynamic fiat filter ---
    for to_token in to_tokens:
        try:
            if to_token in _get_legal_money_set():
                logger.info("[dev3] skip(legalMoney): %s", to_token)
                continue
        except Exception:
            pass
        # Convert min/max фільтр для конкретної пари
        if not _min_max_ok(from_token, to_token, amount):
            logger.info("[dev3] skip(convertMinMax): %s→%s amount=%s", from_token, to_token, amount)
            continue
        if to_token == from_token:
            continue
        if (
            max_notional
            and max_notional > 0
            and est_notional is not None
            and est_notional > max_notional
        ):
            logger.info(
                "[dev3] skip(maxNotional): %s amount=%s px=%s est=%s > %s",
                from_token,
                amount,
                px,
                est_notional,
                max_notional,
            )
            log_conversion_result(
                {"fromAsset": from_token, "toAsset": to_token, "fromAmount": str(amount)},
                False,
                None,
                {"msg": "above MAX_NOTIONAL"},
                None,
                None,
                None,
                None,
                step_str,
                min_str,
                px_str,
                est_str,
                "skip(maxNotional)",
            )
            continue
        if should_throttle(from_token, to_token):
            skipped_pairs.append((to_token, 0.0, "throttled"))
            break

        try:

            amt = float(amount)

        except Exception:

            logger.warning("[dev3] ❌ amount invalid for %s -> %s: %r", from_token, to_token, amount)

            return False

        if not math.isfinite(amt) or amt <= 0:

            logger.info("[dev3] ⏭️ Пропуск %s -> %s: amount<=0 (%.8f)", from_token, to_token, amt if math.isfinite(amt) else float("nan"))

            return False

        quote = get_quote(from_token, to_token, amt, validTime=valid_time)
        if isinstance(quote, dict) and str(quote.get("msg", "")).lower().startswith("hourly"):
            logger.warning("[dev3] ⚠️ Hourly quotation limit reached, backoff")
            time.sleep(5)
            break

        if should_throttle(from_token, to_token, quote):
            break

        if not quote or "ratio" not in quote or "quoteId" not in quote:
            logger.warning(
                f"[dev3] ❌ Не вдалося отримати коректний quote для {from_token} → {to_token}"
            )
            skipped_pairs.append((to_token, 0.0, "ratio_unavailable"))
            continue

        ratio = float(quote.get("ratio", 0))
        res = scoring.score_pair(from_token, to_token, ratio)
        if res:
            edge = res.get("edge", 0.0)
            score = res.get("score", 0.0)
        else:
            edge = 0.0
            score = 0.0
        if abs(edge) > 0.5:
            edge = 0.0
            score = 0.0
        quote["score"] = score
        quote["edge"] = edge
        quotes_map[to_token] = quote
        scores[to_token] = score
        all_tokens[to_token] = {"score": score, "quote": quote}
        if score < score_threshold:
            skipped_pairs.append((to_token, score, f"low_score {score:.4f}"))

    filtered_pairs = filter_top_tokens(all_tokens, score_threshold, top_n=2)
    top_results = [(t, data["score"], data["quote"]) for t, data in filtered_pairs]

    training_candidate = None

    if top_results:
        logger.info("[dev3] ✅ Обрано токени для купівлі: %s", [t for t, _, _ in top_results])
    else:
        logger.warning("[dev3] ⚠️ Жоден токен не пройшов фільтри — виконуємо навчальну угоду.")
        # choose best available pair for training
        for token, data in sorted(all_tokens.items(), key=lambda x: x[1]["score"], reverse=True):
            quote = quotes_map.get(token)
            if quote:
                training_candidate = (token, scores.get(token, 0.0), quote)
                break
        if not training_candidate:
            logger.warning("[dev3] ❌ Немає доступної пари навіть для навчальної угоди.")
            return False

    if allow_learning_quotes and not training_candidate:
        # process one additional low-score pair for training
        for token, sc in sorted(scores.items(), key=lambda x: x[1]):
            if token not in {t for t, _, _ in top_results}:
                quote = quotes_map.get(token)
                if quote:
                    training_candidate = (token, sc, quote)
                    break

    selected_tokens = {t for t, _, _ in top_results}
    any_accepted = False

    def _format_amount(value, precision):
        if value is None or precision is None:
            return value
        q = Decimal("1") if int(precision) == 0 else Decimal("1." + "0" * int(precision))
        return format(Decimal(str(value)).quantize(q, rounding=ROUND_DOWN), "f")

    def _execute(to_token: str, score: float, quote: Dict) -> bool:
        quote["fromAmount"] = _format_amount(
            quote.get("fromAmount"), quote.get("fromAmountPrecision")
        )
        quote["toAmount"] = _format_amount(
            quote.get("toAmount"), quote.get("toAmountPrecision")
        )

        to_amt = float(quote.get("toAmount") or 0)
        if to_amt < MIN_CONVERT_TOAMOUNT:
            logger.info(
                f"[dev3] ❌ Пропуск через MIN_CONVERT_TOAMOUNT {MIN_CONVERT_TOAMOUNT}: {from_token} → {to_token}"
            )
            log_conversion_result(
                {**quote, "fromAsset": from_token, "toAsset": to_token},
                False,
                None,
                {"msg": "below MIN_CONVERT_TOAMOUNT"},
                None,
                None,
                quote.get("score"),
                None,
                step_str,
                min_str,
                px_str,
                est_str,
                "below MIN_CONVERT_TOAMOUNT",
            )
            return False

        if score < EXPLORE_MIN_EDGE:
            logger.info(
                f"[dev3] ❌ Пропуск через низький edge {score:.6f} < {EXPLORE_MIN_EDGE}"
            )
            log_conversion_result(
                {**quote, "fromAsset": from_token, "toAsset": to_token},
                False,
                None,
                {"msg": "below EXPLORE_MIN_EDGE"},
                None,
                None,
                quote.get("score"),
                None,
                step_str,
                min_str,
                px_str,
                est_str,
                "below EXPLORE_MIN_EDGE",
            )
            return False

        now = convert_api._current_timestamp()
        valid_until = int(quote.get("validTimestamp") or 0)
        if valid_until and now > valid_until:
            logger.warning(
                f"[dev3] ❌ Quote прострочено: {quote['quoteId']} для {from_token} → {to_token}"
            )
            quote = get_quote(from_token, to_token, amt, validTime=valid_time)
            valid_until = int(quote.get("validTimestamp") or 0)
            if valid_until and convert_api._current_timestamp() > valid_until:
                log_conversion_result(
                    {**quote, "fromAsset": from_token, "toAsset": to_token},
                    False,
                    None,
                    {"msg": "quote expired"},
                    None,
                    None,
                    quote.get("score"),
                    None,
                    step_str,
                    min_str,
                    px_str,
                    est_str,
                    "quote expired",
                )
                return False

        accept_result: Dict | None = None
        try:
            accept_result = accept_quote(quote["quoteId"])
        except Exception as error:  # pragma: no cover - network/IO
            logger.warning(
                f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {error}"
            )
            accept_result = {"code": None, "msg": str(error)}

        order_id = accept_result.get("orderId") if isinstance(accept_result, dict) else None
        order_status: Dict | None = None
        accepted = False
        error: Dict | None = None
        create_time = accept_result.get("createTime") if isinstance(accept_result, dict) else None

        if order_id:
            try:
                order_status = get_order_status(orderId=order_id)
                if order_status.get("orderStatus") == "SUCCESS":
                    accepted = True
                    quote["fromAmount"] = order_status.get("fromAmount", quote.get("fromAmount"))
                    quote["toAmount"] = order_status.get("toAmount", quote.get("toAmount"))
                else:
                    error = order_status
            except Exception as exc:  # pragma: no cover - network/IO
                error = {"msg": str(exc)}
        else:
            error = accept_result

        logger.info(
            f"[dev3] {'✅' if accepted else '❌'} Конверсія {from_token} → {to_token} (score={score:.4f})"
        )

        log_conversion_result(
            {**quote, "fromAsset": from_token, "toAsset": to_token},
            accepted,
            order_id,
            error,
            create_time,
            order_status,
            quote.get("score"),
            None,
            step_str,
            min_str,
            px_str,
            est_str,
            None,
        )
        return accepted

    for to_token, score, quote in top_results:
        if _execute(to_token, score, quote):
            any_accepted = True

    if training_candidate:
        to_token, score, quote = training_candidate
        selected_tokens.add(to_token)
        if _execute(to_token, score, quote):
            any_accepted = True

    for to_token in to_tokens:
        if to_token in selected_tokens:
            continue
        quote = quotes_map.get(to_token)
        if quote:
            log_conversion_result(
                {**quote, "fromAsset": from_token, "toAsset": to_token},
                False,
                None,
                None,
                None,
                None,
                quote.get("edge"),
                None,
                step_str,
                min_str,
                px_str,
                est_str,
                None,
            )

    log_cycle_summary()
    logger.info("[dev3] ✅ Цикл завершено")
    return any_accepted
