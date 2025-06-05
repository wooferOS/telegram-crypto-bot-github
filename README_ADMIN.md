# Admin Guide

Project path on server: `/root/telegram-crypto-bot-github`.

## Manual deploy
```bash
cd /root/telegram-crypto-bot-github
git pull origin dev
pip install -r requirements.txt
systemctl restart crypto-bot
```
