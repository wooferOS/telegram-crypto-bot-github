# 🚀 Деплой Telegram Crypto Bot

## Коротка інструкція

1. Завантажити `main.py`, `.env`
2. Встановити залежності з `requirements.txt`
3. Запустити через `systemd` або `gunicorn`
4. Перевірити `/healthcheck` (якщо Flask)
5. Налаштувати GitHub Secrets для CI/CD

📦 **Не забудьте додати `python-dotenv` у `requirements.txt`!**
<<<<<<< Updated upstream

---

## 🛠 Увага

=======

---

## 🛠 Увага

>>>>>>> Stashed changes
Обов’язково встановити пакет `python-dotenv`, інакше файл `.env` не зчитуватиметься:

```bash
pip install python-dotenv

