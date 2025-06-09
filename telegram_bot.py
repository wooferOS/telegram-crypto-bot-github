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
from aiogram.utils.callback_data import CallbackData
from binance_api import (
    place_market_order,
    get_price_history_24h,
    place_sell_order,
    market_buy,
    market_sell,
    create_take_profit_order,
    get_open_orders,
    sell_token_market,
    buy_token_market,
    place_stop_limit_sell_order,
    place_stop_limit_buy_order,
    get_token_price,
    get_token_balance,
    get_usdt_balance,
    get_real_pnl_data,
    place_limit_sell,
    place_limit_sell_order,
    market_buy_symbol_by_amount,
    place_take_profit_order,
    place_stop_loss_order,
)
from alerts import check_daily_alerts

take_profit_cb = CallbackData("tp", "symbol", "amount")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", os.getenv("CHAT_ID", "0")))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TP/SL order controls helpers
# ---------------------------------------------------------------------------

def get_order_controls(symbol: str, qty: float, current_price: float) -> InlineKeyboardMarkup:
    """Створити кнопки для виставлення Take Profit та Stop Loss."""

    keyboard = InlineKeyboardMarkup(row_width=2)
    tp_button = InlineKeyboardButton(
        text="\U0001F4C8 \u0412\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u0438 TP",
        callback_data=f"set_tp|{symbol}|{qty}|{current_price}"
    )
    sl_button = InlineKeyboardButton(
        text="\U0001F6E1\ufe0f \u0412\u0441\u0442\u0430\u043D\u043E\u0432\u0438\u0442\u0438 SL",
        callback_data=f"set_sl|{symbol}|{qty}|{current_price}"
    )
    keyboard.add(tp_button, sl_button)
    return keyboard


@dp.callback_query_handler(lambda c: c.data.startswith("set_tp|"))
async def callback_set_tp(call: types.CallbackQuery) -> None:
    """Обробник кнопки Take Profit."""

    _, symbol, qty, price = call.data.split("|")
    tp_price = round(float(price) * 1.10, 6)
    try:
        place_take_profit_order(symbol=symbol, quantity=float(qty), take_profit_price=tp_price)
        await call.message.answer(f"\u2705 TP ордер виставлено: {symbol} \u2192 {tp_price}")
    except Exception as e:  # pragma: no cover - network errors
        await call.message.answer(f"\u274C \u041F\u043E\u043C\u0438\u043B\u043A\u0430 TP: {e}")
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("set_sl|"))
async def callback_set_sl(call: types.CallbackQuery) -> None:
    """Обробник кнопки Stop Loss."""

    _, symbol, qty, price = call.data.split("|")
    sl_price = round(float(price) * 0.95, 6)
    try:
        place_stop_loss_order(symbol=symbol, quantity=float(qty), stop_price=sl_price)
        await call.message.answer(f"\u2705 SL ордер виставлено: {symbol} \u2192 {sl_price}")
    except Exception as e:  # pragma: no cover - network errors
        await call.message.answer(f"\u274C \u041F\u043E\u043C\u0438\u043B\u043A\u0430 SL: {e}")
    await call.answer()


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


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("take_profit_"))
async def handle_take_profit_new(callback_query: CallbackQuery) -> None:
    _, symbol, quantity, buy_price = callback_query.data.split(":")
    quantity = float(quantity)
    buy_price = float(buy_price)
    target_profit_percent = 10
    target_price = round(buy_price * (1 + target_profit_percent / 100), 8)

    result = create_take_profit_order(symbol, quantity, target_price)
    if result["success"]:
        await bot.send_message(
            callback_query.from_user.id,
            f"✅ Ордер на фіксацію прибутку {symbol} встановлено за ціною {target_price}",
        )
    else:
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Помилка при встановленні Take Profit: {result['error']}",
        )


