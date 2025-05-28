import os
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SERVER_DOMAIN = os.getenv("SERVER_DOMAIN")  # приклад: https://188.166.27.248

if not TELEGRAM_TOKEN or not SERVER_DOMAIN:
    raise ValueError("❌ TELEGRAM_TOKEN або SERVER_DOMAIN не встановлено!")

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
webhook_url = f"{SERVER_DOMAIN}/webhook"

response = requests.post(url, data={"url": webhook_url})
print(f"Webhook set: {response.status_code} - {response.text}")
