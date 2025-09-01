# Binance Convert API Audit

This document summarises how the project implements the Binance Convert API and
highlights notable deviations from the official documentation.

## References

| Endpoint | Official documentation |
| --- | --- |
| `exchangeInfo` | https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-exchangeinfo |
| `getQuote` | https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-getquote |
| `acceptQuote` | https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-acceptquote |
| `orderStatus` | https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-orderstatus |
| `tradeFlow` | https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-tradeflow |

## Endpoint summary

| Endpoint | Method | Path | Signing | Params (req/opt) | Source | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| exchangeInfo | GET | `/sapi/v1/convert/exchangeInfo` | **None** | `fromAsset?`, `toAsset?` | query | cached for 30 min |
| getQuote | POST | `/sapi/v1/convert/getQuote` | **SIGNED** | `fromAsset`, `toAsset`, exactly one of `fromAmount`/`toAmount`, `walletType?` | body | returns `validTime` and pricing ratios |
| acceptQuote | POST | `/sapi/v1/convert/acceptQuote` | **SIGNED** | `quoteId`, `walletType?` | body | returns `orderId` and `createTime` |
| orderStatus | GET | `/sapi/v1/convert/orderStatus` | **SIGNED** | `orderId` **or** `quoteId` | query | params are mutually exclusive |
| tradeFlow | GET | `/sapi/v1/convert/tradeFlow` | **SIGNED** | `startTime`, `endTime`, `cursor?`, `limit?` | query | wrapper returns `{list, cursor}` for pagination |

## Error handling and limits

* `-2015` → `PermissionError`
* `-1021` → `ClockSkewError` (timestamp drift)
* 418/429/`-1003` → minimal exponential backoff; no specialised throttling

## DRY‑RUN semantics

Local PAPER/DRY-RUN mode intentionally diverges from Binance behaviour:

* `accept_quote` does **not** call Binance and returns `{"dryRun": true, ...}`
  without `orderId`.
* Conversions in this mode are logged with `accepted = False` and `dryRun = True`.

## Test status

* Branch: `dev3`, commit `26d64afc7c384a71cfb679f0dbe069e2fd5b17d3`
* `pytest -q` → 23 passed
* `PAPER=1 PAPER_BALANCES="USDT=100" python3 daily_analysis.py`
  produced non-empty `logs/predictions.json`
* `PAPER=1 PAPER_BALANCES="USDT=100" python3 run_convert_trade.py`
  produced only dry‑run entries in `logs/convert_history.json`

