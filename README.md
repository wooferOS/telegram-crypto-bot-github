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

## ⚠️ Відомі проблеми
- Binance Convert Small Balances API поки закритий для більшості користувачів. При спробі виклику `convert_dust_to_usdt` бібліотека Binance може видавати `AssertionError: API Secret required for private endpoints`.
