#!/bin/bash

echo "🔁 Перезапуск Telegram GPT-бота..."
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot --no-pager
