from __future__ import annotations

import random
import time
from decimal import Decimal, InvalidOperation
from typing import Any

# Єдина константа нуля для Decimal по всьому проєкту
DECIMAL_ZERO: Decimal = Decimal("0")


def now_ms() -> int:
    """Поточний час у мілісекундах (int)."""
    return int(time.time() * 1000)


def rand_jitter(
    base: float | int = 1.0,
    *,
    spread: float = 0.05,
    seed: int | None = None,
) -> float:
    """
    Повертає base * (1 + u), де u ~ U(-spread, +spread).
    Якщо seed задано — генерація детермінована.
    """
    rng = random.Random(seed) if seed is not None else random
    u = rng.uniform(-abs(spread), abs(spread))
    return float(base) * (1.0 + u)


def decimal_from_any(x: Any) -> Decimal:
    """
    Надійно перетворює int|float|str|Decimal|None -> Decimal.
    - float через str(x), щоб уникати FP-артефактів;
    - None -> Decimal('0').
    """
    if isinstance(x, Decimal):
        return x
    if x is None:
        return DECIMAL_ZERO
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return DECIMAL_ZERO
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"decimal_from_any: cannot parse {x!r}") from None
    try:
        return Decimal(str(x).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"decimal_from_any: cannot parse {x!r}") from None


def ensure_amount_and_limits(amount: Any, *args: Any, **kwargs: Any) -> Decimal:
    """
    Тимчасовий шім до повної реалізації:
    приводить amount до Decimal і повертає його як нормалізоване значення.
    Параметри *args/**kwargs залишені для сумісності існуючих викликів.
    """
    return decimal_from_any(amount)
