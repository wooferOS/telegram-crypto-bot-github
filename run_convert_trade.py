import glob
import subprocess

import os
from convert_api import get_balances, get_available_to_tokens
from convert_cycle import process_pair
from convert_logger import logger
from trade_history_sync import sync_recent_trades
from config_dev3 import CONVERT_SCORE_THRESHOLD, DEV3_REGION_TIMER
from quote_counter import can_request_quote
from top_tokens_utils import read_for_region

if not can_request_quote():
    logger.warning("[dev3] ⛔ Ліміт запитів до Convert API досягнуто. Пропускаємо цикл.")
    exit(0)

CACHE_FILES = [
    "signals.txt",
    "last_message.txt",
]


def cleanup() -> None:
    for path in CACHE_FILES:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    for temp in glob.glob(os.path.join("logs", "temp_*.json")):
        try:
            os.remove(temp)
        except OSError:
            pass
    for qfile in glob.glob(os.path.join("logs", "quote_*.json")):
        try:
            os.remove(qfile)
        except OSError:
            pass
    for log_path in glob.glob(os.path.join("logs", "*.log")):
        try:
            if os.path.getsize(log_path) > 5 * 1024 * 1024:
                os.remove(log_path)
        except OSError:
            pass


def main() -> None:
    cleanup()
    sync_recent_trades()
    logger.info("[dev3] 🔄 Запуск convert трейдингу")
    region = DEV3_REGION_TIMER
    # ensure top tokens file exists for region
    try:
        read_for_region(region)
    except Exception:
        pass
    balances = get_balances()
    for token, amount in balances.items():
        logger.info(f"[dev3] 🔄 Старт трейд-циклу для {token}")
        tos = get_available_to_tokens(token)
        success = process_pair(token, tos, amount, CONVERT_SCORE_THRESHOLD)
        if not success:
            logger.warning(
                "[dev3] ⚠️ Fallback: жодна пара не пройшла фільтри. Обираємо top 2 за ratio."
            )
    cleanup()
    logger.info("[dev3] ✅ Цикл завершено")

    # 🧠 Автоматичне навчання моделі
    logger.info("[dev3] 📚 Починаємо автоматичне навчання моделі...")
    subprocess.run(["python3", "train_convert_model.py"], check=True)
    logger.info("[dev3] ✅ Навчання завершено")

    predictions_path = os.path.join("logs", "predictions.json")
    if os.path.exists(predictions_path):
        try:
            os.remove(predictions_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
