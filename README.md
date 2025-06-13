# 🤖 Telegram GPT Crypto Bot

## 📈 Що це таке?
Це Telegram-бот із GPT-аналітикою для трейдингу криптовалютою. Він підключений до Binance API та автоматично:
- аналізує ринок
- формує щоденні звіти
- прогнозує зміни
- дозволяє купувати / продавати токени прямо через Telegram

## 🔧 Основні можливості:
- `/zarobyty` — аналітичний GPT-звіт з кнопками для дій
- `/stats` — підсумок прибутку за тиждень/місяць
- `/history` — історія угод
- `/price24` — ціни за останні 24 години для вибраного токена
  Наприклад: `/price24 BTC` показує останні ціни Bitcoin за годину.
- щоденний ранковий запуск аналізу (APScheduler / GitHub Actions)
- автозапуск через `systemd`
- інтеграція з Binance API та OpenAI API

## 📦 Технічний стек:
- Python 3.11
- aiogram
- Binance API
- OpenAI (GPT-4)
- Telegram Bot API
- APScheduler
- SQLite
- Docker (опційно)

## 📁 Файлова структура:
- `main.py` — головна логіка Telegram-бота
- `daily_analysis.py` — генерація щоденного прогнозу
- `binance_api.py` — взаємодія з Binance
- `run_daily_analysis.py` — запуск аналітики окремо
- `systemd/crypto-bot.service` — сервіс для VPS
- `.github/workflows/daily.yml` — автоматичний GitHub-запуск
- `/etc/crypto-bot.env` — файл змінних середовища для systemd
- `reports/` — архів GPT-звітів

## 🛠 Запуск:
1. Клонуйте репозиторій:
```bash
git clone https://github.com/wooferOS/telegram-crypto-bot-github.git
```
2. Встановіть пакети для компіляції C‑залежностей (наприклад `aiohttp`):
```bash
sudo apt update && sudo apt install -y build-essential python3-dev
```
3. Оновіть pip та перевстановіть `aiohttp` без кешу:
```bash
pip install --upgrade pip setuptools wheel
pip install --no-cache-dir --force-reinstall aiohttp
```
4. Встановіть Python‑залежності:
```bash
pip install -r requirements.txt
```

## Щоденний звіт о 9:00
Щоб отримувати ранковий звіт у Telegram, додайте cron-завдання:

```cron
# daily cron launch
0 9 * * * /usr/bin/python3 /root/telegram-crypto-bot-github/run_daily_analysis.py >> /root/cron.log 2>&1
```

## Автозапуск через systemd

1. Скопіюйте `systemd/crypto-bot.service` до `/etc/systemd/system/`.
2. Створіть файл `systemd/crypto-bot.env` або `.env` з ключами:

```
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
TELEGRAM_TOKEN=...
CHAT_ID=...
OPENAI_API_KEY=...
```

3. Запустіть та перезавантажте сервіс:

```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable crypto-bot.service
sudo systemctl restart crypto-bot.service
```
