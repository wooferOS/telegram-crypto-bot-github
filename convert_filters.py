from __future__ import annotations
"""Utilities for normalising and validating trading pairs."""

REQUIRED_KEYS = ("from", "to", "amount_quote")


def _pair_has_required_fields(p: dict) -> bool:
    """Приймає як нові ключі (from/to/amount_quote), так і бексові (from_token/to_token/amount, amountQuote)."""
    from_sym = p.get("from") or p.get("from_token")
    to_sym = p.get("to") or p.get("to_token")
    # amount_quote може приходити під різними іменами
    amt = (
        p.get("amount_quote")
        or p.get("quote_amount")
        or p.get("amountQuote")
        or p.get("amount")
        or 0.0
    )
    try:
        amt = float(amt or 0.0)
    except Exception:
        amt = 0.0
    return bool(from_sym and to_sym and amt > 0)


DEFAULT_WALLET = "SPOT"
MIN_QUOTE_DEFAULT = 11.0  # щоб не було amount≈0.0


def normalize_pair(p: dict) -> dict:
    """Повертає пару у канонічному вигляді для конверта."""
    out = {
        "from": (p.get("from") or p.get("from_token") or "").upper(),
        "to": (p.get("to") or p.get("to_token") or "USDT").upper(),
        "wallet": (p.get("wallet") or DEFAULT_WALLET).upper(),
        "score": float(p.get("score") or 0.0),
        "prob": float(p.get("prob") or p.get("prob_up") or 0.0),
        "edge": float(p.get("edge") or p.get("expected_profit") or 0.0),
    }
    amt = (
        p.get("amount_quote")
        or p.get("quote_amount")
        or p.get("amountQuote")
        or p.get("amount")
        or 0.0
    )
    try:
        amt = float(amt)
    except Exception:
        amt = 0.0
    if amt <= 0:
        amt = MIN_QUOTE_DEFAULT
    out["amount_quote"] = amt
    return out
