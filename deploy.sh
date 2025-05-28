#!/bin/bash

cd /root/telegram-crypto-bot-github || exit
echo "📦 Оновлення коду з GitHub..."
git pull

echo "🔁 Перезапуск сервісу crypto-bot.service..."
systemctl restart crypto-bot.service

echo "✅ Бот перезапущено!"
