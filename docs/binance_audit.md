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

| Endpoint    | Method | Path                          | Signed | Required params (location)                                  | Optional params (location)      | Key response fields                        | Notes |
|-------------|--------|-------------------------------|--------|--------------------------------------------------------------|---------------------------------|---------------------------------------------|-------|
| exchangeInfo| GET    | `/sapi/v1/convert/exchangeInfo`| No     | —                                                            | `fromAsset` (query), `toAsset` (query) | `fromAssetList`, `toAssetList`            | cached ~30 min |
| getQuote    | POST   | `/sapi/v1/convert/getQuote`   | **Yes**| `fromAsset` (body), `toAsset` (body), exactly one of `fromAmount`/`toAmount` (body)| `walletType` (body)            | `quoteId`, `ratio`, `inverseRatio`, `validTime` | — |
| acceptQuote | POST   | `/sapi/v1/convert/acceptQuote`| **Yes**| `quoteId` (body)                                              | `walletType` (body)             | `orderId`, `createTime`                     | — |
| orderStatus | GET    | `/sapi/v1/convert/orderStatus`| **Yes**| exactly one of `orderId` or `quoteId` (query)               | —                               | `orderStatus`, `fromAsset`, `toAsset`, `ratio`| params are mutually exclusive |
| tradeFlow   | GET    | `/sapi/v1/convert/tradeFlow`  | **Yes**| `startTime` (query), `endTime` (query)                       | `cursor` (query), `limit` (query) | `list`, `cursor`                            | pagination supported |

## Error handling and limits

* `-2015` → `PermissionError`
* `-1021` → `ClockSkewError` (timestamp drift)
* 418/429/`-1003` → minimal exponential backoff; no specialised throttling

## DRY‑RUN semantics

Local PAPER/DRY-RUN mode intentionally diverges from Binance behaviour:

* `accept_quote` does **not** call Binance and returns `{ "dryRun": true, "msg": "acceptQuote skipped in PAPER/DRY-RUN" }` without `orderId`.
* The conversion cycle treats such results as `accepted = False` and logs `dryRun = True` in `logs/convert_history.json`.

