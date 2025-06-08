from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def zarobyty_keyboard(buy: list, sell: list) -> InlineKeyboardMarkup:
    buttons = []

    for b in buy:
        buttons.append([InlineKeyboardButton(f"\U0001F7E2 \u041a\u0443\u043f\u0438\u0442\u0438 {b['symbol']}", callback_data=f"confirmbuy_{b['symbol']}")])

    for s in sell:
        buttons.append([InlineKeyboardButton(f"\U0001F534 \u041f\u0440\u043e\u0434\u0430\u0442\u0438 {s['symbol']}", callback_data=f"confirmsell_{s['symbol']}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
