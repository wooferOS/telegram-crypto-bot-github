from daily_analysis import get_current_portfolio, get_historical_data, run_daily_analysis
from telegram_bot import bot, CHAT_ID

def run_task():
    current = get_current_portfolio()
    historical = get_historical_data()
    report = run_daily_analysis(current, historical)

    if report:
        try:
            max_length = 4096
            for i in range(0, len(report), max_length):
                bot.send_message(CHAT_ID, report[i:i+max_length])
        except Exception as e:
            bot.send_message(CHAT_ID, f"❌ Помилка при надсиланні GPT-звіту:\n{e}")
    else:
        bot.send_message(CHAT_ID, "⚠️ GPT-звіт не створено.")

if __name__ == "__main__":
    run_task()
