import logging
import asyncio
from aiogram import Dispatcher
from aiogram.utils import executor
from telegram_bot import (
    dp,
    bot,
    setup_scheduler,
    register_handlers,
    ADMIN_CHAT_ID,
    check_tp_sl_execution,
)
from binance_api import get_open_orders

logging.basicConfig(level=logging.INFO)


async def monitor_orders() -> None:
    """Periodically check open orders and notify when filled."""
    while True:
        open_orders = get_open_orders()
        for order in open_orders:
            if order.get("status") == "FILLED":
                await bot.send_message(
                    ADMIN_CHAT_ID,
                    f"\U0001F3AF Ордер виконано: {order['symbol']} {order['side']}",
                )
        await check_tp_sl_execution()
        await asyncio.sleep(30)


async def on_startup(dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)


if __name__ == "__main__":
    setup_scheduler()
    register_handlers(dp)
    loop = asyncio.get_event_loop()
    loop.create_task(monitor_orders())
    executor.start_polling(dp, on_startup=on_startup)
