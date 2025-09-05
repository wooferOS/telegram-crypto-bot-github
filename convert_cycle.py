import os
from decimal import Decimal, ROUND_DOWN
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
from quote_counter import can_request_quote, should_throttle, reset_cycle


# Allow executing quotes with low score for model training
allow_learning_quotes = True

MIN_CONVERT_TOAMOUNT = float(os.getenv("MIN_CONVERT_TOAMOUNT", "0"))
EXPLORE_MIN_EDGE = float(os.getenv("EXPLORE_MIN_EDGE", "0"))



def process_pair(from_token: str, to_tokens: List[str], amount: float, score_threshold: float) -> bool:
    logger.info(f"[dev3] 🔍 Аналіз для {from_token} → {len(to_tokens)} токенів")
    quotes_map: Dict[str, Dict] = {}
    scores: Dict[str, float] = {}
    all_tokens: Dict[str, Dict] = {}
    skipped_pairs: List[Tuple[str, float, str]] = []  # (token, score, reason)

    reset_cycle()

    step_size, min_notional = load_symbol_filters(from_token, "USDT")
    if step_size is None and min_notional is None:
        logger.warning("[dev3] ⚠️ Немає LOT_SIZE/MIN_NOTIONAL для %sUSDT", from_token)
    if step_size and step_size > 0:
        amount = (
            Decimal(str(amount)) / step_size
        ).to_integral_value(rounding=ROUND_DOWN) * step_size
    else:
        amount = Decimal(str(amount))
    px = get_last_price_usdt(from_token)
    if px is None:
        logger.warning("[dev3] ⚠️ Не вдалося отримати ціну %sUSDT", from_token)
    est_notional = (amount * px) if px is not None else None
    step_str = str(step_size) if step_size is not None else None
    min_str = str(min_notional) if min_notional is not None else None
    px_str = str(px) if px is not None else None
    est_str = str(est_notional) if est_notional is not None else None
    mode = "paper" if os.getenv("PAPER", "0") == "1" or os.getenv("ENABLE_LIVE", "0") != "1" else "live"

    for to_token in to_tokens:
        if min_notional and min_notional > 0 and est_notional is not None and est_notional < min_notional:
            logger.info(
                "[dev3] skip(minNotional): %s amount=%s px=%s est=%s < %s",
                from_token,
                amount,
                px,
                est_notional,
                min_notional,
            )
            log_conversion_result(
                {"fromAsset": from_token, "toAsset": to_token, "fromAmount": str(amount)},
                False,
                None,
                {"msg": "below MIN_NOTIONAL"},
                None,
                False,
                None,
                mode,
                None,
                None,
                step_str,
                min_str,
                px_str,
                est_str,
                "skip(minNotional)",
            )
            continue
        if should_throttle(from_token, to_token):
            skipped_pairs.append((to_token, 0.0, "throttled"))
            break

        quote = get_quote(from_token, to_token, float(amount))

        if should_throttle(from_token, to_token, quote):
            break

        if not quote or "ratio" not in quote or "quoteId" not in quote:
            logger.warning(
                f"[dev3] ❌ Не вдалося отримати коректний quote для {from_token} → {to_token}"
            )
            skipped_pairs.append((to_token, 0.0, "ratio_unavailable"))
            continue

        score = float(quote.get("score", 0))
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

    mode = "paper" if os.getenv("PAPER", "0") == "1" or os.getenv("ENABLE_LIVE", "0") != "1" else "live"

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

        now = convert_api._current_timestamp()
        valid_until = int(quote.get("validTimestamp") or 0)
        if valid_until and now > valid_until:
            logger.warning(
                f"[dev3] ❌ Quote прострочено: {quote['quoteId']} для {from_token} → {to_token}"
            )
            log_conversion_result(
                {**quote, "fromAsset": from_token, "toAsset": to_token},
                False,
                None,
                {"msg": "quote expired"},
                None,
                False,
                None,
                mode,
                quote.get("score"),
            )
            return False

        accept_result: Dict | None = None
        try:
            accept_result = accept_quote(quote["quoteId"])
        except Exception as error:  # pragma: no cover - network/IO
            logger.warning(
                f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {error}"
            )
            log_conversion_result(
                {**quote, "fromAsset": from_token, "toAsset": to_token},
                False,
                None,
                {"msg": "below MIN_CONVERT_TOAMOUNT"},
                None,
                False,
                None,
                mode,
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
                False,
                None,
                mode,
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
            log_conversion_result(
                {**quote, "fromAsset": from_token, "toAsset": to_token},
                False,
                None,
                {"msg": "quote expired"},
                None,
                False,
                None,
                mode,
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
        dry_run = os.getenv("PAPER", "0") == "1"
        if dry_run:
            logger.info(
                "[dev3] DRY-RUN: acceptQuote skipped for %s", quote["quoteId"]
            )
            accept_result = {"dryRun": True}
        else:
            try:
                accept_result = accept_quote(quote["quoteId"])
            except Exception as error:  # pragma: no cover - network/IO
                logger.warning(
                    f"[dev3] ❌ Помилка під час accept_quote: {quote['quoteId']} — {error}"
                )
                accept_result = {"code": None, "msg": str(error)}

        order_id = accept_result.get("orderId") if isinstance(accept_result, dict) else None
        dry_run = bool(accept_result.get("dryRun")) if isinstance(accept_result, dict) else False
        order_status: Dict | None = None
        accepted = False
        error: Dict | None = None
        create_time = accept_result.get("createTime") if isinstance(accept_result, dict) else None

        if order_id and not dry_run:
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
            if not dry_run:
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
            dry_run,
            order_status,
            mode,
            quote.get("score"),
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
                False,
                None,
                mode,
                quote.get("score"),
            )

    logger.info("[dev3] ✅ Цикл завершено")
    return any_accepted
