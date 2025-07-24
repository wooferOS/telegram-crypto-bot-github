import os
import glob
import subprocess
import json

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
    # [dev3] Не видаляємо top_tokens.json на початку трейд-циклу, бо файл
    # створюється в GPT-етапі за годину до трейду
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
    try:
        with open("top_tokens.json") as f:
            top_tokens = json.load(f)
        if top_tokens:
            process_top_pairs(top_tokens)
        else:
            logger.warning("[dev3] ⛔️ Файл top_tokens.json порожній. Пропускаємо трейд.")
    except Exception as e:
        logger.error(f"[dev3] ❌ Помилка при завантаженні top_tokens.json: {e}")
        return
    cleanup()
    logger.info("[dev3] ✅ Цикл завершено")

    # 🧠 Автоматичне навчання моделі
    logger.info("[dev3] 📚 Починаємо автоматичне навчання моделі...")
    try:
        subprocess.run(["python3", "train_convert_model.py", "--force-train"], check=True)
    except Exception as exc:
        logger.error(f"[dev3] ❌ Навчання моделі завершилось з помилкою: {exc}")
        return
    logger.info("[dev3] ✅ Навчання завершено")

    predictions_path = os.path.join("logs", "predictions.json")
    if os.path.exists(predictions_path):
        try:
            os.remove(predictions_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
