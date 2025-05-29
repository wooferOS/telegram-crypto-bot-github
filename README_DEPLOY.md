## 📦 README\_DEPLOY.md — Інструкція по розгортанню Telegram-бота `@Oleksii_Profit_bot`

### 🔧 Вимоги

* Сервер Ubuntu 22.04 (DigitalOcean)
* Python 3.10+
* Встановлені пакети: `python3-pip`, `git`, `systemd`, `virtualenv`
* Binance API-ключі, Telegram Bot Token, OpenAI API Key

---

### 📁 Структура проєкту

```
telegram-crypto-bot-github/
├── main.py                  # Основна логіка Telegram-бота
├── daily_analysis.py        # GPT-аналіз портфелю
├── .env                     # Змінні середовища
├── requirements.txt         # Python-залежності
├── deploy.sh                # Скрипт розгортання
├── README_DEPLOY.md         # Інструкція
├── systemd/crypto-bot.service  # systemd сервіс
├── logrotate/crypto-bot      # логування
├── reports/YYYY-MM-DD/      # GPT-звіти
```

---

### 🚀 Команди запуску (на сервері)

```bash
cd ~/telegram-crypto-bot-github
git pull origin master
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot
```

---

### 🔐 Змінні .env (приклад)

```
TELEGRAM_TOKEN=7810501536:AA...KOGKA14
OPENAI_API_KEY=sk-...
BINANCE_API_KEY=tD8pZIfR...
BINANCE_SECRET_KEY=t4bQbi2...
ADMIN_CHAT_ID=465786073
```

---

### 🧠 GPT-ФУНКЦІЇ

Бот використовує GPT для щоденного аналізу крипторинку та формування торгових рішень.

#### 🔍 Основні можливості:

* Автоматичний аналіз криптопортфеля через `daily_analysis.py`.
* Генерація аналітичного звіту за командою `/report`.
* Підготовка і надання сигналів до дій:

  * `/confirm_buy` — бот формує список активів для купівлі, користувач підтверджує.
  * `/confirm_sell` — бот формує список активів для продажу, користувач підтверджує.

#### 📊 Структура GPT-звіту:

* Поточний баланс усіх активів Binance.
* Що рекомендується **продати** — з поясненням.
* Що рекомендується **купити** — з розрахованим обсягом, стоп-лоссом, тейк-профітом.
* Очікуваний прибуток по кожній угоді та сумарно.
* Команди на підтвердження — кожна дія окремо.

⚠️ GPT-аналіз не є фінансовою порадою. Це аналітична оцінка на основі технічних даних станом на момент генерації.

---

### 📱 Кнопки Telegram-бота (`ReplyKeyboardMarkup`)

Починаючи з оновлення `main.py` від `2025-05-29`, для створення меню клавіатури використовується метод `.row(...)`.

#### ✅ Правильна реалізація:

```python
main_menu = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.row("💰 Баланс", "📊 Звіт", "📘 Історія")
main_menu.row("✅ Підтвердити купівлю", "✅ Підтвердити продаж")
main_menu.row("🔄 Оновити", "🛑 Скасувати")
```

Цей підхід стабільно працює з новими версіями `pyTelegramBotAPI` і дозволяє точно контролювати структуру кнопок.

#### 🔁 Після оновлення:

* `main.py` оновлено
* Після `git pull` потрібно виконати:

```bash
sudo systemctl restart crypto-bot
```

---

### 🧪 Додаткові команди Telegram

* `/start` — запустити бота
* `/menu` — головне меню
* `/report` — аналітичний GPT-звіт
* `/confirm_buy` — підтвердити купівлю
* `/confirm_sell` — підтвердити продаж
* `/set_budget 100` — встановити бюджет
* `/buy BTC 0.01` — купити вручну
* `/sell ETH 0.5` — продати вручну
* `/balance` — показати всі активи
* `/status` — стан бюджету
* `/history` — історія угод

---

### 🔄 Логування

* `daily.log` — лог щоденних дій
* `logs/bot.log` — лог Telegram-бота
* `journalctl -u crypto-bot.service` — перегляд логів systemd

---

### 🆘 Відновлення

Якщо бот не запускається:

```bash
sudo systemctl status crypto-bot
journalctl -u crypto-bot.service -n 50 --no-pager
```

Виправ помилку у `main.py`, збережи, перезапусти.

---

👨‍💻 Проєкт підтримується Oleksii Shymanskyi
GitHub: [https://github.com/wooferOS/telegram-crypto-bot-github](https://github.com/wooferOS/telegram-crypto-bot-github)
