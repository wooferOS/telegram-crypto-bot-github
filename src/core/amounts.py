from decimal import Decimal, ROUND_DOWN

def to_amount_str(amount: Decimal, places: int = 8) -> str:
    """
    Обрізає число вниз до places знаків і повертає рядок без експоненти.
    Convert API вимагає max 8 fraction для USDT (і загалом для fromAmount).
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    q = Decimal(10) ** -places
    d = amount.quantize(q, rounding=ROUND_DOWN)
    s = format(d, 'f')
    return s.rstrip('0').rstrip('.') or '0'
