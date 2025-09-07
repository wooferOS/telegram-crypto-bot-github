"""Helpers to reconcile convert trade history via Binance tradeFlow."""

from __future__ import annotations

import json
import os

import convert_api
from convert_logger import log_conversion_result


def _read_existing_ids(path: str) -> set[str]:
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            return {str(item.get('quoteId')) for item in data}
    except Exception:
        return set()


def sync_recent_trades(minutes: int = 15) -> int:
    """Fetch recent trades and ensure they exist in local history.

    Returns the number of new records appended.
    """
    end_ms = convert_api._current_timestamp()
    start_ms = end_ms - minutes * 60 * 1000
    try:
        resp = convert_api.trade_flow(startTime=start_ms, endTime=end_ms)
    except Exception:  # pragma: no cover - network
        return 0
    trades = resp.get('list', [])
    path = os.path.join('logs', 'convert_history.json')
    existing = _read_existing_ids(path)
    added = 0
    for item in trades:
        qid = item.get('quoteId')
        if not qid or qid in existing:
            continue
        quote = {
            'quoteId': qid,
            'fromAsset': item.get('fromAsset'),
            'toAsset': item.get('toAsset'),
            'fromAmount': item.get('fromAmount'),
            'toAmount': item.get('toAmount'),
        }
        status = item.get('status')
        log_conversion_result(
            quote,
            accepted=status == 'SUCCESS',
            order_id=item.get('orderId'),
            error=None,
            create_time=item.get('createTime'),
            order_status={'orderStatus': status},
            edge=None,
        )
        added += 1
    return added
