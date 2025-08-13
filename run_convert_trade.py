import os
import glob
import subprocess
import json

from convert_cycle import process_top_pairs
from convert_logger import logger, safe_log
from convert_api import _sync_time
from quote_counter import can_request_quote
from utils_dev3 import safe_float

EXPLORE_MODE = int(os.getenv("EXPLORE_MODE", "0"))
EXPLORE_PAPER = int(os.getenv("EXPLORE_PAPER", "1"))
EXPLORE_MAX = int(os.getenv("EXPLORE_MAX", "2"))
EXPLORE_MIN_EDGE = float(os.getenv("EXPLORE_MIN_EDGE", "0.001"))
EXPLORE_MIN_LOT_FACTOR = float(os.getenv("EXPLORE_MIN_LOT_FACTOR", "0.5"))

logger.info(
    safe_log(
        f"[dev3] Explore: MODE={EXPLORE_MODE} PAPER={EXPLORE_PAPER} MAX={EXPLORE_MAX} "
        f"MIN_EDGE={EXPLORE_MIN_EDGE} MIN_LOT_FACTOR={EXPLORE_MIN_LOT_FACTOR}"
    )
)

if not can_request_quote():
    logger.warning(safe_log("[dev3] ⛔ Ліміт запитів до Convert API досягнуто. Пропускаємо цикл."))
    exit(0)

CACHE_FILES = [
    "signals.txt",
    "last_message.txt",
]


def _pick(d: dict, keys: list[str], default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def load_top_pairs(path: str) -> list[dict]:
    """Завантажує та нормалізує список пар із різними схемами ключів."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    norm = []
    for x in data:
        frm = _pick(x, ["from_token", "from_asset", "fromAsset", "from", "fromToken"])
        to = _pick(x, ["to_token", "to_asset", "toAsset", "to", "toToken"], "USDT")
        edge = _pick(x, ["edge", "expected_profit"], 0.0)
        prob = _pick(x, ["prob", "prob_up"], 0.0)
        score = float(_pick(x, ["score"], 0.0) or 0.0)
        wallet = _pick(x, ["wallet"], "SPOT")
        amt_q = _pick(x, ["amount_quote"], 11.0)
        norm.append(
            {
                **x,
                "from_token": frm,
                "to_token": to,
                "from": frm,
                "to": to,
                "edge": edge,
                "prob": prob,
                "score": score,
                "wallet": wallet or "SPOT",
                "amount_quote": float(amt_q)
                if isinstance(amt_q, (int, float, str))
                else 11.0,
            }
        )
    return norm


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
    _sync_time()
    logger.info(safe_log("[dev3] 🔄 Запуск convert трейдингу"))
    try:
        logger.info(safe_log("[dev3] 📄 Перевірка наявності файлу top_tokens.json..."))
        if not os.path.exists("top_tokens.json"):
            logger.warning(safe_log("[dev3] ⛔️ Файл top_tokens.json не знайдено. Завершуємо цикл."))
            return

        top_tokens = load_top_pairs("top_tokens.json")

        if not top_tokens:
            logger.warning(safe_log("[dev3] ⛔️ Файл top_tokens.json порожній. Пропускаємо трейд."))
            return

        logger.info(safe_log(f"[dev3] ✅ Завантажено {len(top_tokens)} пар з top_tokens.json"))
        all_zero = all(
            safe_float(item.get("gpt", {}).get("score", item.get("score", 0))) == 0
            and safe_float(item.get("expected_profit", 0)) == 0
            for item in top_tokens
        )
        if all_zero:
            logger.warning(safe_log("[dev3] ⚠️ top_tokens all zeros — GPT gating disabled"))
        config = {
            "mode": EXPLORE_MODE,
            "paper": EXPLORE_PAPER,
            "max": EXPLORE_MAX,
            "min_edge": EXPLORE_MIN_EDGE,
            "min_lot_factor": EXPLORE_MIN_LOT_FACTOR,
            "model_only": all_zero,
        }
        process_top_pairs(top_tokens, config)
    except Exception as e:
        logger.error(safe_log(f"[dev3] ❌ Помилка при завантаженні top_tokens.json: {e}"))
        return
    cleanup()
    logger.info(safe_log("[dev3] ✅ Цикл завершено"))

    # 🧠 Автоматичне навчання моделі
    logger.info(safe_log("[dev3] 📚 Починаємо автоматичне навчання моделі..."))
    try:
        subprocess.run(["python3", "train_convert_model.py", "--force-train"], check=True)
    except Exception as exc:
        logger.error(safe_log(f"[dev3] ❌ Навчання моделі завершилось з помилкою: {exc}"))
        return
    logger.info(safe_log("[dev3] ✅ Навчання завершено"))

    predictions_path = os.path.join("logs", "predictions.json")
    if os.path.exists(predictions_path):
        try:
            os.remove(predictions_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
