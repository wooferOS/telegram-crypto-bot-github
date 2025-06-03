# 🚀 Telegram GPT Crypto Bot — Deploy Guide

Цей документ описує повне розгортання Telegram-бота з підтримкою:

- 📈 Автоматичний аналіз ринку через GPT
- 🤖 Telegram polling режим
- 🌐 Flask /health endpoint
- 🔁 Запуск через systemd
- 🟢 Підтримка моніторингу через UptimeRobot

---

## ⚙️ Структура проєкту

telegram-crypto-bot-github/
├── main.py # Основний бот з Flask + polling
├── daily_analysis.py # Щоденна GPT-аналітика
├── .env # Секрети (НЕ пушити)
├── deploy.sh # Швидкий деплой
├── systemd/crypto-bot.service # systemd сервіс
├── logrotate/crypto-bot # лог-менеджмент
└── README_DEPLOY.md # інструкція

yaml
Copy
Edit

---

## 📦 Залежності

Встановити один раз:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
pip install -r requirements.txt
