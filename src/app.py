from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal
import os
import logging
from typing import Literal, List, Optional

from src.core import balance, binance_client
from src.strategy import selector

Phase = Literal["pre-analyze", "analyze", "trade", "guard"]

@dataclass
class BalanceSnapshot:
    log_dir: Path
    from_assets: List[str]

def _detect_from_assets() -> List[str]:
    # Мінімально достатньо мати USDT/USDC + кілька топових баз
    bases = ["USDT","USDC","BTC","ETH","BNB","SOL","XRP","DOGE","SUI","USDE"]
    present: List[str] = []
    for a in bases:
        try:
            if balance.read_free(a, "SPOT") > Decimal("0"):
                present.append(a)
        except Exception:
            pass
    # завжди гарантуємо наявність USDT/USDC
    for a in ("USDT","USDC"):
        if a not in present:
            present.append(a)
    return present

def _resolve_log_dir() -> Path:
    root = os.environ.get("DEV3_LOGDIR")
    if not root:
        # дефолтний шлях, як у попередніх логах
        root = f"/srv/dev3/logs/convert/{os.environ.get('UTC_DATE_OVERRIDE') or __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d')}"
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p

def run(region: str, phase: Phase, dry_run: Optional[bool] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # ## DRY-RESOLVE BEGIN
    # Resolve dry_run from env DEV3_DRY_RUN or config_dev3.DRY_RUN if not provided
    if dry_run is None:
        v = os.environ.get('DEV3_DRY_RUN')
        if v is not None:
            dry_run = v not in ('0','false','False')
        else:
            try:
                import config_dev3 as _cfg
            except Exception:
                _cfg = None
            dry_run = bool(getattr(_cfg, 'DRY_RUN', 1))
    logging.info('app.run(region=%s, phase=%s, dry_run=%s)', region, phase, dry_run)
    # ## DRY-RESOLVE END
    log = logging.getLogger(__name__)
    log.info("app.run(region=%s, phase=%s, dry_run=%s)", region, phase, dry_run)

    log_dir = _resolve_log_dir()
    snap = BalanceSnapshot(log_dir=log_dir, from_assets=_detect_from_assets())

    if phase == "analyze":
        # легкий «підігрів» API, щоб ранні помилки вилізли тут
        try:
            _ = binance_client.public_ticker_24hr(None)
        except Exception as e:
            log.warning("warmup public_ticker_24hr failed: %s", e)
        # виклик відбору кандидатів -> він сам запише summary/csv/json у snap.log_dir
        selector.select_candidates(region=region, snapshot=snap)
        log.info("analyze done; artifacts in %s", str(log_dir))
        return 0

    if phase in ("pre-analyze","guard"):
        log.info("%s: no-op for now", phase)
        return 0

    if phase == "trade":
        log.info("trade: dry path (no-op in this shim)")
        return 0

    log.error("unknown phase: %s", phase)
    return 1
