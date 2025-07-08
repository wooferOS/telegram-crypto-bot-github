import logging
import os
import json

LOG_FILE = os.path.join("logs", "trade_convert.log")
ERROR_LOG_FILE = os.path.join("logs", "convert_errors.log")
BALANCE_LOG_FILE = os.path.join("logs", "balance_guard.log")


os.makedirs("logs", exist_ok=True)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

logger = logging.getLogger("convert")
logger.setLevel(logging.INFO)

if not any(isinstance(h, logging.FileHandler) and h.baseFilename.endswith("trade_convert.log") for h in logger.handlers):
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

if not any(isinstance(h, logging.FileHandler) and h.baseFilename.endswith("convert_errors.log") for h in logger.handlers):
    eh = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")
    eh.setFormatter(formatter)
    eh.setLevel(logging.WARNING)
    logger.addHandler(eh)

if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    logger.addHandler(logging.StreamHandler())

# Summary logger for overall cycle results
summary_logger = logging.getLogger("summary")
summary_handler = logging.FileHandler("logs/convert_summary.log")
summary_handler.setFormatter(formatter)
summary_logger.addHandler(summary_handler)
summary_logger.setLevel(logging.INFO)


def log_trade(data: dict) -> None:
    logger.info(
        "quote_id=%s from=%s to=%s ratio=%s accepted=%s error=%s response=%s",
        data.get("quote_id"),
        data.get("from"),
        data.get("to"),
        data.get("ratio"),
        data.get("accepted"),
        data.get("error"),
        data.get("response"),
    )


def log_quote(from_token: str, to_token: str, quote_data: dict) -> None:
    logger.info(
        f"[dev3] \U0001F4E5 Quote {from_token} → {to_token}: {json.dumps(quote_data, indent=2)}"
    )


import os
import json
from datetime import datetime


def log_convert_history(entry: dict):
    """Append a single convert entry to logs/convert_history.json"""
    os.makedirs("logs", exist_ok=True)
    path = "logs/convert_history.json"

    if os.path.exists(path):
        with open(path, "r") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    else:
        history = []

    entry["timestamp"] = datetime.utcnow().isoformat()
    history.append(entry)

    with open(path, "w") as f:
        json.dump(history, f, indent=2)


def save_convert_history(entry: dict) -> None:
    """Alias for log_convert_history for backward compatibility."""
    log_convert_history(entry)


def log_conversion_result(quote: dict, accepted: bool) -> None:
    """Log conversion result to history."""
    entry = {
        "quoteId": quote.get("quoteId"),
        "from": quote.get("fromAsset"),
        "to": quote.get("toAsset"),
        "ratio": quote.get("ratio"),
        "inverseRatio": quote.get("inverseRatio"),
        "score": quote.get("score"),
        "expected_profit": quote.get("expected_profit"),
        "accepted": accepted,
    }
    log_convert_history(entry)
