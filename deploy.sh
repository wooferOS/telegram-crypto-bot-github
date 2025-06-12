#!/bin/bash

LOGFILE="/var/log/crypto-bot-deploy.log"
exec > >(tee -a "$LOGFILE") 2>&1

echo "$(date '+%F %T') 🔄 [DEPLOY] Оновлення Telegram GPT Bot..."
cd ~/telegram-crypto-bot-github || exit 1

echo "$(date '+%F %T') 📦 Встановлення системних залежностей..."
sudo apt update && sudo apt install -y build-essential python3-dev

echo "$(date '+%F %T') 📦 Оновлення pip та перевстановлення aiohttp..."
pip install --upgrade pip setuptools wheel
pip install --no-cache-dir --force-reinstall aiohttp

echo "$(date '+%F %T') 📥 Підтягуємо останні зміни з GitHub..."
git pull origin dev

echo "$(date '+%F %T') 🔁 Перезапуск systemd-сервісу..."
sudo systemctl restart crypto-bot.service

echo "$(date '+%F %T') 📄 Перевірка статусу:"
sudo systemctl status crypto-bot.service --no-pager

echo "$(date '+%F %T') ✅ [DONE] Бот оновлено."
