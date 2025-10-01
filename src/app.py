import logging
from typing import Literal

Phase = Literal["pre-analyze", "analyze", "trade", "guard"]


def run(region: str, phase: Phase, dry_run: int = 0) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    logging.info("app.run(region=%s, phase=%s, dry_run=%s) — shim", region, phase, dry_run)
    return 0
