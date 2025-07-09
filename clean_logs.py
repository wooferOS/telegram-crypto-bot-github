import os
import time
import logging

LOG_DIR = "logs"
DAYS = 3
logger = logging.getLogger("cleaner")
logging.basicConfig(level=logging.INFO)

def clean_logs_older_than(days: int):
    now = time.time()
    cutoff = now - (days * 86400)

    for filename in os.listdir(LOG_DIR):
        path = os.path.join(LOG_DIR, filename)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            try:
                os.remove(path)
                logger.info(f"[dev3] \U0001F9F9 \u0412\u0438\u0434\u0430\u043b\u0435\u043D\u043E: {filename}")
            except Exception as e:
                logger.warning(f"[dev3] \u274C \u041D\u0435 \u0432\u0434\u0430\u043B\u043E\u0441\u044F \u0432\u0438\u0434\u0430\u043B\u0438\u0442\u0438 {filename}: {e}")

if __name__ == "__main__":
    clean_logs_older_than(DAYS)
