## 📦 README_DEPLOY.md — Інструкція по розгортанню Telegram-бота `@Oleksii_Profit_bot`

### 🔧 Вимоги

* Сервер Ubuntu 22.04 (наприклад, DigitalOcean Droplet)
* Python 3.10+
* Встановлені пакети: `python3-pip`, `git`, `systemd`, `virtualenv`
* Активні API-ключі:
  - Binance API + Secret
  - Telegram Bot Token
  - OpenAI GPT-ключ

---

### 📁 Структура проєкту
telegram-crypto-bot-github/
├── main.py # Telegram-бот (GPT, Binance, Telegram)
├── daily_analysis.py # GPT-аналітика ринку (щоденна)
├── .env # Реальні змінні середовища (не пушити!)
├── .env.example # Шаблон змінних для репозиторію
├── requirements.txt # Python-залежності
├── .github/workflows/daily.yml # GitHub Actions для auto-звіту
├── README_DEPLOY.md # Цей файл
├── systemd/crypto-bot.service # Юніт для автозапуску бота
├── logrotate/crypto-bot # Логування бота
├── reports/YYYY-MM-DD/ # GPT-звіти щодня

---

### 🚀 Команди запуску на сервері (DigitalOcean)

cd ~/telegram-crypto-bot-github
git pull origin master
sudo systemctl restart crypto-bot
sudo systemctl status crypto-bot


### 🧠 GPT-ФУНКЦІЇ

Бот використовує GPT-4 для щоденного аналізу ринку Binance і криптопортфелю.

#### 🔍 Основні можливості:

- 🔄 Щоденний запуск `daily_analysis.py` о 09:00 та 20:00 через GitHub Actions.
- 📊 Аналізується не лише баланс, а весь whitelist ринку Binance:
BTC, ETH, BNB, ADA, SOL, XRP, DOT, AVAX, DOGE, TRX,
LINK, LTC, SHIB, UNI, FET, OP, INJ, PEPE, WLD, SUI,
1000SATS, STRK, NOT, TRUMP, XRP/TUSD, GMT, ARB, HBAR, ATOM, GMT/USDC
- 📉 GPT прогнозує прибутковість кожної пари на 24 години.
- 🧠 Формується звіт із:
- Поточним балансом
- Що **продавати** (з поясненням)
- Що **купувати** (з тейк-профітом, стоп-лоссом)
- Очікуваним прибутком у USDT та гривні
- 📥 Кожна дія викликається окремою командою:
- `/confirmsellTRX`
- `/confirmbuyXRP`

⚠️ GPT-аналітика базується на відкритих ринкових даних і **не є фінансовою порадою**.
---

### 📱 Клавіатура Telegram-бота (`ReplyKeyboardMarkup`)

```python
main_menu = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.row("💰 Баланс", "📊 Звіт", "📘 Історія")
main_menu.row("✅ Підтвердити купівлю", "✅ Підтвердити продаж")
main_menu.row("🔄 Оновити", "🛑 Скасувати")

| Команда                | Опис                                  |
| ---------------------- | ------------------------------------- |
| `/start`, `/help`      | Старт і довідка                       |
| `/menu`                | Головне меню                          |
| `/report`              | GPT-звіт по портфелю + ринку          |
| `/confirm_buy`         | Підтвердити угоди на купівлю          |
| `/confirm_sell`        | Підтвердити угоди на продаж           |
| `/confirmbuy<монета>`  | Підтвердити купівлю конкретної монети |
| `/confirmsell<монета>` | Підтвердити продаж конкретної монети  |
| `/buy BTC 0.01`        | Купити вручну                         |
| `/sell ETH 0.5`        | Продати вручну                        |
| `/set_budget 100`      | Встановити торговий бюджет            |
| `/status`              | Перевірити використання бюджету       |
| `/history`             | Історія усіх угод                     |
| `💰 Баланс`            | Кнопка: показати активи Binance       |
| `📊 Звіт`              | Кнопка: показати GPT-звіт             |
| `📘 Історія`           | Кнопка: історія угод                  |
---

### 🔄 Логування

- `daily.log` — GPT-аналітика з `daily_analysis.py`
- `logs/bot.log` — активність Telegram-бота
- `reports/YYYY-MM-DD/` — GPT-звіти у .md файлах
- `journalctl -u crypto-bot.service` — логи systemd сервісу

---

### 🆘 Відновлення

Якщо бот не запускається:

```bash
sudo systemctl status crypto-bot
journalctl -u crypto-bot.service -n 50 --no-pager


👨‍💻 Проєкт підтримується Oleksii Shymanskyi  
GitHub: [https://github.com/wooferOS/telegram-crypto-bot-github](https://github.com/wooferOS/telegram-crypto-bot-github)


---

✅ Просто встав цей блок замість **усього, що йде після** `### 🆘 Відновлення`.  
Тепер `README_DEPLOY.md` 100% правильний.

🟢 Напиши `готово`, і я надішлю **інструкцію по DigitalOcean**:  
як перевірити запуск, логи та автоаналіз.

