import time
import logging
from daily_analysis import analyze_market_and_trade
from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(level=logging.INFO)

def run_auto_trade_cycle():
    logging.info("🔁 Auto trade cycle запущено...")
    try:
        analyze_market_and_trade()
    except Exception as e:
        logging.error(f"❌ Помилка в auto_trade_cycle: {e}")

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    scheduler.add_job(run_auto_trade_cycle, 'interval', hours=1)
    scheduler.add_job(run_auto_trade_cycle, 'interval', minutes=15)
    logging.info("📅 Запускаємо планувальник auto_trade_cycle")
    run_auto_trade_cycle()  # одразу при запуску
    scheduler.start()
