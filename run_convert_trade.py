import os
import glob
import subprocess

from convert_api import get_balances, get_available_to_tokens
from convert_cycle import process_pair
from convert_logger import logger
from config_dev3 import CONVERT_SCORE_THRESHOLD

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
    for token in balances.keys():
        tos = get_available_to_tokens(token)
        process_pair(token, tos, None, CONVERT_SCORE_THRESHOLD)
    cleanup()
    logger.info("[dev3] ✅ Цикл завершено")

    # 🧠 Автоматичне навчання моделі
    logger.info("[dev3] 📚 Починаємо автоматичне навчання моделі...")
    subprocess.run(["python3", "train_convert_model.py"], check=True)
    logger.info("[dev3] ✅ Навчання завершено")


if __name__ == "__main__":
    main()
