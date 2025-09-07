# DEV3 Audit Report

## 1) API Surface Map

| Модуль/функція | Ендпойнт | Метод | Обов'язкові параметри | Вага | Док-посилання | Статус |
|----------------|----------|-------|-----------------------|------|---------------|--------|
| `convert_api.get_quote_with_id` | `/sapi/v1/convert/getQuote` | POST | `fromAsset`, `toAsset`, `fromAmount`/`toAmount`, `validTime`, `recvWindow`, `timestamp`, `signature` | 200 UID | [Send Quote][1] | PASS |
| `convert_api.accept_quote` | `/sapi/v1/convert/acceptQuote` | POST | `quoteId`, `recvWindow`, `timestamp`, `signature` | 500 UID | [Accept Quote][5] | PASS |
| `convert_api.get_order_status` | `/sapi/v1/convert/orderStatus` | GET | `orderId`/`quoteId`, `recvWindow`, `timestamp`, `signature` | 100 UID | [Order Status][6] | PASS |
| `convert_api.trade_flow` | `/sapi/v1/convert/tradeFlow` | GET | `startTime`, `endTime`, `recvWindow`, `timestamp`, `signature` | 3000 UID | [Trade History][7] | PASS |
| `convert_api.exchange_info` | `/sapi/v1/convert/exchangeInfo` | GET | `fromAsset?` | 3000 IP | [Convert Market Data][3] | PASS |
| `convert_api.asset_info` | `/sapi/v1/convert/assetInfo` | GET | `asset` | 100 IP | [Asset Precision][8] | PASS |
| `convert_api.get_balances` | `/sapi/v3/asset/getUserAsset` | POST | `needBtcValuation`, `recvWindow`, `timestamp`, `signature` | 5 IP | [User Asset][4] | PASS |
| `md_rest.mid_price` | `/api/v3/ticker/bookTicker`, `/api/v3/avgPrice` | GET | `symbol` | 2 | [Market Data endpoints][9] | PASS |
| `md_rest.ticker_price` | `/api/v3/ticker/price` | GET | `symbol` | 2 | [Market Data endpoints → Symbol price ticker][9] | PASS |
| `md_rest.ticker_24hr` | `/api/v3/ticker/24hr` | GET | `symbol` | 40 | [Market Data endpoints][9] | PASS |
| `md_rest.klines` | `/api/v3/klines` | GET | `symbol`, `interval`, `limit` | 2 | [Market Data endpoints][9] | PASS |
| `md_ws.MarketDataWS` | `wss://data-stream.binance.vision/stream` | WS | `streams` | – | [WebSocket Streams][14] | PASS |
| `binance_api.get_historical_prices` | `/api/v3/klines` | GET | `symbol`, `interval`, `limit` | 2 | [Market Data endpoints][9] | PASS |
| `exchange_filters.get_last_price_usdt` | `/api/v3/ticker/price` | GET | `symbol` | 2 (1 символ) / 4 (без symbol або з symbols) | [Market Data endpoints → Symbol price ticker][9] | PASS |
| `risk_off._price_usdt` | `/api/v3/avgPrice`, `/api/v3/ticker/24hr` | GET | `symbol` | 2 | [Market Data endpoints][9] | PASS |

## 2) Execution Flow
1. Отримання меж і дробності через `exchange_info` та `asset_info`【F:exchange_filters.py†L10-L45】 – PASS  
2. Округлення суми вниз до `fraction` й перевірка Min/Max **до** запиту `getQuote`【F:convert_cycle.py†L60-L112】 – PASS  
3. `getQuote` з параметром `validTime` повертає `quoteId` та `validTimestamp`【F:convert_api.py†L236-L267】 – PASS  
4. Перед `acceptQuote` перевіряється `validTimestamp` і за потреби оновлюється quote【F:convert_cycle.py†L254-L280】 – PASS
5. Після `acceptQuote` викликається `orderStatus`; історія синхронізується через `tradeFlow`【F:convert_cycle.py†L282-L318】【F:trade_history_sync.py†L18-L32】 – PASS

Максимальний інтервал між `startTime` і `endTime` — 30 днів[13].

6. Цикл повторюється, поки ліміт ваги/лічильника не вичерпано【F:convert_cycle.py†L82-L117】【F:quote_counter.py†L15-L26】 – PASS

## 3) Market-Data Analytics
Уся аналітика отримується з публічних REST на `data-api.binance.vision`:  
* `bookTicker` та `avgPrice` для mid‑price【F:md_rest.py†L92-L116】【F:mid_ref.py†L22-L51】 – PASS
* `klines` для історичних даних та моментуму【F:md_rest.py†L80-L87】 – PASS
* `ticker/price` для останньої ціни【F:md_rest.py†L52-L57】 – PASS
* `ticker/24hr` у risk‑off оцінці портфеля та ліквідності【F:md_rest.py†L71-L75】【F:risk_off.py†L32-L47】 – PASS
**Примітка:** Для API, що повертають лише публічні дані, базова адреса має бути `https://data-api.binance.vision` (без API-ключа)[12].
Пошук інших Spot‑ендпойнтів не дав результатів【98a565†L1-L2】.

