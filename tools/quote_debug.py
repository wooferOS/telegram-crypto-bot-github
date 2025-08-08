#!/usr/bin/env python3
import sys
import json
from pathlib import Path

# Ensure repository root is in sys.path for module imports
sys.path.append(str(Path(__file__).resolve().parents[1]))

from convert_api import get_quote
from convert_filters import passes_filters
from convert_model import predict
from convert_logger import logger, safe_log
from utils_dev3 import safe_float


def main():
    if len(sys.argv) < 4:
        print("Usage: quote_debug.py FROM_TOKEN TO_TOKEN AMOUNT")
        sys.exit(1)
    f, t, a = sys.argv[1], sys.argv[2], float(sys.argv[3])
    q = get_quote(f, t, a)
    exp, prob, score = predict(f, t, q)
    ok, reason = passes_filters(score, q, a)
    logger.info(
        safe_log(
            f"[dev3] 🔍 quote_debug {f}->{t}: ok={ok}, reason={reason}, "
            f"score={score:.4f}, exp_profit={safe_float(exp):.4f}, quote={json.dumps(q, ensure_ascii=False)}"
        )
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "reason": reason,
                "score": float(score),
                "expected_profit": float(exp),
                "quote": q,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
