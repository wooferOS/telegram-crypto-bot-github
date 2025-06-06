#!/bin/bash

LOGFILE="/var/log/crypto-bot-deploy.log"
exec > >(tee -a "$LOGFILE") 2>&1

echo "$(date '+%F %T') 🔄 [DEPLOY] Оновлення Telegram GPT Bot..."
cd ~/telegram-crypto-bot-github || exit 1

echo "$(date '+%F %T') 📥 Підтягуємо останні зміни з GitHub..."
git pull origin dev

echo "$(date '+%F %T') 🔁 Перезапуск systemd-сервісу..."
sudo systemctl restart crypto-bot.service

echo "$(date '+%F %T') 📄 Перевірка статусу:"
sudo systemctl status crypto-bot.service --no-pager

echo "$(date '+%F %T') ✅ [DONE] Бот оновлено."
