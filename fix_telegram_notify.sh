#!/bin/bash

echo "🔧 Updating Telegram notify block in .github/workflows/daily.yml..."

WORKFLOW_FILE=".github/workflows/daily.yml"

# Замінити блок run: | python -c ... на однорядкову команду з правильним date
sed -i '/- name: Notify Telegram/,/^ *run: *|/ {
  N;N;N
  s|.*run:.*|    run: python -c "import os, requests; text = open(f'daily_report_$(date +%F).md').read(); requests.post(f'https://api.telegram.org/bot{os.environ[\\\"TELEGRAM_TOKEN\\\"]}/sendMessage', data={'chat_id': os.environ['ADMIN_CHAT_ID'], 'text': text})"|
}' "$WORKFLOW_FILE"

echo "✅ Updated $WORKFLOW_FILE"

# Git дії
git add "$WORKFLOW_FILE"
git commit -m "✅ Fix: telegram notify shell block with correct date formatting"
git pull --rebase origin master
git push origin master

echo "🚀 Done! Check the workflow on GitHub Actions."
