import requests
from typing import Iterable
from config_dev3 import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN


def _send(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def notify_success(from_token: str, to_token: str, amount: float, to_amount: float, score: float, expected_profit: float) -> None:
    msg = (
        f"[dev3] ✅ Convert {from_token} → {to_token}\n"
        f"🔸 Кількість: {amount} {from_token}\n"
        f"🔹 Отримано: ≈{to_amount} {to_token}\n"
        f"📈 Прогноз: {expected_profit:+.1%} (score: {score:.3f})"
    )
    _send(msg)


def notify_failure(from_token: str, to_token: str, reason: str) -> None:
    msg = (
        f"[dev3] ❌ Відхилено: {from_token} → {to_token}\n"
        f"Причина: {reason}"
    )
    _send(msg)
