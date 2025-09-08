# DEV3 Final Production Audit

## 1. Summary
**Verdict:** Compliant – production configuration aligns with Binance Convert and Spot documentation. No gaps found.

## 2. API Surface Map
| Module / Function | Endpoint | Method | Required Params | Weight | Docs | Status |
|-------------------|----------|--------|-----------------|--------|------|--------|
| `convert_api.get_quote_with_id` | `/sapi/v1/convert/getQuote` | POST | `fromAsset`, `toAsset`, `fromAmount`/`toAmount`, `validTime`, `recvWindow`, `timestamp`, `signature` | 200 UID | [Send Quote](https://developers.binance.com/docs/convert/trade) | PASS |
| `convert_api.accept_quote` | `/sapi/v1/convert/acceptQuote` | POST | `quoteId`, `recvWindow`, `timestamp`, `signature` | 500 UID | [Accept Quote](https://developers.binance.com/docs/convert/trade/Accept-Quote) | PASS |
| `convert_api.get_order_status` | `/sapi/v1/convert/orderStatus` | GET | `orderId`/`quoteId`, `recvWindow`, `timestamp`, `signature` | 100 UID | [Order Status](https://developers.binance.com/docs/convert/trade/Order-Status) | PASS |
| `convert_api.trade_flow` | `/sapi/v1/convert/tradeFlow` | GET | `startTime`, `endTime`, `recvWindow`, `timestamp`, `signature` | 3000 UID | [Trade Flow](https://developers.binance.com/docs/convert/trade/Get-Convert-Trade-History) | PASS |
| `convert_api.exchange_info` | `/sapi/v1/convert/exchangeInfo` | GET | `fromAsset?` | 3000 IP | [Convert Market Data](https://developers.binance.com/docs/convert/market-data) | PASS |
| `convert_api.asset_info` | `/sapi/v1/convert/assetInfo` | GET | `asset` | 100 IP | [Asset Precision](https://developers.binance.com/docs/convert/market-data/Query-order-quantity-precision-per-asset) | PASS |
| `convert_api.get_balances` | `/sapi/v3/asset/getUserAsset` | POST | `needBtcValuation`, `recvWindow`, `timestamp`, `signature` | 5 IP | [User Asset](https://developers.binance.com/docs/wallet/asset/user-assets) | PASS |
| `md_rest.avg_price` | `/api/v3/avgPrice` | GET | `symbol` | 2 | [Market Data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api#current-average-price) | PASS |
| `md_rest.ticker_price` | `/api/v3/ticker/price` | GET | `symbol` | 2 (with `symbol`) / 4 (otherwise) | [Symbol price ticker](https://developers.binance.com/docs/binance-spot-api-docs/rest-api#symbol-price-ticker) | PASS |
| `md_rest.book_ticker` | `/api/v3/ticker/bookTicker` | GET | `symbol` | 2 | [Order book ticker](https://developers.binance.com/docs/binance-spot-api-docs/rest-api#symbol-order-book-ticker) | PASS |
| `md_rest.ticker_24hr` | `/api/v3/ticker/24hr` | GET | `symbol` or `symbols[]` | 2 / 40 / 80 | [24hr ticker](https://developers.binance.com/docs/binance-spot-api-docs/rest-api#24hr-ticker-price-change-statistics) | PASS |
| `md_rest.klines` | `/api/v3/klines` | GET | `symbol`, `interval`, `limit` | 2 | [Klines](https://developers.binance.com/docs/binance-spot-api-docs/rest-api#klinecandlestick-data) | PASS |
| `md_ws.MarketDataWS` | `wss://data-stream.binance.vision/stream` | WS | `streams` | – | [WebSocket Streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams) | PASS |

## 3. Execution Flow
1. Rounding and Min/Max from Convert `exchangeInfo` + `assetInfo` before quoting【F:exchange_filters.py†L10-L26】.
2. Amount rounded down to fraction and minNotional checked prior to `getQuote`【F:convert_cycle.py†L60-L110】.
3. `getQuote` returns `validTimestamp`; quote verified before `acceptQuote`【F:convert_cycle.py†L250-L274】.
4. Upon acceptance, `orderStatus` is queried; history reconciled via `trade_flow` ≤30d【F:convert_cycle.py†L276-L306】【F:convert_api.py†L305-L334】.

## 4. Security / Timing
* `timestamp` and `recvWindow` (default 5000 ms, capped at 60000 ms) added and HMAC‑SHA256 signed【F:convert_api.py†L86-L99】【F:config_dev3.py†L11-L12】.
* `_request` handles `-1021` with time resync and retry【F:convert_api.py†L118-L156】.

## 5. Market Data (REST / WS)
* All REST calls use `https://data-api.binance.vision`【F:md_rest.py†L1-L20】.
* Parameter-sensitive weights recorded (`ticker/24hr` 2/40/80, `ticker/price` 2/4, etc.)【F:md_rest.py†L46-L110】【F:quote_counter.py†L14-L40】.
* WebSocket manager enforces `wss://data-stream.binance.vision`, ≤5 msg/s, ping 20 s【F:md_ws.py†L1-L45】【F:md_ws.py†L72-L80】.

## 6. Rounding & Limits
* `assetInfo.fraction` converted to step size and applied with Decimal ROUND_DOWN【F:exchange_filters.py†L10-L26】【F:convert_cycle.py†L60-L70】.
* Min notional enforced before quoting【F:convert_cycle.py†L86-L110】.

## 7. Scoring / Mid‑reference / Risk‑off
* Spot mid reference via direct or synthetic bridges (`edge = (quote−mid)/mid`)【F:mid_ref.py†L1-L52】【F:scoring.py†L31-L75】.
* Risk-off reduces activity at >10 % drawdown and pauses at >25 %【F:convert_cycle.py†L42-L58】【F:risk_off.py†L66-L79】.

## 8. Rate / Weight‑Budget
* Official weights tracked in `quote_counter.WEIGHTS` and parameterised for `ticker/24hr`【F:quote_counter.py†L14-L40】.
* `should_throttle` guards daily and per-cycle quotas by count and weight【F:quote_counter.py†L125-L149】【F:convert_cycle.py†L111-L113】.

## 9. Prod‑Readiness
* Secrets/config only in `config_dev3.py`; no `.env`/`dotenv`/`os.getenv` found【F:config_dev3.py†L1-L18】【be2dae†L1-L7】.
* All endpoints point to production domains: Convert on `api.binance.com`, market data on `data-api.binance.vision`【F:convert_api.py†L36-L38】【F:md_rest.py†L1-L20】.

## 10. Tests Status
* `pytest` – 50 passed【cb720e†L1-L9】.

## 11. Gaps & Remediation
No gaps detected; code is production ready.

