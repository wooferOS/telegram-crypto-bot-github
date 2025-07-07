import logging
import os
import json

LOG_FILE = os.path.join("logs", "trade_convert.log")
ERROR_LOG_FILE = os.path.join("logs", "convert_errors.log")
BALANCE_LOG_FILE = os.path.join("logs", "balance_guard.log")

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("convert")
logger.setLevel(logging.INFO)

if not any(isinstance(h, logging.FileHandler) and h.baseFilename.endswith("trade_convert.log") for h in logger.handlers):
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)

if not any(isinstance(h, logging.FileHandler) and h.baseFilename.endswith("convert_errors.log") for h in logger.handlers):
    eh = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")
    eh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    eh.setLevel(logging.WARNING)
    logger.addHandler(eh)

if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    logger.addHandler(logging.StreamHandler())


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
