# 🚀 Інструкція з деплою Telegram GPT Crypto Bot

## 📋 Вимоги
- Ubuntu 22.04 VPS
- Python 3.11
- Доступ до GitHub
- Доступ до Binance API та OpenAI API
- Створений Telegram‑бот

---

## 🔧 Крок 1: Клонування репозиторію
```bash
git clone https://github.com/wooferOS/telegram-crypto-bot-github.git
cd telegram-crypto-bot-github
```

## 🐍 Крок 2: Віртуальне середовище та залежності
Встановіть Python 3.11 та створіть віртуальне середовище:
```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv git
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 🔑 Крок 3: Налаштування `.env`
1. Скопіюйте файл `.env.example` в `/root/.env`:
   ```bash
   cp .env.example /root/.env
   ```
2. Відредагуйте `/root/.env`, вказавши ваші токени Telegram, ключі Binance та OpenAI.

## 🖥 Крок 4: Пробний запуск
Після заповнення конфігурації запустіть бота вручну й переконайтесь, що він стартує без помилок:
```bash
python main.py
```
Зупиніть його `Ctrl+C` після перевірки.

## ⚙️ Крок 5: Налаштування systemd
1. Скопіюйте сервіс:
   ```bash
   sudo cp systemd/crypto-bot.service /etc/systemd/system/
   ```
2. Перезавантажте конфігурацію `systemd` та увімкніть сервіс:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now crypto-bot.service
   ```
3. Переконайтеся, що бот працює:
   ```bash
   sudo systemctl status crypto-bot.service --no-pager
   ```

## 📝 Додатково
- Для ротації логів скопіюйте файл `logrotate/crypto-bot` у `/etc/logrotate.d/`.
- Оновлювати код можна скриптом `update-from-github.sh`, який стягує останню версію з гілки `dev` без перезапуску сервісу.
- Щоденний звіт запускається через APScheduler всередині бота. Також є GitHub Actions, що запускає `run_daily_analysis.py`.

Бот готовий до роботи! Для зміни конфігурації редагуйте `/root/.env` і перезапускайте сервіс.
