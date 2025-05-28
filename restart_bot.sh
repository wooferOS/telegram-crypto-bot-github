#!/bin/bash

echo "🔁 Перевірка й завершення попередніх процесів main.py..."
PIDS=$(ps aux | grep 'main.py' | grep -v grep | awk '{print $2}')

if [ -n "$PIDS" ]; then
  echo "🔴 Завершення процесів з PID: $PIDS"
  kill -9 $PIDS
else
  echo "✅ Немає запущених копій main.py"
fi

echo "🚀 Запуск нового процесу бота..."
cd ~/telegram-crypto-bot-github
python3 main.py
