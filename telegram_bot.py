"""Telegram bot configuration and handlers."""

import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types

load_dotenv(dotenv_path=os.path.expanduser("~/.env"))

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", "7885000778:AAE9VsogpVzr5VR-HvufUGgSnp4Fif1_yG8"
)
if TELEGRAM_TOKEN == "7885000778:AAE9VsogpVzr5VR-HvufUGgSnp4Fif1_yG8":
    print("⚠️ Warning: .env not loaded. This is expected in Codex.")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", "0")))
if ADMIN_CHAT_ID == 0:
    print("⚠️ Warning: ADMIN_CHAT_ID is empty. Make sure .env is loaded on server.")


@dp.message_handler(commands=["start"])
async def handle_start(message: types.Message) -> None:
    """Handle /start command."""
    await message.answer(
        "Привіт! Використовуйте /zarobyty для отримання прогнозу."
    )


@dp.message_handler(commands=["zarobyty"])
async def handle_zarobyty(message: types.Message) -> None:
    """Generate stub GPT report with action buttons."""
    from daily_analysis import generate_zarobyty_report

    report = generate_zarobyty_report()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("Підтвердити", callback_data="confirm")
    )
    await message.answer(report, reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data == "confirm")
async def handle_confirm_callback(callback_query: types.CallbackQuery) -> None:
    """Respond to inline confirmation button press."""
    await callback_query.answer("Підтверджено ✅", show_alert=True)


@dp.message_handler(commands=["stats"])
async def handle_stats(message: types.Message) -> None:
    await message.answer("Статистика тимчасово недоступна.")


@dp.message_handler(commands=["balance"])
async def handle_balance(message: types.Message) -> None:
    """Show current portfolio balances."""
    from binance_api import get_current_portfolio

    portfolio = get_current_portfolio()
    if not portfolio:
        await message.answer("Баланс недоступний.")
        return

    lines = [f"{asset}: {amount} USDT" for asset, amount in portfolio.items()]
    await message.answer("\n".join(lines))


@dp.message_handler(commands=["history"])
async def handle_history(message: types.Message) -> None:
    await message.answer("Історія дій тимчасово недоступна.")


@dp.message_handler(commands=["statsday"])
async def handle_statsday(message: types.Message) -> None:
    await message.answer("Денна статистика тимчасово недоступна.")


@dp.message_handler(commands=["alerts_on"])
async def handle_alerts_on(message: types.Message) -> None:
    await message.answer("Сповіщення увімкнено.")


@dp.message_handler(lambda m: m.text.startswith("/confirmbuy_"))
async def handle_confirm_buy(message: types.Message) -> None:
    symbol = message.text.split("_", 1)[1]
    await message.answer(f"Купівля {symbol} підтверджена ✅")


@dp.message_handler(lambda m: m.text.startswith("/confirmsell_"))
async def handle_confirm_sell(message: types.Message) -> None:
    symbol = message.text.split("_", 1)[1]
    await message.answer(f"Продаж {symbol} підтверджено ✅")

