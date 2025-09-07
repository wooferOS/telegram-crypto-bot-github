# DEV3 Audit Report

## 1. Summary

DEV3 relies on Binance Convert endpoints for execution. Market data for analytics is pulled from public Spot REST URLs under `data-api.binance.vision`. Secrets are expected only in `config_dev3.py`. The implementation signs all Convert requests and checks quote validity before acceptance, supporting `validTime` enum (`10s`, `30s`, `1m`, default `10s`). However, environment variables (`os.getenv`) are used for runtime toggles, contrary to the requirement of avoiding `os.getenv` entirely. Dedicated risk-off logic tied to drawdown and market data was not found.

## 2. API Surface Map

| Module & Function | Endpoint | Method | Parameters | Weight* | Doc Ref | Status |
|-------------------|----------|--------|------------|--------|---------|--------|
| `convert_api.exchange_info` | `/sapi/v1/convert/exchangeInfo` | GET | `fromAsset?` | 3000/IP | [Convert Market Data][6] | Pass |
| `convert_api.asset_info` | `/sapi/v1/convert/assetInfo` | GET | `asset` | 100/IP | [Query order quantity precision per asset][7] | Pass |
| `convert_api.get_quote_with_id` | `/sapi/v1/convert/getQuote` | POST | `fromAsset`, `toAsset`, one of `fromAmount`/`toAmount`, `walletType?`, `recvWindow`, `timestamp`, `signature` | 200/UID | [Send quote request][1] | Pass |
| `convert_api.accept_quote` | `/sapi/v1/convert/acceptQuote` | POST | `quoteId`, `walletType?`, `recvWindow`, `timestamp`, `signature` | 500/UID | [Accept Quote][3] | Pass |
| `convert_api.get_order_status` | `/sapi/v1/convert/orderStatus` | GET | `orderId`/`quoteId`, `recvWindow`, `timestamp`, `signature` | 100/UID | [Order Status][4] | Pass |
| `convert_api.trade_flow` | `/sapi/v1/convert/tradeFlow` | GET | `startTime`, `endTime`, `cursor?`, `limit?`, `recvWindow`, `timestamp`, `signature` | 3000/UID | [Get Convert Trade History][5] | Pass |
| `convert_api.get_balances` | `/sapi/v3/asset/getUserAsset` | POST | `needBtcValuation` | 5/IP | [User Asset][12] | Pass |
| `binance_api.get_historical_prices` | `/api/v3/klines` (Market Data URL) | GET | `symbol`, `interval`, `limit` | 2 | [Market Data endpoints][2] | Pass |
| `exchange_filters.get_last_price_usdt` | `/api/v3/ticker/price` (Market Data URL) | GET | `symbol` | 1 | [Market Data endpoints][2] | Pass |

### Convert Weights (per docs)
`getQuote` 200(UID), `acceptQuote` 500(UID), `orderStatus` 100(UID), `tradeFlow` 3000(UID), `exchangeInfo` 3000(IP), `assetInfo` 100(IP).

*Weights per Binance documentation.*

### Timing Security
`timestamp` + `recvWindow` (default 5000, max 60000). Retry on `-1021` with time sync per [Request Security][8].

## 3. Execution Flow

`convert_cycle.process_pair` gathers candidate pairs, retrieves quotes, checks their validity and submits conversions:

1. `get_quote` → `get_quote_with_id` sends `POST /sapi/v1/convert/getQuote` and records quote usage【F:convert_api.py†L225-L250】.
2. Validity: current time vs `validTimestamp` is checked before acceptance【F:convert_cycle.py†L220-L243】.
3. `accept_quote` posts to `/sapi/v1/convert/acceptQuote` and then polls `/sapi/v1/convert/orderStatus` for final status【F:convert_cycle.py†L245-L276】.
4. Recent trades are reconciled via `/sapi/v1/convert/tradeFlow` in `trade_history_sync.sync_recent_trades`【F:trade_history_sync.py†L18-L27】.

## 4. Market‑Data Analytics

Public Spot endpoints under `https://data-api.binance.vision` provide analytics data with no API key:

- Exchange info and klines for symbol validation and pricing【F:binance_api.py†L5-L47】.
- Ticker price for last‑trade reference【F:exchange_filters.py†L18-L56】.
A repository‑wide search shows no Spot trading endpoints such as `POST /api/v3/order`【465ecf†L1-L2】.

## 5. Security (SIGNED)

Convert requests add `recvWindow`, `timestamp`, and HMAC‑SHA256 signatures via `_sign`【F:convert_api.py†L82-L99】. `_request` retries on `-1021` and synchronises time using `/api/v3/time`【F:convert_api.py†L117-L152】. Tests cover `recvWindow` and clock‑skew retry logic (`tests/test_recv_window_and_-1021_retry.py`).

## 6. Rounding & Limits

`exchange_filters.load_symbol_filters` obtains `fromAssetMinAmount` and `fraction` to compute step size and min notional before quoting【F:exchange_filters.py†L10-L45】. `convert_cycle.process_pair` applies step rounding and revalidates notional; quotes below minimum are skipped【F:convert_cycle.py†L29-L47】【F:convert_cycle.py†L106-L123】.

## 7. Weight Budget & Anti‑spam

Quote requests increment daily and per‑cycle counters in `quote_counter` (`QUOTE_LIMIT=950`, `MAX_PER_CYCLE=20`) and throttle when limits are hit【F:quote_counter.py†L9-L107】.

## 8. Risk‑off & Logging

`convert_logger.log_conversion_result` records quote ID, ratio, validUntil, acceptance status, latency placeholders, edge score and counters【F:convert_logger.py†L110-L170】. `convert_notifier.flush_failures` aggregates per‑cycle Telegram notifications into a single message【F:convert_notifier.py†L13-L33】. Explicit risk‑off behaviour for >10% drawdown tied to market data was not detected.

## 9. Secrets & Config

The project expects secrets only in `config_dev3.py` as documented【F:README.md†L7-L14】. Searches reveal uses of `os.getenv` for runtime flags (e.g., PAPER mode)【F:convert_cycle.py†L55-L57】, violating the requirement to avoid `os.getenv` entirely.

No `.env` files were found in the repository (`find . -name '*.env'`).

## 10. Gaps

Gaps:
- No explicit risk-off for >10% drawdown (must use public Spot Market Data).
- No mid-price (`avgPrice`/`bookTicker`) in scoring model; required by DEV3 logic.
- `os.getenv` usage contradicts single-source `config_dev3.py`.
- Ensure analytics via `data-api.binance.vision`; no Spot trading endpoints present.

## 11. Appendix

1. [Send quote request | Binance Open Platform][1]
2. [Market Data endpoints | Binance Open Platform][2]
3. [Accept Quote | Binance Open Platform][3]
4. [Order Status | Binance Open Platform][4]
5. [Get Convert Trade History | Binance Open Platform][5]
6. [List all convert pairs | Binance Open Platform][6]
7. [Query order quantity precision per asset | Binance Open Platform][7]
8. [Request Security | Binance Open Platform][8]
9. [Market Data Only | Binance Open Platform][9]
10. [Trading endpoints | Binance Open Platform][10]
11. [Change Log | Binance Open Platform][11]
12. [General API Information | Binance Open Platform][12]

*Report generated without executing tests per user instruction.*
