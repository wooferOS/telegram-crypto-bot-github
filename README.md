# Binance Convert dual-market automation

Продакшн-орієнтований код для щоденних Convert-операцій на двох ринках
(Азія/Америка). Усі модулі працюють лише з офіційними Spot/SAPI
ендпойнтами Binance та покладаються на єдиний локальний конфіг
`config_dev3.py` (зберігається тільки на сервері й не комітиться).

## Архітектура

```
src/
├─ app.py                 # оркестратор analyze/trade з блокуванням та квотами
├─ cli.py                 # єдиний CLI для ручних викликів і автозапуску
├─ core/
│  ├─ binance_client.py   # HMAC, токен-бакет, ретраї, кеш exchangeInfo
│  ├─ balance.py          # читання SPOT/FUNDING залишків
│  ├─ convert_api.py      # обгортки exchangeInfo/getQuote/acceptQuote/... 
│  ├─ scheduler.py        # вікна ринків, стартовий джитер, файлові lock-и
│  └─ utils.py            # час, форматування, перевірка мін/макс лімітів
└─ strategy/
   └─ selector.py         # відбір маршрутів із whitelist за фазою

scripts/
├─ install_bins.sh        # встановлює тонкі оболонки (`cspot`, `auto-asia`, ...)
├─ crontab.example        # приклад cron-розкладу (UTC)
└─ logrotate_convert      # політика ротації `/var/log/convert.log`
```

## Конфігурація

Файл `config_dev3.py` повинен містити (доступний лише локально):

```python
BINANCE_API_KEY: str
BINANCE_SECRET_KEY: str
QPS: int
BURST: int
JITTER_MS: tuple[int, int]
EXCHANGEINFO_TTL_SEC: int
QUOTE_BUDGET_PER_RUN: int
LOG_PATH: str
DRY_RUN: int  # 0 або 1
ASIA_WINDOW: dict
US_WINDOW: dict
ROUTES_WHITELIST: list[dict]
```

Жодних `.env` чи дублювання ключів — усі модулі роблять `from config_dev3 import ...`.

## Встановлення оболонок

```bash
sudo PREFIX=/usr/local/bin bash scripts/install_bins.sh
```

Будуть створені:

- `cspot` / `cfund` — миттєва конвертація через CLI (`now`),
- `cqspot` / `cqfund` — лише котирування (`quote`),
- `auto-asia` / `auto-us` — прямий виклик `python3 -m src.app` з потрібною фазою.

## Cron та logrotate

1. Скопіюйте `scripts/crontab.example` до crontab користувача, що запускає
   автоцикл (часи — в UTC, додатковий `flock` не потрібен: застосовується
   файлове блокування зсередини застосунку).
2. Додайте файл `scripts/logrotate_convert` до `/etc/logrotate.d/`, щоб
   обмежити ріст логу `LOG_PATH`.

## CLI

```
python3 -m src.cli info  FROM TO
python3 -m src.cli quote FROM TO AMOUNT --wallet=SPOT|FUNDING
python3 -m src.cli now   FROM TO AMOUNT --wallet=SPOT|FUNDING [--dry-run 0|1]
python3 -m src.cli status ORDER_ID
python3 -m src.cli trades --hours 24 [--detailed]
python3 -m src.cli run --region asia|us --phase analyze|trade [--dry-run 0|1]
```

Суми форматуються через `floor_str_8`, баланси беруться з SPOT/FUNDING гаманців.

## Автоцикл

Запуск: `python3 -m src.app --region asia|us --phase analyze|trade [--dry-run 0|1]`.

Послідовність дій:

1. Перевіряється, чи поточний час входить у вікно з `ASIA_WINDOW` / `US_WINDOW`.
2. Накладається файловий lock (`/tmp/{region}_{phase}.lock`).
3. Додається стартовий джитер 120–180 секунд.
4. Для кожного маршруту з `ROUTES_WHITELIST` виконується `getQuote` (ліміт —
   `QUOTE_BUDGET_PER_RUN`).
5. На фазі `trade` при вимкненому dry-run додатково виконується `acceptQuote`
   та одноразовий `orderStatus`.

## Захист від лімітів

- Токен-бакет (`QPS`/`BURST`) + мікроджитер для `getQuote`.
- Повтор запиту на -1021 (timestamp) та експоненційний backoff 1–16 c + джитер
  на HTTP 429/-1003.
- Кеш `exchangeInfo` на `EXCHANGEINFO_TTL_SEC` секунд.
- Ліміт котирувань `QUOTE_BUDGET_PER_RUN` на кожен прогін.

## Ручні смок-тести

```
python3 -m compileall src
python3 -m src.cli info  USDT BTC
python3 -m src.cli quote USDT BTC 1.23 --wallet=SPOT
python3 -m src.cli quote USDT BTC 1.23 --wallet=FUNDING
python3 -m src.cli trades --hours 24
python3 -m src.cli status 2091872497350769094
python3 -m src.app --region asia --phase analyze --dry-run 1
python3 -m src.app --region asia --phase trade   --dry-run 1
```

## Корисні посилання (офіційна документація Binance)

- Convert: `/sapi/v1/convert/exchangeInfo`, `/sapi/v1/convert/getQuote`,
  `/sapi/v1/convert/acceptQuote`, `/sapi/v1/convert/orderStatus`,
  `/sapi/v1/convert/tradeFlow`
- Баланси: `/api/v3/account`, `/sapi/v3/asset/getUserAsset`
