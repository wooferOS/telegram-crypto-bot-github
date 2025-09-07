from __future__ import annotations

import logging

from run_convert_trade import load_top_pairs
from convert_filters import normalize_pair, _pair_has_required_fields

log = logging.getLogger(__name__)


def convert_cycle(top_tokens_path: str = "top_tokens.json") -> None:
    """Process top trading pairs using common normalisation helpers."""
    top_pairs = load_top_pairs(top_tokens_path)
    for pair in top_pairs:
        pair = normalize_pair(pair)
        if not _pair_has_required_fields(pair):
            log.info("\u23ed\ufe0f  convert skipped: %s (reason=pair_fields_missing)", pair)
            continue

        amount_quote = pair["amount_quote"]
        from_sym = pair["from"]
        to_sym = pair["to"]
        wallet = pair["wallet"]
        log.debug(
            "Prepared pair for quote: %s/%s amount=%s wallet=%s", from_sym, to_sym, amount_quote, wallet
        )
        # Here you would call get_quote(..., amount_quote=amount_quote)


if __name__ == "__main__":
    convert_cycle()
