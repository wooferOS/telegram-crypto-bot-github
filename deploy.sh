#!/bin/bash

export $(grep -v '^#' /root/telegram-crypto-bot-github/.env | xargs)


echo "📥 Отримую останні зміни з GitHub..."
cd ~/telegram-crypto-bot-github || exit
git pull origin master

echo "🔁 Перезапуск бота через systemd..."
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot --no-pager
