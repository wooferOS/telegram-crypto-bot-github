# Binance Convert Auto-Cycle

Автоматизація добових конвертацій Binance Convert для двох торгових вікон
(Азія/Америка). Репозиторій зосереджений на одному CLI та оркестраторі,
побудованих поверх офіційних Spot/SAPI ендпоінтів.

## Структура

```
src/
├─ core/
│  ├─ binance_client.py   # HTTP клієнт: підпис, тротлінг, кеш exchangeInfo
│  ├─ convert_api.py      # Обгортки SAPI Convert та балансів
│  ├─ balance.py          # Єдині точки читання SPOT/FUNDING
│  ├─ scheduler.py        # Вікна, джитер, файлові локи
│  └─ utils.py            # Decimal/час/джитер
├─ strategy/
│  └─ selector.py         # Простий rule-based відбір кандидатів
├─ app.py                 # Оркестратор analyze/trade
└─ cli.py                 # Єдиний CLI для ручних дій і автозапуску
scripts/
├─ install_bins.sh        # Встановлює /usr/local/bin/ обгортки
└─ crontab.example        # Готові cron-задачі
```

## Перед стартом

1. Створіть **локальний** файл `config_dev3.py` у корені проєкту з таким
   вмістом (значення підставте свої):

   ```python
   BINANCE_API_KEY = "..."
   BINANCE_SECRET_KEY = "..."

   DRY_RUN_DEFAULT = False
   QPS = 5
   BURST = 10
   EXINFO_TTL_SEC = 120
   QUOTE_BUDGET_PER_RUN = 10
   ORDER_POLL_SEC = 2
   ORDER_POLL_TIMEOUT_SEC = 60

   ASIA_ANALYZE_FROM = "05:40"
   ASIA_ANALYZE_TO   = "05:46"
   ASIA_TRADE_FROM   = "05:47"
   ASIA_TRADE_TO     = "05:57"

   US_ANALYZE_FROM = "17:10"
   US_ANALYZE_TO   = "17:16"
   US_TRADE_FROM   = "17:17"
   US_TRADE_TO     = "17:27"

   JITTER_SEC = 120
   LOG_PATH = "/var/log/convert.log"
   ```

   > **Увага:** файл не комітимо. Переконайтесь, що `config_dev3.py` доданий у
   > `.gitignore` (вже налаштовано).

2. Встановіть залежності: потрібен лише `requests` (Python 3.10+).

   ```bash
   python3 -m pip install --user requests
   ```

3. (Опційно) прокладіть `LOG_PATH` через `logrotate`, аби файл логів не ріс
   безкінечно.

## CLI

Основний інтерфейс запускається як `python3 -m src.cli`. Ключові підкоманди:

- `info FROM TO` — показує `exchangeInfo` та доступні баланси у SPOT/FUNDING.
- `quote FROM TO AMOUNT --wallet=SPOT|FUNDING` — сухе котирування без угоди.
- `now FROM TO AMOUNT --wallet=... [--dry]` — миттєва угода (або dry run).
- `status ORDER_ID` — поточний статус конвертації.
- `trades --hours 24 [--detailed]` — історія конвертацій за період.
- `run --region=asia|us --phase=analyze|trade [--dry|--real]` — запуск
  етапів автоциклу (використовується cron/systemd).

Приклади:

```bash
python3 -m src.cli info USDT BTC
python3 -m src.cli quote USDT BTC 25 --wallet=SPOT
python3 -m src.cli now USDT BTC ALL --wallet=SPOT --dry
```

## Автоцикл

1. Встановіть системні шорткати (бажано під root):

   ```bash
   sudo PREFIX=/usr/local/bin bash scripts/install_bins.sh
   ```

   Будуть створені утиліти `cspot`, `cqspot`, `auto-asia`, `auto-us` тощо.

2. Додайте рядки з `scripts/crontab.example` у crontab користувача, що має
   доступ до ключів. Вивід спрямовується в `/var/log/convert.log`.

3. Перевірте, що файл логів доступний для запису користувачу cron/systemd.

## Анти-спам механіки

- Токен-бакет на рівні HTTP клієнта (QPS/BURST).
- Backoff на 429/-1003 та повтор на -1021 із синхронізацією часу.
- Кеш `exchangeInfo` на `EXINFO_TTL_SEC` секунд.
- Джитер запуску вікон (`JITTER_SEC`) та невеликий джитер перед `getQuote`.
- Квота `QUOTE_BUDGET_PER_RUN` на один прогін analyze/trade.
- Файлові локи `/tmp/asia.lock` та `/tmp/us.lock`.

## Перевірка

1. `python3 -m src.cli info USDT BTC`
2. `python3 -m src.cli quote USDT BTC 5 --wallet=SPOT`
3. `python3 -m src.cli run --region=asia --phase=analyze --dry`
4. У робочому вікні запускається `auto-asia trade`, логи з'являються у
   `/var/log/convert.log`.

## Документація Binance

- [Convert Endpoints](https://binance-docs.github.io/apidocs/spot/en/#convert-endpoints)
- [Account Information](https://binance-docs.github.io/apidocs/spot/en/#account-information-user_data)
- [Funding Balances](https://binance-docs.github.io/apidocs/spot/en/#get-user-asset-user_data)
- [Limits & Errors](https://binance-docs.github.io/apidocs/spot/en/#limits)
