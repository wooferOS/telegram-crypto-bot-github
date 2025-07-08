import atexit
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

import requests
from config_dev3 import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN


_current_from_token: Optional[str] = None
_pending: Dict[str, List[str]] = defaultdict(list)


def flush_failures() -> None:
    """Send aggregated failure message for the current FROM token."""
    global _current_from_token, _pending
    if not _current_from_token or not _pending:
        return
    if len(_pending) == 1:
        reason, tokens = next(iter(_pending.items()))
        tokens_str = ", ".join(tokens)
        msg = (
            f"[dev3] ❌ Відхилено {_current_from_token} → [{tokens_str}]\n"
            f"Причина: {reason}"
        )
    else:
        lines = [f"[dev3] ❌ Відхилено {_current_from_token}"]
        for reason, tokens in _pending.items():
            tokens_str = ", ".join(tokens)
            lines.append(f"- [{tokens_str}] → {reason}")
        msg = "\n".join(lines)
    _send(msg)
    _current_from_token = None
    _pending = defaultdict(list)


atexit.register(flush_failures)


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


def send_telegram(text: str) -> None:
    """Simple helper to send raw Telegram messages."""
    _send(text)


def notify_success(from_token: str, to_token: str, amount: float, to_amount: float, score: float, expected_profit: float) -> None:
    if _current_from_token and from_token != _current_from_token:
        flush_failures()
    msg = (
        f"[dev3] ✅ Convert {from_token} → {to_token}\n"
        f"🔸 Кількість: {amount} {from_token}\n"
        f"🔹 Отримано: ≈{to_amount} {to_token}\n"
        f"📈 Прогноз: {expected_profit:+.1%} (score: {score:.3f})"
    )
    _send(msg)


def notify_failure(from_token: str, to_token: str, reason: str) -> None:
    global _current_from_token, _pending
    if _current_from_token and from_token != _current_from_token:
        flush_failures()
    _current_from_token = from_token
    _pending[reason].append(to_token)
