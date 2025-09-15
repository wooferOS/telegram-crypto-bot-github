# Telegram Crypto Bot

This project interacts with the Binance Convert API. The typical flow is:

1. **Аналіз** – `daily_analysis.py` збирає ринки та формує `logs/top_tokens.dev3.json` у схемі v1.
2. **Відбір** – `top_tokens_utils.allowed_tos_for()` читає цей файл та відкидає фіати за даними Binance Capital.
3. **Конверт** – `convert_cycle.py` запитує `getQuote` та, якщо котирування чинне, викликає `acceptQuote`.

## Binance API references
- [Request Security](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/request-security)
- [Check Server Time](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-endpoints)
- [Send quote request](https://developers.binance.com/docs/convert/trade)
- [Accept Quote](https://developers.binance.com/docs/convert/trade/Accept-Quote)
- [Convert Error Codes](https://developers.binance.com/docs/convert/error-code)
- [All Coins’ Information](https://developers.binance.com/docs/wallet/capital)

## Secrets
API ключі не зберігаються у `.env` або unit-файлах. Єдиний робочий файл – `config_dev3.py`, який **не** в репозиторії і ігнорується через `.gitignore`. Для локального запуску використовуйте зразок `config_dev3.example.py` та створіть власний `config_dev3.py` з реальними значеннями.

## Systemd units

Sample unit files are provided in `deploy/systemd/` and use absolute paths to the
repository under `/root/telegram-crypto-bot-github`. Copy the required templates
into `/etc/systemd/system/` and adjust if your installation differs.

- `dev3-analysis-hourly@.service` runs `daily_analysis.py` hourly for a region.
- `dev3-convert@.service` runs `run_convert_trade.py` for a region.
- `dev3-tradeflow.service` is a documented placeholder and is disabled by default.

Each service expects a Python virtual environment located at
`.venv` inside the repository and real credentials supplied via a local
`config_dev3.py` which must never be committed to the repository.
