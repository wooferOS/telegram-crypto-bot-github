# 🧠 Telegram GPT Crypto Bot — Deployment Manual (Flask + Polling + systemd)

Цей проєкт — Telegram-бот із GPT-аналізом та автотрейдингом через Binance API.

## 🚀 Основні можливості:

- 🤖 Telegram бот із підтримкою GPT-4 аналізу
- 📊 Щоденна аналітика ринку криптовалют
- 🔁 Автотрейдинг через Binance API (купівля/продаж)
- 💡 Генерація стоп-лосів, PNL, прогнозу прибутку
- 🧩 Інтеграція з OpenAI, Telegram, Flask, GitHub Actions
- 🔥 Підтримка polling + healthcheck `/health`
- 🖥️ Автозапуск через systemd

---

## 📁 Структура проєкту
telegram-crypto-bot-github/
├── main.py # Основний файл з polling + Flask
├── daily_analysis.py # Щоденна GPT-аналітика ринку
├── .env # Змінні середовища (токени, ключі)
├── systemd/crypto-bot.service # systemd-сервіс для автозапуску
├── README_DEPLOY.md # Цей файл
├── deploy.sh # Bash-скрипт перезапуску бота
├── .github/workflows/daily.yml # GitHub Actions для щоденного аналізу
└── ...


---

## 🔧 1. Змінні `.env` (приклад)

```env
TELEGRAM_TOKEN=7810...KA14
ADMIN_CHAT_ID=465786073
OPENAI_API_KEY=sk-proj-...
BINANCE_API_KEY=XW1xhisEv...
BINANCE_SECRET_KEY=zRpLELZr...
SERVER_DOMAIN=https://188.166.27.248
---

---

---

## ⚙️ 2. Режим Flask + Polling

### 🔁 Активні одночасно:
- Flask (порт 10000, маршрут `/health`)
- Telegram polling (`telebot.infinity_polling()`)

> ❗ Не використовується Webhook — тільки polling.

---

## 🛠️ 3. Створення systemd-сервісу

Файл: `systemd/crypto-bot.service`

```ini
[Unit]
Description=Telegram GPT Crypto Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /root/telegram-crypto-bot-github/main.py
WorkingDirectory=/root/telegram-crypto-bot-github
Restart=always
RestartSec=10
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target

sudo cp systemd/crypto-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-bot
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot

from flask import Flask
app = Flask(__name__)

@app.route("/health")
def health():
    return "OK", 200

