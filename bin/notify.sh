#!/usr/bin/env bash
set -euo pipefail
MSG="\$1"
source /etc/telegram/dev3.env
URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
curl -fsS -m 10 -X POST "$URL" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MSG}" >/dev/null
