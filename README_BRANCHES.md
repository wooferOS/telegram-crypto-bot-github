# 🔀 Стратегія гілок у telegram-crypto-bot-github

## 🟩 `master` — продакшн
- Усі стабільні, перевірені зміни
- Бот на сервері завжди працює з цієї гілки
- Щоб оновити бота на сервері:
  ```bash
  git pull origin master
  sudo systemctl restart crypto-bot
