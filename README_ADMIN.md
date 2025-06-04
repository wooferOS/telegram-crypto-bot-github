# 🛡️ Інструкція для адміністрування сервера (README_ADMIN.md)

## 📍 Локація коду
- Шлях до проєкту: `/root/telegram-crypto-bot-github`
- Основний файл: `main.py`

## 🚀 Ручний деплой
```bash
cd /root/telegram-crypto-bot-github
git pull origin dev
pip install -r requirements.txt
systemctl restart crypto-bot
