import os
import glob
import subprocess

from convert_cycle import process_top_pairs
from convert_logger import logger
from quote_counter import can_request_quote

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
    top_tokens_path = os.path.join(os.path.dirname(__file__), "top_tokens.json")
    if os.path.exists(top_tokens_path):
        try:
            os.remove(top_tokens_path)
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
    logger.info("[dev3] 🔄 Запуск convert трейдингу")
    process_top_pairs()
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
