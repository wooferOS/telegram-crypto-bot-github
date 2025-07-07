from typing import Dict, Any

from convert_api import get_quote, accept_quote
from convert_model import predict
from convert_filters import check_filters, is_duplicate_conversion
from convert_logger import log_trade, log_quote, logger
from convert_logger import log_convert_history
import json
from convert_notifier import notify_success, notify_failure
from config_dev3 import CONVERT_SCORE_THRESHOLD


def process_pair(from_token: str, to_token: str, amount: float) -> Dict[str, Any]:
    quote = get_quote(from_token, to_token, amount)
    log_quote(from_token, to_token, quote)
    expected_profit, prob_up, score = predict(from_token, to_token, quote)
    accepted = score >= CONVERT_SCORE_THRESHOLD
    log_convert_history({
        "from_token": from_token,
        "to_token": to_token,
        "score": score,
        "expected_profit": expected_profit,
        "prob_up": prob_up,
        "ratio": quote.get("ratio"),
        "from_amount": quote.get("fromAmount"),
        "to_amount": quote.get("toAmount"),
        "accepted": accepted,
    })
    data = {
        "from": from_token,
        "to": to_token,
        "amount": amount,
        "quote": quote,
        "quote_id": quote.get("quoteId"),
        "ratio": float(quote.get("ratio", 0)),
        "toAmount": float(quote.get("toAmount", 0)),
        "expected_profit": expected_profit,
        "prob_up": prob_up,
        "score": score,
    }
    if score < CONVERT_SCORE_THRESHOLD:
        logger.info(
            f"[dev3] \u274C Відмова: {from_token} → {to_token} — score {score:.4f} < threshold {CONVERT_SCORE_THRESHOLD}"
        )
        data["accepted"] = False
        data["error"] = "score"
        log_trade(data)
        return data

    if is_duplicate_conversion(from_token, to_token):
        logger.info(
            f"[dev3] \u274C Відмова: {from_token} → {to_token} — вже було конвертовано"
        )
        data["accepted"] = False
        data["error"] = "duplicate"
        log_trade(data)
        return data

    ok, reason = check_filters(data)
    if not ok:
        notify_failure(from_token, to_token, reason)
        data["accepted"] = False
        data["error"] = reason
        log_trade(data)
        return data

    resp = accept_quote(data["quote_id"])
    data["response"] = resp
    success = resp.get("status") == "success"
    data["accepted"] = success
    if success:
        notify_success(from_token, to_token, amount, data["toAmount"], score, expected_profit)
    else:
        notify_failure(from_token, to_token, "api_error")
    log_trade(data)
    return data
