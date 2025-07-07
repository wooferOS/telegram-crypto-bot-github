import os
import glob
from typing import List

from convert_api import get_balances, get_available_to_tokens
from convert_cycle import process_pair
from convert_logger import logger
from utils_dev3 import load_json, save_json
from config_dev3 import CONVERT_SCORE_THRESHOLD

HISTORY_FILE = "convert_history.json"
CACHE_FILES = [
    "signals.txt",
    "last_message.txt",
    os.path.join("logs", "predictions.json"),
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


def main() -> None:
    logger.info("[dev3] 🔄 Запуск convert трейдингу")
    balances = get_balances()
    history: List[dict] = load_json(HISTORY_FILE) or []
    for token, amount in balances.items():
        tos = get_available_to_tokens(token)
        for to_asset in tos:
            result = process_pair(token, to_asset, amount)
            history.append(result)
    save_json(HISTORY_FILE, history)
    cleanup()
    logger.info("[dev3] ✅ Цикл завершено")

    import subprocess

    # 🔁 Автоматичне навчання моделі після завершення циклу
    try:
        logger.info("[dev3] 📚 Починаємо автоматичне навчання моделі...")
        subprocess.run(["python3", "train_convert_model.py"], check=True)
        logger.info("[dev3] ✅ Навчання завершено")
    except Exception as e:
        logger.warning(f"[dev3] ⚠️ Помилка під час навчання: {e}")


if __name__ == "__main__":
    main()
