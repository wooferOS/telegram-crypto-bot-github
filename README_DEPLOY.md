# Деплой

1. Завантажити main.py, .env
2. Встановити залежності з `requirements.txt`
3. Запустити через systemd або Gunicorn
4. Перевірити healthcheck

📦 Не забудьте додати `python-dotenv` у залежності!

## Увага
Обов’язково має бути встановлений пакет `python-dotenv`, інакше файл `.env` не буде зчитано:

```bash
pip install python-dotenv
