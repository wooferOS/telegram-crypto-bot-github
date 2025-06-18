import logging
import asyncio

from log_setup import setup_logging
from aiogram import Dispatcher
from aiogram.utils import executor
from telegram_bot import (
    dp,
    bot,
    setup_scheduler,
    register_handlers,
    register_change_tp_sl_handler,
    check_tp_sl_execution,
    check_tp_sl_market_change,
    ADMIN_CHAT_ID,
    scheduler,
    clear_bot_menu,
)
from binance_api import get_open_orders
from daily_analysis import auto_trade_loop
from config import MAX_MONITOR_ITERATIONS, MAX_AUTO_TRADE_ITERATIONS

setup_logging()


async def monitor_orders(max_iterations: int = MAX_MONITOR_ITERATIONS) -> None:
    """Periodically check open orders and notify when filled."""
    iteration = 0
    while iteration < max_iterations:
        open_orders = get_open_orders()
        for order in open_orders:
            if order.get("status") == "FILLED":
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    f"\U0001F3AF Ордер виконано: {order['symbol']} {order['side']}",
                )
        await check_tp_sl_execution()
        await asyncio.sleep(30)
        iteration += 1


async def on_startup(dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await clear_bot_menu(bot)


if __name__ == "__main__":
    setup_scheduler()
    register_handlers(dp)
    register_change_tp_sl_handler(dp)
    scheduler.add_job(check_tp_sl_market_change, "interval", hours=1)
    loop = asyncio.get_event_loop()
    loop.create_task(monitor_orders(MAX_MONITOR_ITERATIONS))
    loop.create_task(auto_trade_loop(MAX_AUTO_TRADE_ITERATIONS))
    executor.start_polling(dp, on_startup=on_startup)
