# 🤖 Telegram Crypto Bot with GPT Assistant

Цей бот автоматично аналізує крипторинок, формує звіт, і дозволяє підтвердження купівлі/продажу на основі GPT-аналізу.

## 📦 Основні функції

- Автоматичний щоденний аналіз ринку (`daily_analysis.py`)
- GPT-звіт: `/report`
- Підтвердження: `/confirm_buy`, `/confirm_sell`
- Налаштування бюджету: `/set_budget`
- Встановлення торгової пари: `/set_pair`
- Перегляд історії: `/history`

## 🧠 GPT-Функції
Описано детально в [README_DEPLOY.md](./README_DEPLOY.md)

## ⚙️ Інфраструктура
- Python 3.10+
- Telegram Bot API
- OpenAI GPT API
- Binance API
- GitHub Actions (щоденний запуск `daily_analysis.py`)
