"""Telegram bot configuration and handlers."""

import logging
import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher.filters import Command, Text
from aiogram.dispatcher import filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from daily_analysis import (
    generate_zarobyty_report,
    generate_daily_stats_report,
    daily_analysis_task,
)
from history import generate_history_report
from stats import generate_stats_report
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
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
    place_take_profit_order_auto,
    place_stop_loss_order_auto,
    get_current_price,
    cancel_order,
    update_tp_sl_order,
    get_active_orders,
    get_binance_balances,
    modify_order,
    cancel_tp_sl_if_market_changed,
)
from alerts import check_daily_alerts
from config import TELEGRAM_TOKEN, CHAT_ID, ADMIN_CHAT_ID

take_profit_cb = CallbackData("tp", "symbol", "amount")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)
logger = logging.getLogger(__name__)


async def clear_bot_menu(bot: Bot) -> None:
    """Remove any custom bot commands."""

    await bot.delete_my_commands()

# Mapping of symbol to current TP/SL order IDs
active_orders: dict[str, dict] = {}


async def notify_updated_order(symbol: str, new_tp: float, new_sl: float) -> None:
    """Send Telegram notification about updated TP/SL order."""

    text = f"\u267B\ufe0f Ордер оновлено для {symbol}:\n\u27A4 TP: {new_tp}\n\u27A4 SL: {new_sl}"
    await bot.send_message(ADMIN_CHAT_ID, text)


async def check_tp_sl_execution() -> None:
    """Monitor active TP/SL orders and update if market moved."""
    for symbol, data in list(active_orders.items()):
        if not data:
            continue
        pair = f"{symbol.upper()}USDT"
        orders = get_open_orders(pair)
        if not orders:
            active_orders[symbol] = None
            continue

        tp_order = next((o for o in orders if o.get("orderId") == data.get("tp_id")), None)
        sl_order = next((o for o in orders if o.get("orderId") == data.get("sl_id")), None)

        if not tp_order and not sl_order:
            active_orders[symbol] = None
            continue

        current = get_current_price(symbol)
        new_tp = round(current * 1.10, 6)
        new_sl = round(current * 0.95, 6)

        need_update = False
        if tp_order and abs(float(tp_order.get("price", 0)) - new_tp) / float(tp_order.get("price", 1)) > 0.015:
            need_update = True
        if sl_order and abs(float(sl_order.get("stopPrice", 0)) - new_sl) / float(sl_order.get("stopPrice", 1)) > 0.015:
            need_update = True

        if need_update:
            result = update_tp_sl_order(symbol, new_tp, new_sl)
            if result:
                active_orders[symbol] = {"tp_id": result["tp"], "sl_id": result["sl"]}
                await notify_updated_order(pair, new_tp, new_sl)

# Reply keyboard with main actions
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.row(
    KeyboardButton("\U0001F4C8 Заробити"),
    KeyboardButton("\U0001F4CB Змінити ордери")
)
menu.row(
    KeyboardButton("\U0001F9F0 Змінити TP/SL")
)
menu.row(
    KeyboardButton("\U0001F4CA Баланс"),
    KeyboardButton("\U0001F4E6 Всі активи")
)
menu.row(
    KeyboardButton("\U0001F4C8 Графік"),
    KeyboardButton("\U0001F9E0 Прогноз GPT")
)
menu.row(
    KeyboardButton("\U0001F9D1\u200d\U0001F4BB Підтримка")
)


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


