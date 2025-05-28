#!/bin/bash

echo "📦 Зберігаю main.py"
git add main.py

echo "📦 Зберігаю daily_analysis.py"
git add daily_analysis.py

echo "📦 Зберігаю auto_trader.py"
git add auto_trader.py

echo "📦 Зберігаю forecast_and_history_modules.py"
git add forecast_and_history_modules.py

echo "📦 Зберігаю summary_and_profit_logger.py"
git add summary_and_profit_logger.py

echo "📦 Зберігаю recommendations.json"
git add recommendations.json

echo "📦 Зберігаю requirements.txt"
git add requirements.txt

echo "📦 Зберігаю .github/workflows/daily.yml"
git add .github/workflows/daily.yml

echo "✅ Комічу всі зміни"
git commit -m "🚀 Full update: all logic, GPT modules, forecasts, trading and reports"

echo "📥 Підтягуємо останні зміни з master"
git pull --rebase origin master

echo "📤 Відправляю все в репозиторій"
git push origin master

echo "📨 Надсилаю повідомлення в Telegram"
python3 -c "import os, requests; text = '✅ Успішно оновлено всі файли та пушено в GitHub!'; requests.post(f'https://api.telegram.org/bot{os.environ[\"TELEGRAM_TOKEN\"]}/sendMessage', data={'chat_id': os.environ[\"ADMIN_CHAT_ID\"], 'text': text})"

echo "🚀 Готово! Перевір GitHub Actions та Telegram!"

