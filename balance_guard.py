import json
import os

from convert_api import get_balances
from convert_logger import balance_logger
from convert_notifier import notify_failure
from utils_dev3 import load_json

SNAPSHOT_FILE = "balance_snapshot.json"
THRESHOLD = 0.25


def load_snapshot() -> dict:
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_snapshot(data: dict) -> None:
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def check_balance() -> None:
    current = get_balances()
    total = sum(current.values())
    snapshot = load_snapshot()
    prev_total = snapshot.get("total", total)
    diff = total - prev_total

    history = load_json(os.path.join("logs", "convert_history.json"))
    last_trade = history[-1].get("timestamp", "N/A") if history else "N/A"

    if prev_total and diff < -prev_total * THRESHOLD:
        notify_failure("BALANCE", "USDT", "зменшення балансу >25%")

    balance_logger.info(
        "[dev3] Баланс перед=%.4f після=%.4f активи=%d остання_угода=%s",
        prev_total,
        total,
        len(current),
        last_trade,
    )
    save_snapshot({"total": total})


if __name__ == "__main__":
    check_balance()
