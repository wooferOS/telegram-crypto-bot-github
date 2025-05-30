#!/bin/bash

export $(cat /root/telegram-crypto-bot-github/.env | xargs)

echo "🔁 Перезапуск Telegram GPT-бота..."
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot --no-pager
