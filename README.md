# 🤖 GPT Binance Telegram Bot

Це інтелектуальний Telegram-бот для щоденної аналітики криптовалютного ринку через Binance API та OpenAI GPT-4.

---

## 📊 Можливості

- Автоматичний аналіз ринку (топ-30 пар) двічі на день
- Формування GPT-звітів із рекомендаціями купівлі/продажу
- Telegram-команди для підтвердження дій
- Підтримка кнопок, бюджету, історії, PNL
- Повністю інтегрований із GitHub Actions та Binance
- Автоматичне збереження історії угод (`trade_history.json`)
- Встановлення Stop-Loss і Take-Profit через OCO після купівлі
- Захист `.env` — файл не потрапляє у репозиторій
- Щоденний аналіз автоматично о 09:00 та 20:00 через GitHub Actions

---

## 📁 Основні файли

- `main.py` — логіка Telegram-бота
- `daily_analysis.py` — GPT-звіт та whitelist-аналітика
- `.env` — змінні середовища
- `requirements.txt` — залежності
- `README_DEPLOY.md` — повна інструкція для запуску

## 🚀 Flask + Telegram polling режим

Бот працює у двох потоках:

- 🤖 Telegram-бот запускається через `bot.polling()`
- 🌐 Flask-сервер відповідає на `/health` на порту `10000`

Це дозволяє використовувати UptimeRobot для моніторингу живого стану бота.

### Запуск:
Використовується файл:

🔄 Оновлення основного бота:

- Додано `main_polling_flask.py` — запуск Telegram polling і Flask одночасно
- Flask-сервер доступний на `http://188.166.27.248:10000/health`
- Додано підтримку UptimeRobot моніторингу
- Підтримується запуск через systemd (`ExecStart=/usr/bin/python3 main_polling_flask.py`)
## 🚀 Режим Flask + Telegram polling

Цей режим дозволяє одночасно запускати:

- 🤖 Telegram-бота (polling)
- 🌐 Flask-сервер з `/health` для моніторингу

### 📌 Запуск

Запускається через файл:
```bash
main_polling_flask.py


