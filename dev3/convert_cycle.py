from typing import Dict, Any

from convert_api import get_quote, accept_quote
from convert_model import predict
from convert_filters import check_filters
from convert_logger import log_trade, logger
from convert_notifier import notify_success, notify_failure
from config_dev3 import CONVERT_SCORE_THRESHOLD


def process_pair(from_token: str, to_token: str, amount: float) -> Dict[str, Any]:
    quote = get_quote(from_token, to_token, amount)
    expected_profit, prob_up, score = predict(from_token, to_token, quote)
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
        notify_failure(from_token, to_token, "низький score")
        data["accepted"] = False
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
