# Binance Convert API Audit

| Endpoint | Method | Required Params | Signature / Headers | Key Response Fields | Status | Doc Link |
|---|---|---|---|---|---|---|
| `/sapi/v1/convert/getQuote` | POST | `fromAsset`, `toAsset`, (`fromAmount` or `toAmount`), `walletType` optional | `timestamp`, `recvWindow`, HMAC SHA256 signature over query, header `X-MBX-APIKEY` | `quoteId`, `ratio`, `inverseRatio`, `fromAmount`, `toAmount` | OK | [Docs](https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-getQuote) |
| `/sapi/v1/convert/acceptQuote` | POST | `quoteId`, `walletType` optional | Signed query params and `X-MBX-APIKEY` header | `orderId`, `status`, `fromAsset`, `toAsset` | OK | [Docs](https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-acceptQuote) |
| `/sapi/v1/convert/orderStatus` | GET | `orderId` | Signed query params and `X-MBX-APIKEY` header | `orderId`, `status`, `fromAsset`, `toAsset` | OK | [Docs](https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-orderStatus) |
| `/sapi/v1/convert/exchangeInfo` | GET | optional `fromAsset`, `toAsset` | Signed query params and `X-MBX-APIKEY` header | `fromAssetList`/`toAssetList` | OK | [Docs](https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-exchangeInfo) |
| `/sapi/v1/convert/tradeFlow` | GET | `startTime`, optional `endTime`, `limit`, `fromAsset`, `toAsset` | Signed query params and `X-MBX-APIKEY` header | `list` of `quoteId`, `orderId`, `status` | OK | [Docs](https://developers.binance.com/docs/binance-spot-api-docs/sapi#convert-tradeFlow) |

All endpoints were checked against the official Binance Spot API documentation. Only minimal changes were needed: added explicit handling for error `-2015` and provided a wrapper for the `tradeFlow` endpoint.
