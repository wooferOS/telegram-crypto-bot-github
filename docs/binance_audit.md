# Binance Convert API Audit

This document summarises how the project implements the Binance Spot Convert API
and verifies compliance with the official specification. References:
<https://developers.binance.com/docs/binance-spot-api-docs>.

## General API information

* **Base URL:** `https://api.binance.com`
* **Timestamp:** millisecond precision, appended to every SIGNED request.
* **recvWindow:** default `20000` ms if not supplied.
* **Signing:** parameters are URL‑encoded in order, then HMAC‑SHA256 signed with
  the secret key. Header `X-MBX-APIKEY` is sent only for SIGNED endpoints.
* **Error codes → exceptions**
  * `-1021` clock skew → time auto‑sync then `ClockSkewError` if still failing.
  * `-1022` invalid signature → `ValueError`.
  * `-1102`, `-1103` missing/invalid param → `ValueError`.
  * `-2015` permission/API key → `PermissionError`.
* **Rate limits:** responses `429`, `418` or code `-1003` trigger exponential
  backoff with jitter. Request weights follow Binance documentation.

## Endpoint summary

| Endpoint | Method | Path | Security | Required params | Optional params | Response fields | Pagination/Weights | Local deviation |
|---|---|---|---|---|---|---|---|---|
| exchangeInfo | GET | `/sapi/v1/convert/exchangeInfo` | PUBLIC | – | `fromAsset`, `toAsset` (query) | `fromAssetList`, `toAssetList` | weight 1, cached ~30 m | none |
| getQuote | POST | `/sapi/v1/convert/getQuote` | SIGNED | `fromAsset`, `toAsset`, **one of** `fromAmount` / `toAmount` | `walletType` | `quoteId`, `ratio`, `inverseRatio`, `toAmount`/`fromAmount`, `validTime` | weight 150 | – |
| acceptQuote | POST | `/sapi/v1/convert/acceptQuote` | SIGNED | `quoteId` | `walletType` | `orderId`, `createTime` | weight 150 | **DRY‑RUN:** returns `{"dryRun":true}` without contacting Binance |
| orderStatus | GET | `/sapi/v1/convert/orderStatus` | SIGNED | exactly one of `orderId` or `quoteId` | – | `orderStatus`, `ratio`, `fromAsset`, `toAsset`, amounts | weight 5 | parameters are mutually exclusive |
| tradeFlow | GET | `/sapi/v1/convert/tradeFlow` | SIGNED | `startTime`, `endTime` | `cursor`, `limit` | `list`, `cursor` | weight 30, cursor pagination | none |

### Sample

```
POST /sapi/v1/convert/getQuote
fromAsset=USDT&toAsset=BTC&fromAmount=10&recvWindow=20000&timestamp=...
```

Response:

```
{
  "quoteId": "123",
  "ratio": "0.00001",
  "inverseRatio": "100000",
  "toAmount": "0.0001",
  "validTime": 1699999999999
}
```

## General compliance

* Clock skew handling uses `/api/v3/time` and retries once.
* `accept_quote` is non‑idempotent and never retried automatically.
* `trade_flow` exposes cursor pagination to callers.
* Logs never include API secrets; history records follow a stable schema.

## Tests mapping

| Requirement | Test |
|---|---|
| Signature & headers | `tests/test_convert_api.py::test_get_quote_signed`, `::test_accept_quote_live` |
| Param validation | `tests/test_convert_api.py::test_get_quote_with_id_validation`, `::test_trade_flow_params` |
| Error mapping | `tests/test_convert_api.py::test_clock_skew_sync`, `::test_invalid_signature`, `::test_missing_param`, `::test_rate_limit_error`, `::test_permission_error` |
| DRY‑RUN semantics | `tests/test_convert_api.py::test_accept_quote_dry_run`, `tests/test_convert_cycle.py::test_accept_only_with_orderid` |
| Trade flow pagination | `tests/test_convert_api.py::test_trade_flow_pagination` |
| Exchange info caching | `tests/test_convert_api.py::test_exchange_info_cache` |
| History schema | `tests/test_history_schema.py` |

## Smoke run

### PAPER / DRY‑RUN

```bash
export PAPER=1 ENABLE_LIVE=0 PAPER_BALANCES="USDT=100"
python3 daily_analysis.py
jq 'length' logs/predictions.json           # > 0
python3 run_convert_trade.py
jq '[ .[] | select(.dryRun==true) ] | length' logs/convert_history.json   # > 0
grep -E '"accepted"\s*:\s*true' -n logs/convert_history.json || echo "OK: no accepted in DRY-RUN"
```

### LIVE (keys required)

```python
from convert_api import get_quote, trade_flow
get_quote("USDT", "BTC", 10)
trade_flow(startTime, endTime)
```

`accept_quote` should be invoked only after manual review.
