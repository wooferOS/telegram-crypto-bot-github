from __future__ import annotations

from pathlib import Path
import json

from utils_dev3 import assert_config_only_credentials
assert_config_only_credentials()
from config_dev3 import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    TELEGRAM_TOKEN,
    CHAT_ID,
)

MIN_QUOTE_DEFAULT = 11.0


def load_top_pairs(path: str = "top_tokens.json") -> list[dict]:
    p = Path(path)
    if not p.exists():
        p = Path("logs") / "top_tokens.json"
    data = json.loads(p.read_text())

    out: list[dict] = []
    for x in data:
        norm = {
            "from": (x.get("from") or x.get("from_token") or "").upper(),
            "to": (x.get("to") or x.get("to_token") or "USDT").upper(),
            "wallet": (x.get("wallet") or "SPOT").upper(),
            "score": float(x.get("score") or 0.0),
            "prob": float(x.get("prob") or x.get("prob_up") or 0.0),
            "edge": float(x.get("edge") or x.get("expected_profit") or 0.0),
        }
        amt = (
            x.get("amount_quote")
            or x.get("quote_amount")
            or x.get("amountQuote")
            or x.get("amount")
            or 0.0
        )
        try:
            amt = float(amt)
        except Exception:
            amt = 0.0
        if amt <= 0:
            amt = MIN_QUOTE_DEFAULT
        norm["amount_quote"] = amt
        out.append(norm)
    return out