@dp.callback_query_handler(take_profit_cb.filter())
async def take_profit_callback_handler(
    callback_query: types.CallbackQuery, callback_data: dict
) -> None:
    symbol = callback_data["symbol"]
    amount = float(callback_data["amount"])

    try:
        result = place_limit_sell(symbol, amount)
        await callback_query.message.answer(
            f"✅ Ордер на фіксацію прибутку для {symbol} відправлено!\n{result}"
        )
    except Exception as e:
        await callback_query.message.answer(
            f"❌ Помилка при виставленні ордера: {e}"
        )
    await callback_query.answer()


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
        report, _ = generate_zarobyty_report()
        if not report:
            await message.answer(
                "⚠️ Звіт наразі недоступний. Спробуйте пізніше."
            )
            return
        logger.info("Zarobyty report:\n%s", report)
        print("✅ Звіт сформовано:", report[:200])
        report = clean_surrogates(report)

        pnl_data = get_real_pnl_data()
        profitable_to_sell = {
            sym: data for sym, data in pnl_data.items() if data.get("pnl_percent", 0) > 0
        }

        keyboard = InlineKeyboardMarkup(row_width=1)
        for symbol, data in profitable_to_sell.items():
            btn = InlineKeyboardButton(
                text=f"Фіксувати прибуток {symbol}",
                callback_data=take_profit_cb.new(symbol=symbol, amount=str(data["amount"]))
            )
            keyboard.add(btn)

        await message.answer(report, parse_mode="Markdown", reply_markup=keyboard)

    async def confirm_buy(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmbuy_", "")
        result = place_market_order(symbol=token, side="BUY", usdt_amount=5)
        await callback_query.answer(f"Купівля {token} підтверджена.")
        await callback_query.message.answer(f"\U0001F7E2 Куплено {token}: {result}")

    async def confirm_sell(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmsell_", "")
        result = place_market_order(symbol=token, side="SELL", usdt_amount=5)
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


@dp.callback_query_handler(lambda c: c.data == "cancel_take_profit")
async def handle_cancel_take_profit(callback_query: CallbackQuery) -> None:
    await callback_query.message.answer("🚫 Фіксацію прибутку скасовано.")


@dp.callback_query_handler(lambda c: c.data.startswith("confirm_buy:"))
async def handle_confirm_buy(callback_query: CallbackQuery):
    symbol = callback_query.data.split(":")[1]
    usdt_amount = 10  # фіксована тестова сума
    try:
        result = market_buy(symbol, usdt_amount)
        await callback_query.message.answer(
            f"🟢 Купівля {symbol.upper()} на {usdt_amount} USDT успішна!\n\n{result}"
        )

        quantity = 0.0
        price = 0.0
        if isinstance(result, dict):
            quantity = float(result.get("executedQty", 0))
            quote_qty = float(result.get("cummulativeQuoteQty", 0))
            if quantity:
                price = quote_qty / quantity

        keyboard = get_order_controls(f"{symbol.upper()}USDT", quantity, price)
        await callback_query.message.answer(
            "\U0001F4CA Встановити TP або SL?",
            reply_markup=keyboard,
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


@dp.message_handler(commands=["orders"])
async def open_orders_cmd(message: types.Message) -> None:
    """Respond with currently open Binance orders."""
    try:
        orders = get_open_orders()
        if not orders:
            await message.answer("ℹ️ Немає відкритих ордерів.")
            return

        text = "📋 Відкриті ордери Binance:\n"
        for o in orders:
            symbol = o.get("symbol", "")
            side = o.get("side", "")
            order_type = o.get("type", "")
            price = o.get("price", "")
            qty = o.get("origQty", "")
            status = o.get("status", "")
            text += (
                f"\n{symbol} | {side} | {order_type} | 💵 Ціна: {price} | К-сть: {qty} | Статус: {status}"
            )

        await message.answer(text)
    except Exception as e:  # pragma: no cover - network errors
        await message.answer(f"⚠️ Помилка при отриманні ордерів: {e}")


@dp.callback_query_handler(lambda c: c.data.startswith("sell_"))
async def handle_sell_callback(callback_query: types.CallbackQuery):
    token = callback_query.data.split("_", 1)[1]
    try:
        result = sell_token_market(token)
        await callback_query.message.answer(
            f"✅ Продано {result['executedQty']} {token} за {result['cummulativeQuoteQty']} USDT"
        )
    except Exception as e:
        await callback_query.message.answer(
            f"❌ Помилка при продажу {token}: {e}"
        )
@dp.callback_query_handler(lambda c: c.data.startswith("buy_"))
async def handle_buy_callback(callback_query: types.CallbackQuery):
    token = callback_query.data.split("_", 1)[1].upper()
    amount_in_usdt = 10
    try:
        order = market_buy_symbol_by_amount(token, amount_in_usdt)
        price = float(order["fills"][0]["price"]) if "fills" in order and order["fills"] else None
        if not price:
            await callback_query.message.answer(f"❌ Купівля {token} не вдалася: немає ціни виконання")
            return
        quantity = float(order.get("executedQty", 0))
        symbol = f"{token}USDT"
        take_profit_price = round(price * 1.15, 8)
        stop_loss_price = round(price * 0.93, 8)
        place_take_profit_order(symbol, quantity=quantity, take_profit_price=take_profit_price)
        place_stop_loss_order(symbol, quantity=quantity, stop_price=stop_loss_price)
        await callback_query.message.answer(
            f"✅ Куплено {token} на ~{amount_in_usdt} USDT за {price} USDT\n"
            f"🎯 Встановлено Take Profit: {take_profit_price}\n"
            f"🛑 Встановлено Stop Loss: {stop_loss_price}"
        )
    except Exception as e:
        await callback_query.message.answer(f"❌ Помилка при купівлі {token}: {e}")





@dp.callback_query_handler(lambda c: c.data.startswith("takeprofit_"))
async def handle_take_profit_callback(callback_query: types.CallbackQuery):
    token = callback_query.data.split("_", 1)[1]
    try:
        price_data = get_token_price(token)
        current_price = float(price_data["price"])
        target_profit_percent = 10  # Прибуток у %
        take_profit_price = round(current_price * (1 + target_profit_percent / 100), 6)
        balance = get_token_balance(token)

        if balance <= 0:
            await callback_query.message.answer(
                f"⚠️ Баланс {token} = 0. Ордер не створено."
            )
            return

        result = place_stop_limit_sell_order(
            symbol=token,
            quantity=balance,
            stop_price=take_profit_price,
            limit_price=take_profit_price,
        )

        if result.get("orderId"):
            await callback_query.message.answer(
                f"📉 Ордер на фіксацію прибутку створено:\n"
                f"{balance} {token} при {take_profit_price}"
            )
        else:
            await callback_query.message.answer(
                f"⚠️ Не вдалося створити ордер для {token}.\n{result}"
            )
    except Exception as e:
        await callback_query.message.answer(
            f"❌ Помилка при створенні take profit для {token}:\n{e}"
        )


@dp.callback_query_handler(lambda c: c.data.startswith("smartbuy_"))
async def handle_smart_buy_callback(callback_query: types.CallbackQuery):
    token = callback_query.data.split("_", 1)[1]
    try:
        price_data = get_token_price(token)
        current_price = float(price_data["price"])
        stop_price = round(current_price * 0.99, 6)
        usdt_to_use = 10

        usdt_balance = get_usdt_balance()
        if usdt_balance < usdt_to_use:
            await callback_query.message.answer("⚠️ Недостатньо USDT для купівлі.")
            return

        quantity = round(usdt_to_use / stop_price, 2)

        result = place_stop_limit_buy_order(
            symbol=token,
            quantity=quantity,
            stop_price=stop_price,
            limit_price=stop_price,
        )

        if result.get("orderId"):
            await callback_query.message.answer(
                f"🛒 Ордер на купівлю створено:\n{quantity} {token} при {stop_price}"
            )
        else:
            await callback_query.message.answer(
                f"⚠️ Не вдалося створити ордер на купівлю {token}.\n{result}"
            )

    except Exception as e:
        await callback_query.message.answer(
            f"❌ Помилка при створенні ордера на {token}:\n{e}"
        )

