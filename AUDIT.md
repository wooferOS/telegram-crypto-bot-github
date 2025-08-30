# Binance Convert API audit (dev3)

## Endpoints

| Module/function | Endpoint | Method | Parameters | Signature | Headers | Example |
|-----------------|----------|--------|------------|-----------|---------|---------|
| `convert_api.exchange_info` | `/sapi/v1/convert/exchangeInfo` | GET | `fromAsset?` | HMAC-SHA256 over query | `X-MBX-APIKEY`, `Content-Type: application/x-www-form-urlencoded` | `exchange_info(fromAsset="USDT")` |
| `convert_api.get_quote_with_id` | `/sapi/v1/convert/getQuote` | POST | `fromAsset, toAsset, fromAmount, walletType?` | HMAC-SHA256 over form body | same as above | `get_quote_with_id("USDT","BTC",10)` |
| `convert_api.accept_quote` | `/sapi/v1/convert/acceptQuote` | POST | `quoteId, walletType?` | HMAC-SHA256 | same as above | `accept_quote("12345")` |
| `convert_api.get_quote_status` | `/sapi/v1/convert/orderStatus` | GET | `orderId` | HMAC-SHA256 | same as above | `get_quote_status("67890")` |
| `convert_api.get_balances` | `/api/v3/account` | GET | none | HMAC-SHA256 | same | `get_balances()` |

## Rate limit / backoff

Requests use exponential backoff with jitter:

```
delay = min(0.5 * 2**(attempt-1), 30) + random(0, 0.25)
```

`Retry-After` header is honoured when provided.  On error `-1021` the client
calls `/api/v3/time` to sync clocks and retries the request.

## Top-tokens format (`v1`)

```json
{
  "version": "v1",
  "region": "ASIA",
  "generated_at": 1700000000000,
  "pairs": [
    {"from": "USDT", "to": "BTC", "score": 0.5, "edge": 0.1}
  ]
}
```

Files are written atomically with a `.lock` and temporary file to avoid
corruption.  Legacy formats (list or dict without `version`) are migrated on
read.

## DRY-RUN vs LIVE

`accept_quote` is executed only when `ENABLE_LIVE=1` **and** `PAPER=0`.
Otherwise it logs the skip and returns `{"dryRun": true}`.

