#!/bin/bash

echo "🔁 [AUTO-UPDATE] Підтягуємо код з GitHub та перезапускаємо бота..."
cd ~/telegram-crypto-bot-github || exit
git pull origin dev
sudo systemctl restart crypto-bot.service
echo "✅ [DONE] Бот оновлено та запущено."
