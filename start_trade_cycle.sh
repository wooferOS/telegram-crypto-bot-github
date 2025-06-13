echo '#!/bin/bash
cd /root/telegram-crypto-bot-github
export $(grep -v "^#" systemd/crypto-bot.env | xargs)
python3 run_auto_trade_cycle.py >> /root/trade.log 2>&1' > /root/start_trade_cycle.sh && \
chmod +x /root/start_trade_cycle.sh && \
(crontab -l 2>/dev/null; echo "15 * * * * /root/start_trade_cycle.sh") | crontab -
