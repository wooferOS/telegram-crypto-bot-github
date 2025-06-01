#!/bin/bash

echo "📦 Оновлення Telegram-бота..."

cd /root/telegram-crypto-bot-github || exit 1

echo "🔄 Отримання останніх змін із GitHub..."
git pull origin dev || exit 1

echo "🔁 Перезапуск systemd-сервісу..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl restart crypto-bot

echo "✅ Бот успішно перезапущено!"
