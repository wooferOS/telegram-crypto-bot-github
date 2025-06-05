#!/bin/bash

export $(cat /root/.env | xargs)

echo "📦 Зберігаю актуальні файли"
git add main.py
git add daily_analysis.py
git add requirements.txt
git add .github/workflows/daily.yml
git add .env.example
git add README.md
git add README_DEPLOY.md
git add systemd/crypto-bot.service
git add logrotate/crypto-bot
git add restart_bot.sh
git add deploy.sh
git add update_all.sh
git add github-secrets-template.md
git add .gitignore

echo "✅ Комічу всі зміни"
git commit -m "🔄 Auto-update: GPT Binance bot core + configs"

echo "📥 Підтягуємо останні зміни з master"
git pull --rebase origin master

echo "📤 Відправляю все в GitHub"
git push origin master

echo "🔁 Перезапускаю systemd сервіс"
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot --no-pager

# 📨 Надсилаємо повідомлення в Telegram
python3 -c "import os, requests; text = '✅ Успішне оновлення Telegram GPT-бота!'; requests.post(f'https://api.telegram.org/bot{os.environ[\"TELEGRAM_TOKEN\"]}/sendMessage', data={'chat_id': os.environ['CHAT_ID'], 'text': text})"

echo "🚀 Готово!"