@dp.callback_query_handler(lambda c: c.data == "zarobyty")
async def zarobyty_button_handler(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await zarobyty_cmd(callback_query.message)

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


async def zarobyty_cmd(message: types.Message) -> None:
    """Send the daily earnings report."""

    await message.answer("⏳ Формую звіт...")

    report, _, _, gpt_text = generate_zarobyty_report()
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
    MAX_LEN = 4000
    for i in range(0, len(gpt_text), MAX_LEN):
        await message.answer(gpt_text[i:i + MAX_LEN])


def register_handlers(dp: Dispatcher) -> None:
    """Register bot command and callback handlers."""

    async def start_cmd(message: types.Message) -> None:
        await message.reply(
            "\U0001F44B Вітаю! Я GPT-бот для криптотрейдингу. Використовуйте команду /zarobyty для щоденного звіту.",
            reply_markup=menu,
        )


    async def confirm_buy(callback_query: types.CallbackQuery) -> None:
        token = callback_query.data.replace("confirmbuy_", "").upper()
        result = place_market_order(symbol=token, side="BUY", usdt_amount=5)
        await callback_query.answer(f"Купівля {token} підтверджена.")

        if not result or (isinstance(result, dict) and result.get("error")):
            await callback_query.message.answer(
                f"❌ Помилка покупки {token}: {result.get('error') if isinstance(result, dict) else 'Unknown error'}"
            )
            return

        await callback_query.message.answer(
            f"\U0001F7E2 Куплено {token}. Ставимо автоматичні ордери..."
        )

        price = get_current_price(token)
        take_profit_price = round(price * 1.10, 6)
        stop_loss_price = round(price * 0.95, 6)

        tp = place_take_profit_order_auto(token, target_price=take_profit_price)
        sl = place_stop_loss_order_auto(token, stop_price=stop_loss_price)
        if isinstance(tp, dict) and isinstance(sl, dict):
            active_orders[token] = {"tp_id": tp.get("orderId"), "sl_id": sl.get("orderId")}

        await callback_query.message.answer(
            "\uD83C\uDF1F \u0412\u0441\u0442\u0430\u043D\u043E\u0432\u043B\u0435\u043D\u043E:"\
            f"\nTake Profit: {take_profit_price} USDT"\
            f"\nStop Loss: {stop_loss_price} USDT"\
            f"\n{'✅ TP OK' if isinstance(tp, dict) and tp.get('orderId') else '❌ TP Error'} | "\
            f"{'✅ SL OK' if isinstance(sl, dict) and sl.get('orderId') else '❌ SL Error'}"
        )
        await callback_query.message.answer(
            f"\u267B\ufe0f Ордер оновлено: {token}USDT — новий TP: {take_profit_price}, SL: {stop_loss_price}"
        )

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

    # ✅ Обробники для команд та кнопок меню
    dp.register_message_handler(start_cmd, commands=["start"])
    dp.register_message_handler(zarobyty_cmd, commands=["zarobyty"])
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
    dp.register_message_handler(show_balance, commands=["balance"])
    dp.register_message_handler(show_all_assets, commands=["all_assets"])
    dp.register_message_handler(show_support, commands=["support"])

    dp.register_message_handler(zarobyty_cmd, Text(contains="Заробити", ignore_case=True))
    dp.register_message_handler(show_balance, Text(contains="Баланс", ignore_case=True))
    dp.register_message_handler(show_all_assets, Text(contains="Всі активи", ignore_case=True))
    dp.register_message_handler(show_price_chart, Text(contains="Графік", ignore_case=True))
    dp.register_message_handler(show_gpt_forecast, Text(contains="Прогноз GPT", ignore_case=True))
    dp.register_message_handler(show_support, Text(contains="Підтримка", ignore_case=True))


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


@dp.message_handler(commands=["ордера"])
async def show_active_orders(message: types.Message) -> None:
    """Display currently active TP/SL orders stored locally."""

    orders = get_active_orders()
    if not orders:
        await message.answer("Немає активних ордерів на TP/SL.")
        return

    text = "📋 <b>Ваші активні TP/SL ордери:</b>\n"
    keyboard = InlineKeyboardMarkup(row_width=1)

    for symbol, data in orders.items():
        tp = data.get("take_profit")
        sl = data.get("stop_loss")
        updated = data.get("updated_at", "—")
        text += f"\n<b>{symbol}</b>\n🎯 TP: {tp}\n🛑 SL: {sl}\n🕒 {updated}\n"

        btn = InlineKeyboardButton(
            f"🔧 Змінити {symbol}", callback_data=f"edit_order:{symbol}"
        )
        keyboard.add(btn)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


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


@dp.message_handler(commands=["orders"])
@dp.message_handler(filters.Text(equals="📋 Змінити ордери"))
async def handle_edit_orders(message: types.Message) -> None:
    """Show editable open orders with cancel buttons."""
    open_orders = get_open_orders()
    if not open_orders:
        await message.reply("🔕 У вас немає активних TP/SL ордерів.")
        return

    buttons = [
        [
            InlineKeyboardButton(
                f"❌ Скасувати {o['symbol']} ({o['side']})",
                callback_data=f"cancel_{o['orderId']}",
            )
        ]
        for o in open_orders
    ]
    buttons.append([InlineKeyboardButton("🔁 Оновити", callback_data="refresh_orders")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.reply("🛠 Оберіть ордер для редагування:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith("cancel_"))
async def cancel_tp_sl(callback_query: types.CallbackQuery) -> None:
    order_id = int(callback_query.data.split("_")[1])
    success = cancel_order(order_id)
    if success:
        await callback_query.message.edit_text(f"✅ Ордер #{order_id} скасовано.")
    else:
        await callback_query.message.edit_text(
            f"⚠️ Помилка при скасуванні ордера #{order_id}."
        )


@dp.callback_query_handler(lambda c: c.data == "refresh_orders")
async def refresh_orders(callback_query: types.CallbackQuery) -> None:
    await handle_edit_orders(callback_query.message)


@dp.callback_query_handler(lambda c: c.data.startswith("edit_order:"))
async def edit_order_callback(callback_query: types.CallbackQuery) -> None:
    """Placeholder handler for editing TP/SL orders."""

    symbol = callback_query.data.split(":", 1)[1]
    await callback_query.answer(
        f"Редагування {symbol} поки не реалізовано.", show_alert=True
    )


async def show_balance(message: types.Message):
    balances = get_binance_balances()
    lines = [f"{sym}: {amount}" for sym, amount in balances.items()]
    await message.answer("\U0001F4B0 Баланс за токенами:\n" + "\n".join(lines))


async def show_price_chart(message: types.Message):
    await message.answer("\U0001F4C8 Введіть токен: /price24 BTC")


async def show_all_assets(message: types.Message):
    balances = get_binance_balances()
    await message.answer("\U0001F4E6 Всі активи на балансі:\n" + ", ".join(balances.keys()))


async def show_gpt_forecast(message: types.Message):
    await message.answer("\U0001F9E0 GPT прогноз:\n(Підтягується з останнього звіту...)")


async def show_support(message: types.Message):
    await message.answer("\U0001F9D1\u200d\U0001F4BB Пишіть адміну: @your_admin_username")

# added handler for UI button
@dp.message_handler(Text(equals="\U0001F4C8 Заробити"))
async def handle_zarobyty_button(message: types.Message) -> None:
    await zarobyty_cmd(message)

# added handler for UI button
@dp.message_handler(Text(equals="\U0001F4CA Баланс"))
async def handle_balance_button(message: types.Message) -> None:
    await show_balance(message)

# added handler for UI button
@dp.message_handler(Text(equals="\U0001F4E6 Всі активи"))
async def handle_all_assets_button(message: types.Message) -> None:
    await show_all_assets(message)

# added handler for UI button
@dp.message_handler(Text(equals="\U0001F4C8 Графік"))
async def handle_chart_button(message: types.Message) -> None:
    await show_price_chart(message)

# added handler for UI button
@dp.message_handler(Text(equals="\U0001F9E0 Прогноз GPT"))
async def handle_gpt_forecast_button(message: types.Message) -> None:
    await show_gpt_forecast(message)


async def check_tp_sl_market_change() -> None:
    """Update or close orders if market moved or trade older than 24h."""

    now = datetime.datetime.utcnow()
    orders = get_active_orders()
    for symbol, data in orders.items():
        if not data:
            continue
        entry_price = data.get("entry_price")
        ts = data.get("timestamp")
        if ts:
            try:
                trade_time = datetime.datetime.fromisoformat(ts)
            except ValueError:
                trade_time = None
        else:
            trade_time = None

        if trade_time and trade_time + datetime.timedelta(hours=24) < now and entry_price:
            current = get_current_price(symbol)
            pnl = (current - entry_price) / entry_price * 100
            if pnl > 2 or pnl < -3:
                sell_token_market(symbol)
                continue
            new_tp = round(current * 1.10, 6)
            new_sl = round(current * 0.95, 6)
            update_tp_sl_order(symbol, new_tp, new_sl)
        else:
            cancel_tp_sl_if_market_changed(symbol)


def register_change_tp_sl_handler(dp: Dispatcher) -> None:
    pending: dict[int, dict] = {}

    @dp.message_handler(Text(contains="Змінити TP/SL", ignore_case=True))
    async def select_token(message: types.Message) -> None:
        orders = get_active_orders()
        if not orders:
            await message.answer("Немає відкритих ордерів.")
            return
        keyboard = InlineKeyboardMarkup(row_width=1)
        for sym in orders.keys():
            keyboard.add(InlineKeyboardButton(sym, callback_data=f"change_tp_sl:{sym}"))
        await message.answer("Оберіть токен:", reply_markup=keyboard)

    @dp.callback_query_handler(lambda c: c.data.startswith("change_tp_sl:"))
    async def ask_tp(query: CallbackQuery) -> None:
        symbol = query.data.split(":", 1)[1]
        pending[query.from_user.id] = {"symbol": symbol}
        await bot.send_message(query.from_user.id, f"Введіть новий TP для {symbol}:", reply_markup=types.ForceReply())
        await query.answer()

    @dp.message_handler(lambda m: m.from_user.id in pending and "tp" not in pending[m.from_user.id])
    async def receive_tp(message: types.Message) -> None:
        try:
            tp = float(message.text.replace(",", "."))
        except ValueError:
            await message.reply("Невірне число TP")
            return
        pending[message.from_user.id]["tp"] = tp
        symbol = pending[message.from_user.id]["symbol"]
        await message.reply(f"Введіть новий SL для {symbol}:", reply_markup=types.ForceReply())

    @dp.message_handler(lambda m: m.from_user.id in pending and "tp" in pending[m.from_user.id])
    async def receive_sl(message: types.Message) -> None:
        data = pending.pop(message.from_user.id)
        symbol = data["symbol"]
        try:
            sl = float(message.text.replace(",", "."))
        except ValueError:
            await message.reply("Невірне число SL")
            return
        success = modify_order(symbol, data["tp"], sl)
        if success:
            await message.reply(f"✅ Ордер для {symbol} оновлено")
        else:
            await message.reply(f"❌ Не вдалося оновити ордер для {symbol}")

