#!/bin/bash

export $(grep -v '^#' /root/.env | xargs)


echo "🔁 Перезапуск Telegram GPT-бота..."
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot --no-pager
