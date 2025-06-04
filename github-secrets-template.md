# 🔐 GitHub Secrets Template

Цей файл описує, які секрети потрібно додати в GitHub (Settings → Secrets → Actions):

| Назва секрету       | Призначення                             |
|----------------------|------------------------------------------|
| `TELEGRAM_TOKEN`     | Токен Telegram-бота                     |
| `CHAT_ID`      | ID адміністратора в Telegram            |
| `OPENAI_API_KEY`     | GPT-ключ (OpenAI Platform)              |
| `BINANCE_API_KEY`    | Ключ Binance API                        |
| `BINANCE_SECRET_KEY` | Секретний ключ Binance                  |

> Усі значення беруться з `.env`, але мають бути продубльовані в Secrets для GitHub Actions.
