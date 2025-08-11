import logging
import os
import json
import sys
from datetime import datetime

from utils_dev3 import safe_json_load, safe_json_dump, HISTORY_PATH


def ensure_dir_exists(path: str) -> None:
    """Create directory if it doesn't exist."""
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

LOG_FILE = os.path.join("logs", "convert_trade.log")
DEBUG_LOG_FILE = os.path.join("logs", "convert_debug.log")
ERROR_LOG_FILE = os.path.join("logs", "convert_errors.log")
BALANCE_LOG_FILE = os.path.join("logs", "balance_guard.log")
HISTORY_FILE = str(HISTORY_PATH)
CONVERT_LOG_FILE = os.path.join("logs", "convert.log")


os.makedirs("logs", exist_ok=True)
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - safety
        pass


def safe_log(msg: str) -> str:
    try:
        return str(msg).encode("utf-8", "replace").decode("utf-8")
    except Exception:  # pragma: no cover - safety
        return str(msg)


def init_logger() -> logging.Logger:
    """Initialize and return the main convert logger."""
    os.makedirs("logs", exist_ok=True)
    log = logging.getLogger("convert")
    log.setLevel(logging.INFO)
    if not any(
        isinstance(h, logging.FileHandler)
        and h.baseFilename.endswith("convert.log")
        for h in log.handlers
    ):
        fh_main = logging.FileHandler(CONVERT_LOG_FILE, encoding="utf-8")
        fh_main.setFormatter(formatter)
        log.addHandler(fh_main)
    return log

logger = init_logger()

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
summary_handler = logging.FileHandler("logs/convert_summary.log", encoding="utf-8")
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
        safe_log(
            f"[dev3] \U0001F4E5 Quote {from_token} → {to_token}: {json.dumps(quote_data, indent=2)}"
        )
    )



def log_convert_history(entry: dict):
    """Append a single convert entry to HISTORY_FILE."""
    save_convert_history(entry)


def save_convert_history(entry: dict) -> None:
    """Persist convert history entry safely handling missing file."""
    history = safe_json_load(HISTORY_FILE, default=[])
    if not isinstance(history, list):
        history = []
    entry["timestamp"] = datetime.utcnow().isoformat()
    history.append(entry)
    safe_json_dump(HISTORY_FILE, history)


def log_conversion_result(quote: dict, accepted: bool) -> None:
    """Log conversion result to history and debug log."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "from": quote.get("fromAsset"),
        "to": quote.get("toAsset"),
        "fromAmount": quote.get("fromAmount"),
        "toAmount": quote.get("toAmount"),
        "accepted": accepted,
        "price": quote.get("price"),
        "ratio": quote.get("ratio"),
    }
    log_convert_history(entry)
    with open("logs/convert_debug.log", "a") as f:
        status = "ACCEPTED" if accepted else "REJECTED"
        f.write(f"[dev3] ✅ {status} {entry}\n")
    if accepted:
        logger.info(safe_log("✅ ACCEPTED"))


def log_prediction(from_token: str, to_token: str, score: float) -> None:
    """Log prediction score for a token pair."""
    logger.info(
        safe_log(f"[dev3] ✨ Прогноз {from_token} → {to_token} | score={score:.6f}")
    )


def log_quote_skipped(from_token: str, to_token: str, reason: str) -> None:
    """Log reason for skipping quote execution."""
    logger.info(
        safe_log(f"[dev3] ⏭ Пропуск {from_token} → {to_token}: {reason}")
    )


def log_conversion_success(from_token: str, to_token: str, profit: float) -> None:
    """Log successful conversion with profit."""
    logger.info(
        safe_log(
            f"[dev3] ✅ Конверсія {from_token} → {to_token} успiшна | profit={profit:.8f}"
        )
    )


def log_conversion_error(from_token: str, to_token: str, error: str) -> None:
    """Log conversion error."""
    logger.warning(
        safe_log(f"[dev3] ❌ Помилка конверсії {from_token} → {to_token}: {error}")
    )


def log_skipped_quotes() -> None:
    """Log that quote requests were skipped due to limit."""
    logger.warning(safe_log("[dev3] ⏸️ Достигнуто лiмiт запитiв get_quote за цикл"))


def log_error(message: str) -> None:
    """Log an error message to the main logger."""
    logger.error(message)
