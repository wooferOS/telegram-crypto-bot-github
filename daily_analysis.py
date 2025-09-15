import asyncio
import os
import sys
from typing import Dict, List

from convert_api import get_available_to_tokens, get_quote
from convert_logger import logger
from convert_model import predict
from utils_dev3 import save_json, get_current_timestamp
from top_tokens_utils import save_for_region, TOP_TOKENS_VERSION

try:
    from config_dev3 import DEV3_REGION_TIMER, MIN_NOTIONAL
except Exception as exc:  # pragma: no cover - config
    raise RuntimeError("Не знайдено config_dev3.py") from exc

ALLOWED_BASES = {"USDT", "BTC"}


def _parse_base(argv: List[str]) -> str:
    """Return base token from CLI arguments or exit with error."""
    if len(argv) < 2:
        raise SystemExit("Очікується база: USDT або BTC")
    base = argv[1].upper()
    if base not in ALLOWED_BASES:
        raise SystemExit("База має бути USDT або BTC")
    return base


async def gather_predictions(base: str, amount: float) -> List[Dict[str, float]]:
    """Отримати прогнози для всіх доступних пар з фіксованим from_token."""

    predictions: List[Dict[str, float]] = []
    try:
        to_tokens = await asyncio.to_thread(get_available_to_tokens, base)
        logger.info(f"[dev3] 📥 Доступні to_tokens для {base}: {to_tokens}")
    except Exception as exc:
        logger.warning(
            f"[dev3] ❌ get_available_to_tokens помилка для {base}: {exc}"
        )
        return predictions

    for to_token in to_tokens:
        try:
            quote = await asyncio.to_thread(get_quote, base, to_token, amount)
            logger.info(f"[dev3] 🔄 Quote для {base} → {to_token}: {quote}")
        except Exception as exc:
            logger.warning(
                f"[dev3] ❌ get_quote помилка для {base} → {to_token}: {exc}"
            )
            continue

        if not quote or "ratio" not in quote or "inverseRatio" not in quote:
            logger.warning(
                f"[dev3] ⛔️ Неповний quote для {base} → {to_token}: {quote}"
            )
            continue

        ratio = float(quote["ratio"])
        inverse_ratio = float(quote["inverseRatio"])

        base_expected_profit = ratio - 1.0
        base_prob_up = 0.5
        base_score = base_expected_profit * base_prob_up

        expected_profit, prob_up, score = predict(
            base,
            to_token,
            {
                "expected_profit": base_expected_profit,
                "prob_up": base_prob_up,
                "score": base_score,
                "ratio": ratio,
                "inverseRatio": inverse_ratio,
                "amount": amount,
            },
        )

        logger.info(
            f"[dev3] ✅ Прогноз: {base} → {to_token} | profit={expected_profit}, prob_up={prob_up}, score={score}"
        )

        predictions.append(
            {
                "from_token": base,
                "to_token": to_token,
                "ratio": ratio,
                "inverseRatio": inverse_ratio,
                "expected_profit": expected_profit,
                "prob_up": prob_up,
                "score": score,
            }
        )

    logger.info(f"[dev3] ✅ Загалом отримано {len(predictions)} прогнозів для {base}")
    return predictions

async def main() -> None:
    base = _parse_base(sys.argv)
    predictions = await gather_predictions(base, MIN_NOTIONAL)

    os.makedirs("logs", exist_ok=True)
    await asyncio.to_thread(save_json, os.path.join("logs", "predictions.json"), predictions)

    sorted_tokens = sorted(predictions, key=lambda x: x["score"], reverse=True)
    top_tokens = sorted_tokens[:5]
    region = "dev3"
    if not top_tokens:
        logger.warning(
            "[dev3] ❌ top_tokens порожній — відсутні релевантні прогнози"
        )
        return

    pairs = [
        {
            "from": base,
            "to": t["to_token"],
            "score": t.get("score"),
            "edge": t.get("expected_profit"),
        }
        for t in top_tokens
    ]

    data = {
        "version": TOP_TOKENS_VERSION,
        "region": region,
        "generated_at": get_current_timestamp(),
        "pairs": pairs,
    }
    await asyncio.to_thread(save_for_region, data, region)

    logger.info(
        f"[dev3] ✅ Аналіз завершено. Створено top_tokens для регіону {region} з {len(pairs)} записами."
    )
    try:
        from convert_api import _quota_blocked
        if '--mode' in sys.argv:
            i = sys.argv.index('--mode')
            if i+1 < len(sys.argv) and sys.argv[i+1] == 'convert' and _quota_blocked():
                print('[dev3] GPT: convert quota cached — skip heavy steps')
                raise SystemExit(0)
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
