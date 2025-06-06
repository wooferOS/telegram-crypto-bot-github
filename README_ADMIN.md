# 👨‍💻 README для адміністратора Telegram GPT Crypto Bot

## 📦 Архітектура

- Увесь код зберігається в гіт-репозиторії [dev](https://github.com/wooferOS/telegram-crypto-bot-github/tree/dev).
- Сервер для запуску: [DigitalOcean Droplet](https://cloud.digitalocean.com/droplets/497525685/terminal/ui).
- Запуск бота керується через `systemd` сервіс `crypto-bot.service`.

Проект розгорнуто в `/root/telegram-crypto-bot-github`.

## 🗓️ Оновлення бота

1. Увійдіть на сервер:
   ```bash
   ssh root@<SERVER_IP>
   ```
2. Перейдіть до папки проекту та отримайте останні зміни:
   ```bash
   cd /root/telegram-crypto-bot-github
   git pull origin dev
   pip install -r requirements.txt
   ```
3. Перезапустіть systemd-сервіс:
   ```bash
   sudo systemctl restart crypto-bot.service
   ```

Спростити оновлення можна скриптом `update-from-github.sh`, який автоматично підтягує код з GitHub та перезапускає сервіс.

## 📁 Структура проекту

- `main.py` — точка входу для запуску бота. Налаштовує планіровщик APScheduler.
- `telegram_bot.py` — містить налаштування та хендлери Telegram.
- `daily_analysis.py` — логіка щоденного аналізу ринку.
- `binance_api.py` — вся робота з Binance API.
- `systemd/crypto-bot.service` — конфігурація systemd для автозапуску.
- `logrotate/crypto-bot` — налаштування архівації логів.

## 👤 Відповідальності

- **Адміністратор** — підтримка сервера, оновлення пакетів, резервні копії.
- **Розробник** — додаває новий функціонал та обслуговує код. Зміни проходять через гіт та зливаються з гілки `dev`.

Цей документ призначено для внутрішного користування і описує базові кроки підтримки та оновлення бота.