## 4) Security (SIGNED/Timing)
* `timestamp` та `recvWindow` (дефолт 5000) додаються перед підписом HMAC‑SHA256【F:convert_api.py†L86-L102】 – PASS
* `_request` обробляє код `-1021` із повторним синком часу【F:convert_api.py†L118-L156】 – PASS

Для всіх **SIGNED** запитів використовується параметр `timestamp` і опційний `recvWindow`. Якщо `recvWindow` не передано — дефолт 5000 мс; максимум 60000 мс[11].

## 5) Rounding & Limits
* `assetInfo` надає `fraction`, `exchangeInfo` – `fromAssetMinAmount`; обидва застосовуються перед цитуванням【F:exchange_filters.py†L10-L45】【F:convert_cycle.py†L60-L112】 – PASS

## 6) Weight-бюджет і антиспам
* Офіційні ваги збережені у `WEIGHTS` та враховуються для ліміту циклу【F:quote_counter.py†L15-L26】 – PASS  
* `should_throttle` блокує перевищення добового/циклового ліміту та ваги【F:quote_counter.py†L118-L123】【F:convert_cycle.py†L114-L116】 – PASS

## 7) Mid-price у скорингу
* `score_pair` використовує Spot mid для розрахунку `edge`【F:convert_cycle.py†L146-L160】【F:scoring.py†L24-L59】 – PASS

## 8) Risk-off
* `check_risk` оцінює просідання портфеля на основі балансів і публічних цін; при >10% зменшує ліміт/validTime, при >25% – пауза【F:convert_cycle.py†L42-L58】【F:risk_off.py†L32-L78】 – PASS

## 9) Secrets & Config
* Секрети та прапорці беруться лише з `config_dev3.py`【F:config_dev3.py†L1-L12】 – PASS  
* Пошук не виявив `.env`, `dotenv` чи `os.getenv`【98a565†L1-L2】【8955c6†L1-L2】 – PASS

## 10) Production-readiness
* Convert‑запити відправляються на `https://api.binance.com`【F:convert_api.py†L36-L38】 – PASS  
* Market Data використовує `https://data-api.binance.vision`【F:market_data.py†L4-L33】【F:binance_api.py†L5-L6】 – PASS  
* `DEV3_PAPER_MODE` за замовчуванням `False`【F:config_dev3.py†L9-L12】 – PASS  
* Пошук тестових режимів/ sandbox URL не дав результатів【8c4397†L1-L17】 – PASS

## 11) Gaps & Recommendations
INFO: Виявлених невідповідностей не знайдено; код відповідає вимогам Binance та внутрішній логіці DEV3.

**Doc errata (Binance references):**

* `/api/v3/ticker/price` — **2** (із `symbol`) / **4** (без `symbol` або з `symbols`). Джерело: *Market Data endpoints → Symbol price ticker*. ([Binance Developers][10])
* `recvWindow` — **дефолт 5000 мс**, **макс 60000 мс** для SIGNED. Джерело: *Request Security*. ([Binance Developers][11])
* Публічні ендпойнти — використовувати **`https://data-api.binance.vision`**. Джерела: *General API Information*; *Market Data Only*. ([Binance Developers][12])
* `tradeFlow` — інтервал **≤ 30 днів**. Джерело: *Get Convert Trade History*. ([Binance Developers][13])

---
[1]: https://developers.binance.com/docs/convert/trade?utm_source=chatgpt.com
[2]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api?utm_source=chatgpt.com
[3]: https://developers.binance.com/docs/convert/market-data?utm_source=chatgpt.com
[4]: https://developers.binance.com/docs/wallet/asset/user-assets?utm_source=chatgpt.com
[5]: https://developers.binance.com/docs/convert/trade/Accept-Quote?utm_source=chatgpt.com
[6]: https://developers.binance.com/docs/convert/trade/Order-Status?utm_source=chatgpt.com
[7]: https://developers.binance.com/docs/convert/trade/Get-Convert-Trade-History?utm_source=chatgpt.com
[8]: https://developers.binance.com/docs/convert/market-data/Query-order-quantity-precision-per-asset?utm_source=chatgpt.com
[9]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints?utm_source=chatgpt.com
[10]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints?utm_source=chatgpt.com
[11]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/request-security?utm_source=chatgpt.com
[12]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api?utm_source=chatgpt.com
[13]: https://developers.binance.com/docs/convert/trade/Get-Convert-Trade-History?utm_source=chatgpt.com
[14]: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
