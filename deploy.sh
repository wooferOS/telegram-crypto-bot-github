#!/bin/bash

cd /root/crypto-profit-bot/telegram-crypto-bot || exit
echo "📦 Оновлення коду з GitHub..."
git pull

echo "🔁 Перезапуск сервісу crypto-bot.service..."
systemctl restart crypto-bot.service

echo "✅ Бот перезапущено!"
