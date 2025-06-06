import json
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)
ALERTS_FILE = os.getenv("ALERTS_FILE", "pending_alerts.json")


def _load_alerts() -> List[Dict]:
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to read alerts: %s", exc)
    return []


def _save_alerts(alerts: List[Dict]) -> None:
    try:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Failed to save alerts: %s", exc)


def record_forecast(tokens: List[str]) -> None:
    alerts = _load_alerts()
    alerts.append({"tokens": tokens, "timestamp": datetime.utcnow().isoformat(), "done": False})
    _save_alerts(alerts)


async def check_daily_alerts(bot, chat_id: int) -> None:
    alerts = _load_alerts()
    now = datetime.utcnow()
    updated = False
    for alert in alerts:
        if not alert.get("done") and datetime.fromisoformat(alert["timestamp"]) < now - timedelta(days=1):
            try:
                tokens = ", ".join(alert.get("tokens", []))
                await bot.send_message(chat_id, f"\u23F0 \u041D\u0430\u0433\u0430\u0434\u0443\u0454\u043C\u043E: {tokens} \u0431\u0435\u0437 \u0434\u0456\u0439")
                alert["done"] = True
                updated = True
            except Exception as exc:  # pragma: no cover - network call
                logger.error("Failed to send alert: %s", exc)
    if updated:
        _save_alerts(alerts)



def check_unconfirmed_actions() -> List[List[str]]:
    """Return tokens from alerts that haven't been confirmed yet."""
    alerts = _load_alerts()
    return [alert.get("tokens", []) for alert in alerts if not alert.get("done")]
