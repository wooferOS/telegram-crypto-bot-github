import json
import os
import time
import re
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from json_sanitize import safe_load_json

try:  # Optional config overrides
    from config_dev3 import BINANCE_BASE_URL as _CFG_BASE_URL, USE_BINANCE_US
except Exception:  # pragma: no cover - optional config
    _CFG_BASE_URL = ""
    USE_BINANCE_US = False

# Base URL resolution with US flag handling
logger = logging.getLogger("dev3")
BINANCE_BASE_URL = _CFG_BASE_URL or (
    "https://api.binance.us" if USE_BINANCE_US else "https://api.binance.com"
)

# Convert may be unavailable on Binance US
CONVERT_ENABLED = True
if USE_BINANCE_US and not _CFG_BASE_URL:
    logger.warning(
        "[dev3] ⚠️ Binance US selected; Convert API may be unavailable"
    )
    CONVERT_ENABLED = False

# ---- Конфіг нормалізації активів для Convert (без хардкоду) ----
_ASSET_CFG_PATH = "convert_assets_config.json"
_asset_aliases: Dict[str, str] = {}
_asset_alias_regex: List[Dict[str, str]] = []  # [{"pattern": "...", "replace": "..."}]
_unsupported_assets: set[str] = set()


def _load_asset_cfg():
    global _asset_aliases, _asset_alias_regex, _unsupported_assets
    if not os.path.exists(_ASSET_CFG_PATH):
        _asset_aliases = {}
        _asset_alias_regex = []
        _unsupported_assets = set()
        return
    try:
        data = safe_load_json(_ASSET_CFG_PATH) or {}
        _asset_aliases = {k.upper(): v.upper() for k, v in (data.get("aliases", {}) or {}).items()}
        _asset_alias_regex = data.get("alias_regex", []) or []
        _unsupported_assets = set(a.upper() for a in (data.get("unsupported", []) or []))
    except Exception:
        # У разі помилки — працюємо з порожньою конфігурацією
        _asset_aliases = {}
        _asset_alias_regex = []
        _unsupported_assets = set()


_load_asset_cfg()


def to_convert_asset(symbol: str) -> str:
    """
    Уніфікатор назви активу для Convert:
    1) точні відповідності (aliases),
    2) regex-маски (alias_regex),
    3) дефолт — верхній регістр без змін.
    """
    s = (symbol or "").upper()
    if not s:
        return s
    # 1) точний alias
    if s in _asset_aliases:
        return _asset_aliases[s]
    # 2) regex-маски (універсально, без хардкоду)
    for rule in _asset_alias_regex:
        pat = rule.get("pattern")
        rep = rule.get("replace", "")
        if pat:
            try:
                ns = re.sub(pat, rep, s)
                if ns != s:
                    s = ns
                    break
            except re.error:
                continue
    return s


def is_convert_supported_asset(symbol: str) -> bool:
    """Чи не заборонений актив у Convert (навіть якщо аналізуємо його на СПОТ)."""
    s = (symbol or "").upper()
    return bool(s) and s not in _unsupported_assets


def mark_convert_unsupported(symbol: str):
    """Динамічно додати актив до unsupported (без редагування коду)."""
    s = (symbol or "").upper()
    if s:
        _unsupported_assets.add(s)


def safe_float(val: Any) -> float:
    """Return float value, handling nested dicts like {"value": x}."""
    if isinstance(val, dict):
        if "value" in val:
            val = val.get("value")
        elif "predicted" in val:
            val = val.get("predicted")
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def normalize_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    return symbol.upper().replace("USDT", "")


def round_step_size(value: float, step: float) -> float:
    step_dec = Decimal(str(step))
    return float((Decimal(str(value)) // step_dec) * step_dec)


def format_amount(amount: float, precision: int = 6) -> str:
    return f"{amount:.{precision}f}".rstrip('0').rstrip('.')


def load_json(path: str) -> list | dict:
    if os.path.exists(path):
        try:
            return safe_load_json(path)
        except Exception:
            return [] if path.endswith(".json") else {}
    return [] if path.endswith(".json") else {}


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_current_timestamp() -> int:
    return int(time.time() * 1000)


# Єдине місце визначення шляху історії конверсій
HISTORY_PATH = Path("convert_history.json")


def safe_json_load(path: str | Path, default: Any) -> Any:
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return default
        return safe_load_json(p)
    except Exception:
        return default


def safe_json_dump(path: str | Path, data: Any) -> None:
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
