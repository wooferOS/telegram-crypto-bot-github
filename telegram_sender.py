from dotenv import load_dotenv
import os
load_dotenv("/root/.env")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
import os


def send_conversion_signals(signals):
    if not signals:
        return

    message = "🔄 Конвертація вручну:\n"
    for i, s in enumerate(signals, 1):
        message += (
            f"{i}. {s['from_symbol']} → {s['to_symbol']}\n"
            f"   - {s['from_symbol']}: {s['from_amount']:.2f} шт (~{s['from_usdt']:.2f} USDT)\n"
            f"   - {s['to_symbol']}: ~{s['to_amount']:.2f} шт\n"
            f"   - Очікуваний прибуток: +{s['profit_pct']:.2f}% (~{s['profit_usdt']:.2f} USDT)\n"
            f"   - TP: {s['tp']}, SL: {s['sl']}\n\n"
        )

    # Надсилаємо повідомлення через curl
    message_escaped = message.replace('"', '\"')
    curl_cmd = (
        f'curl -s -X POST "https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" '
        f'-d chat_id={CHAT_ID} '
        f'--data-urlencode text="{message_escaped}"'
    )
    print("[Telegram] Executing curl...")
    os.system(curl_cmd)
