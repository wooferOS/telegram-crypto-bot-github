"""Telegram bot configuration and handlers."""

import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher.filters import Command, Text
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from daily_analysis import (
    generate_zarobyty_report,
    generate_daily_stats_report,
    daily_analysis_task,
)
from history import generate_history_report
from stats import generate_stats_report
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from binance_api import (
    place_market_order,
    get_price_history_24h,
    place_sell_order,
    market_buy,
    market_sell,
)
from alerts import check_daily_alerts


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", "0")))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)
logger = logging.getLogger(__name__)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("take_profit:"))
async def handle_take_profit(callback_query: CallbackQuery) -> None:
    """Handle take profit button presses."""

    try:
        _, symbol, quantity_str, price_str = callback_query.data.split(":")
        quantity = float(quantity_str)
        price = float(price_str)

        result = place_sell_order(symbol=symbol, quantity=quantity, price=price)
        if result:
            await callback_query.message.answer(
                f"✅ Ордер на продажу {symbol} по {price} встановлено. Кількість: {quantity}"
            )
        else:
            await callback_query.message.answer(
                f"❌ Не вдалося встановити ордер на {symbol}"
            )
    except Exception as e:  # pragma: no cover - log errors only
        await callback_query.message.answer(
            f"⚠️ Помилка під час фіксації прибутку: {e}"
        )


@dp.callback_query_handler(
    lambda c: c.data and (c.data.startswith("buy:") or c.data.startswith("sell:"))
)
async def handle_trade_action(callback_query: CallbackQuery) -> None:
    """Notify user about buy/sell actions."""
    action, symbol = callback_query.data.split(":")

    if action == "buy":
        await callback_query.answer(
            f"🟢 Купівля {symbol} (в розробці)", show_alert=False
        )
    elif action == "sell":
        await callback_query.answer(
            f"🔴 Продаж {symbol} (в розробці)", show_alert=False
        )

    # Optional log
    print(f"[BUTTON ACTION] User requested to {action.upper()} {symbol}")

scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler() -> None:
    """Configure daily tasks for APScheduler."""
    scheduler.add_job(
        daily_analysis_task,
        "cron",
        hour=7,
        args=(bot, ADMIN_CHAT_ID),
    )
    scheduler.add_job(
        check_daily_alerts,
        "cron",
        hour=8,
        args=(bot, ADMIN_CHAT_ID),
    )
    scheduler.start()


def clean_surrogates(text: str) -> str:
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "ignore")


