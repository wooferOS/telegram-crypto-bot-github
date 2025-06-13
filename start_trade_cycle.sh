cat << 'EOF' > /root/start_trade_cycle.sh
#!/bin/bash
cd /root/telegram-crypto-bot-github
set -a
. systemd/crypto-bot.env
set +a
exec /usr/bin/python3 run_auto_trade_cycle.py >> /root/trade.log 2>&1
EOF

chmod +x /root/start_trade_cycle.sh
