#!/bin/bash

# Simple update from GitHub without service restart
# Convenient for previewing changes

echo "📥 Оновлення коду з GitHub (гілка dev)..."
cd ~/telegram-crypto-bot-github || exit
git pull origin dev
echo "✅ Готово!"