def register_handlers(dp: Dispatcher) -> None:
    """Register bot command and callback handlers."""

    async def start_cmd(message: types.Message) -> None:
        await message.reply(
            "\U0001F44B Вітаю! Я GPT-бот для криптотрейдингу. Використовуйте команду /zarobyty для щоденного звіту."
        )

    async def zarobyty_cmd(message: types.Message) -> None:
        report, keyboard = generate_zarobyty_report()
        if not report:
            await message.answer(
                "⚠️ Звіт наразі недоступний. Спробуйте пізніше."
            )
            return
        logger.info("Zarobyty report:\n%s", report)
        print("✅ Звіт сформовано:", report[:200])
        report = clean_surrogates(report)
        if keyboard is None:
            await message.answer(report, parse_mode="Markdown")
        else:
            await message.answer(report, parse_mode="Markdown", reply_markup=keyboard)

    async def confirm_buy(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmbuy_", "")
        result = place_market_order(symbol=token, side="BUY", quantity=5)
        await callback_query.answer(f"Купівля {token} підтверджена.")
        await callback_query.message.answer(f"\U0001F7E2 Куплено {token}: {result}")

    async def confirm_sell(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmsell_", "")
        result = place_market_order(symbol=token, side="SELL", quantity=5)
        await callback_query.answer(f"Продаж {token} підтверджено.")
        await callback_query.message.answer(f"\U0001F534 Продано {token}: {result}")


    async def history_cmd(message: types.Message) -> None:
        await message.reply(generate_history_report(), parse_mode="Markdown")

    async def stats_cmd(message: types.Message) -> None:
        await message.reply(generate_stats_report(), parse_mode="Markdown")

    async def statsday_cmd(message: types.Message) -> None:
        await message.reply(generate_daily_stats_report(), parse_mode="Markdown")

    async def price24_cmd(message: types.Message) -> None:
        token = message.get_args().split()[0].upper() if message.get_args() else "BTC"
        prices = get_price_history_24h(token)
        if not prices:
            await message.reply(f"\u274C \u041d\u0435 \u043e\u0442\u0440\u0438\u043c\u0430\u043d\u043e \u0434\u0430\u043d\u0456 \u0434\u043b\u044f {token}.")
            return
        formatted = ", ".join(f"{p:.4f}" for p in prices)
        await message.reply(f"\U0001F4C8 \u0426\u0456\u043d\u0438 {token} \u0437\u0430 24\u0433:\n{formatted}")

    async def alerts_on_cmd(message: types.Message) -> None:
        await message.reply("Щоденні сповіщення увімкнено.")

    dp.register_message_handler(start_cmd, commands=["start"])
    dp.register_message_handler(zarobyty_cmd, Command("zarobyty"))
    dp.register_callback_query_handler(
        confirm_buy, lambda c: c.data and c.data.startswith("confirmbuy_")
    )
    dp.register_callback_query_handler(
        confirm_sell, lambda c: c.data and c.data.startswith("confirmsell_")
    )
    dp.register_message_handler(history_cmd, commands=["history"])
    dp.register_message_handler(stats_cmd, commands=["stats"])
    dp.register_message_handler(statsday_cmd, commands=["statsday"])
    dp.register_message_handler(price24_cmd, commands=["price24"])
    dp.register_message_handler(alerts_on_cmd, commands=["alerts_on"])

    async def menu_balance_cmd(message: types.Message) -> None:
        await message.reply(generate_history_report(), parse_mode="Markdown")

    async def menu_report_cmd(message: types.Message) -> None:
        report, keyboard = generate_zarobyty_report()
        report = clean_surrogates(report)
        await message.reply(report, parse_mode="Markdown", reply_markup=keyboard)

    async def menu_history_cmd(message: types.Message) -> None:
        await message.reply(generate_stats_report(), parse_mode="Markdown")

    dp.register_message_handler(menu_balance_cmd, commands=["Баланс"])
    dp.register_message_handler(menu_report_cmd, commands=["Звіт"])
    dp.register_message_handler(menu_history_cmd, commands=["Історія"])

    dp.register_message_handler(zarobyty_cmd, Text(contains="Звіт", ignore_case=True))
    dp.register_message_handler(stats_cmd, Text(contains="Баланс", ignore_case=True))
    dp.register_message_handler(history_cmd, Text(contains="Історія", ignore_case=True))


@dp.callback_query_handler(lambda c: c.data.startswith("buy:"))
async def handle_buy_callback(callback_query: CallbackQuery):
    symbol = callback_query.data.split(":")[1]
    await callback_query.message.answer(
        f"🟢 Ви впевнені, що хочете купити {symbol}? Натисніть кнопку нижче для підтвердження.",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton(f"✅ Купити {symbol}", callback_data=f"confirm_buy:{symbol}"),
            InlineKeyboardButton("❌ Скасувати", callback_data="cancel")
        )
    )


@dp.callback_query_handler(lambda c: c.data.startswith("sell:"))
async def handle_sell_callback(callback_query: CallbackQuery):
    symbol = callback_query.data.split(":")[1]
    await callback_query.message.answer(
        f"🔴 Ви впевнені, що хочете продати {symbol}? Натисніть кнопку нижче для підтвердження.",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton(f"✅ Продати {symbol}", callback_data=f"confirm_sell:{symbol}"),
            InlineKeyboardButton("❌ Скасувати", callback_data="cancel")
        )
    )


@dp.callback_query_handler(lambda c: c.data == "cancel")
async def handle_cancel(callback_query: CallbackQuery):
    await callback_query.message.answer("❌ Дію скасовано.")


@dp.callback_query_handler(lambda c: c.data.startswith("confirm_buy:"))
async def handle_confirm_buy(callback_query: CallbackQuery):
    symbol = callback_query.data.split(":")[1]
    usdt_amount = 10  # фіксована тестова сума
    try:
        result = market_buy(symbol, usdt_amount)
        await callback_query.message.answer(
            f"🟢 Купівля {symbol.upper()} на {usdt_amount} USDT успішна!\n\n{result}"
        )
    except Exception as e:  # pragma: no cover - network errors
        await callback_query.message.answer(
            f"❌ Помилка при купівлі {symbol.upper()}: {str(e)}"
        )


@dp.callback_query_handler(lambda c: c.data.startswith("confirm_sell:"))
async def handle_confirm_sell(callback_query: CallbackQuery):
    symbol = callback_query.data.split(":")[1]
    try:
        result = market_sell(symbol)
        await callback_query.message.answer(
            f"🔴 Продаж {symbol.upper()} успішний!\n\n{result}"
        )
    except Exception as e:  # pragma: no cover - network errors
        await callback_query.message.answer(
            f"❌ Помилка при продажу {symbol.upper()}: {str(e)}"
        )


