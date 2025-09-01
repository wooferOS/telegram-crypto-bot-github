from __future__ import annotations
import os
from typing import Dict, Tuple, List

from convert_logger import logger

HISTORY_FILE = os.path.join("logs", "convert_history.json")


def filter_top_tokens(
    all_tokens: Dict[str, Dict],
    score_threshold: float,
    top_n: int = 3,
) -> List[Tuple[str, Dict]]:
    """Return top tokens filtered by score."""

    filtered = [
        (token, data)
        for token, data in all_tokens.items()
        if data.get("score", 0) >= score_threshold
    ]
    filtered.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    if not filtered:
        logger.info(
            "[dev3] ❕ Немає токенів з високим score. Використовуємо навчальні угоди."
        )

    return filtered[:top_n]
