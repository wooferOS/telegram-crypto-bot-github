import json
import os

from convert_api import get_balances
from convert_logger import logger
from convert_notifier import notify_failure

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
    if prev_total and diff < -prev_total * THRESHOLD:
        notify_failure("BALANCE", "USDT", "зменшення балансу >25%")
    logger.info("[dev3] Balance total=%s diff=%s", total, diff)
    save_snapshot({"total": total})


if __name__ == "__main__":
    check_balance()
