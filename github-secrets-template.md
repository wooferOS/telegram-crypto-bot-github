# 🛡 GitHub Secrets для Telegram GPT Crypto Bot

Щоб GitHub Actions (`.github/workflows/daily.yml`) могли запускати `run_daily_analysis.py`, необхідно додати такі секрети у Settings > Secrets:

| Назва              | Приклад                                   | Опис                                      |
|-------------------|-------------------------------------------|-------------------------------------------|
| TELEGRAM_TOKEN     | 7885...:AAE...yG8                         | Токен Telegram-бота                       |
| CHAT_ID            | 465786073                                 | ID чату (каналу, групи або користувача)   |
| OPENAI_API_KEY     | sk-proj-...                                | GPT-ключ OpenAI                           |
| BINANCE_API_KEY    | XW1x...                                     | Ключ Binance API                          |
| BINANCE_SECRET_KEY | zRpL...                                     | Секрет Binance API                        |

⚠️ **Ніколи не пушити `.env` у репозиторій.** Для безпеки всі ключі живуть лише у GitHub Secrets або `.env` на сервері.

---

```plaintext
Terminal:
❌ Нічого робити не потрібно. Файл потрібен лише для репозиторію GitHub.
```
