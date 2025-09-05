import logging
import os
import json
from datetime import datetime

LOG_FILE = os.path.join("logs", "convert_trade.log")
DEBUG_LOG_FILE = os.path.join("logs", "convert_debug.log")
ERROR_LOG_FILE = os.path.join("logs", "convert_errors.log")
BALANCE_LOG_FILE = os.path.join("logs", "balance_guard.log")


os.makedirs("logs", exist_ok=True)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

logger = logging.getLogger("convert")
logger.setLevel(logging.INFO)

if not any(
    isinstance(h, logging.FileHandler) and h.baseFilename.endswith("convert_trade.log")
    for h in logger.handlers
):
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

if not any(
    isinstance(h, logging.FileHandler) and h.baseFilename.endswith("convert_debug.log")
    for h in logger.handlers
):
    dh = logging.FileHandler(DEBUG_LOG_FILE, encoding="utf-8")
    dh.setFormatter(formatter)
    dh.setLevel(logging.DEBUG)
    logger.addHandler(dh)

if not any(isinstance(h, logging.FileHandler) and h.baseFilename.endswith("convert_errors.log") for h in logger.handlers):
    eh = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")
    eh.setFormatter(formatter)
    eh.setLevel(logging.WARNING)
    logger.addHandler(eh)

if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    logger.addHandler(logging.StreamHandler())

balance_logger = logging.getLogger("balance_guard")
balance_logger.setLevel(logging.INFO)
if not any(
    isinstance(h, logging.FileHandler) and h.baseFilename.endswith("balance_guard.log")
    for h in balance_logger.handlers
):
    bh = logging.FileHandler(BALANCE_LOG_FILE, encoding="utf-8")
    bh.setFormatter(formatter)
    balance_logger.addHandler(bh)

# Summary logger for overall cycle results
summary_logger = logging.getLogger("summary")
summary_handler = logging.FileHandler("logs/convert_summary.log")
summary_handler.setFormatter(formatter)
summary_logger.addHandler(summary_handler)
summary_logger.setLevel(logging.INFO)


def log_trade(data: dict) -> None:
    logger.info(
        "[dev3] quote_id=%s from=%s to=%s ratio=%s accepted=%s error=%s response=%s",
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


def log_conversion_result(
    quote: dict,
    accepted: bool,
    order_id: str | None = None,
    error: dict | None = None,
    create_time: int | None = None,
    dry_run: bool = False,
    order_status: dict | None = None,
    mode: str | None = None,
    edge: float | None = None,
    region: str | None = None,
) -> None:
    """Log conversion result to history using the new unified schema."""

    if mode is None:
        mode = "paper" if os.getenv("PAPER", "0") == "1" or os.getenv("ENABLE_LIVE", "0") != "1" else "live"
    if region is None:
        region = os.getenv("REGION", "UNKNOWN")

    status = order_status.get("orderStatus") if isinstance(order_status, dict) else None

    entry = {
        "createTime": create_time,
        "region": region,
        "quoteId": quote.get("quoteId"),
        "fromAsset": quote.get("fromAsset"),
        "toAsset": quote.get("toAsset"),
        "fromAmount": str(quote.get("fromAmount")) if quote.get("fromAmount") is not None else None,
        "toAmount": str(quote.get("toAmount")) if quote.get("toAmount") is not None else None,
        "ratio": str(quote.get("ratio")) if quote.get("ratio") is not None else None,
        "inverseRatio": str(quote.get("inverseRatio")) if quote.get("inverseRatio") is not None else None,
        "validUntil": quote.get("validTimestamp") or quote.get("validTime"),
        "accepted": accepted,
        "orderId": order_id,
        "orderStatus": status,
        "error": error,
        "dryRun": dry_run,
        "edge": edge,
        "mode": mode,
    }

    logger.info(
        "[dev3] quoteId=%s -> accept_quote %s -> orderId=%s -> status=%s",
        entry["quoteId"],
        "\u2705" if accepted else "\u274c",
        order_id,
        status,
    )

    log_convert_history(entry)
