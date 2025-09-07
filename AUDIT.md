# Binance Convert API audit (dev3)

## Endpoints

| Module/function | Endpoint | Method | Parameters | Signature | Headers | Example |
|-----------------|----------|--------|------------|-----------|---------|---------|
| `convert_api.exchange_info` | `/sapi/v1/convert/exchangeInfo` | GET | `fromAsset?` | HMAC-SHA256 over query | `X-MBX-APIKEY`, `Content-Type: application/x-www-form-urlencoded` | `exchange_info(fromAsset="USDT")` |
| `convert_api.get_quote_with_id` | `/sapi/v1/convert/getQuote` | POST | `fromAsset, toAsset, fromAmount, walletType?` | HMAC-SHA256 over form body | same as above | `get_quote_with_id("USDT","BTC",10)` |
| `convert_api.accept_quote` | `/sapi/v1/convert/acceptQuote` | POST | `quoteId, walletType?` | HMAC-SHA256 | same as above | `accept_quote("12345")` |
| `convert_api.get_quote_status` | `/sapi/v1/convert/orderStatus` | GET | `orderId` | HMAC-SHA256 | same as above | `get_quote_status("67890")` |
| `convert_api.get_balances` | `/sapi/v3/asset/getUserAsset` | POST | `needBtcValuation=false` | HMAC-SHA256 | same | `get_balances()` |

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

## Requirement matrix

| Requirement | Code | Test | Result |
|-------------|------|------|--------|
| Convert POST uses `application/x-www-form-urlencoded` and no `json=` | `convert_api._request` / `_headers` | `tests/test_convert_api.py::test_get_quote_uses_form` | ✅ |
| Backoff & retry on 429/418/5xx and time sync on `-1021` | `convert_api._request` / `_backoff` / `_sync_time` | `tests/test_convert_api.py::test_backoff_on_429`, `test_time_sync_retry` | ✅ |
| Atomic top-token writes with locking and migration of legacy formats | `top_tokens_utils.write_top_tokens_atomic`, `migrate_legacy_if_needed` | `tests/test_top_tokens.py` | ✅ |

## Backoff and limits

* Exponential backoff with jitter implemented in `_backoff`.
* `quote_counter.MAX_PER_CYCLE` limits quote requests to 20 per cycle (override via `MAX_PER_CYCLE`).

## Normalisation & timers

* Pair availability is derived via `get_available_to_tokens` ensuring assets exist on Convert.
* `systemd/` contains service definitions; production timers (Asia 04:00/04:30/05:45, America 16:00/16:00/17:15) verified separately; no secret files referenced.


