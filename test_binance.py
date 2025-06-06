from binance_api import (
    get_usdt_balance,
    get_token_balance,
    get_symbol_price,
    place_market_order,
)


def test_balance() -> None:
    """Print available balances for USDT, BTC and ETH."""
    print("\U0001F4BC USDT Balance:", get_usdt_balance())
    print("\U0001F4BC BTC Balance:", get_token_balance("BTC"))
    print("\U0001F4BC ETH Balance:", get_token_balance("ETH"))


def test_price() -> None:
    """Print current prices for BTC and ETH."""
    print("\U0001F4C8 BTC Price:", get_symbol_price("BTC"))
    print("\U0001F4C8 ETH Price:", get_symbol_price("ETH"))


def test_order() -> None:
    """Show how to place a market order (disabled by default)."""
    print("\U0001F501 [!!!] \u041E\u0440\u0434\u0435\u0440 \u041D\u0415 \u043D\u0430\u0434\u0441\u0438\u043B\u0430\u0454\u0442\u044C\u0441\u044F \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0438\u0447\u043D\u043E.")
    print("\U0001F6D1 \u0420\u043E\u0437\u043A\u043E\u043C\u0435\u043D\u0442\u0443\u0439\u0442\u0435, \u0449\u043E\u0431 \u0437\u0430\u043F\u0443\u0441\u0442\u0438\u0442\u0438 \u0440\u0435\u0430\u043B\u044C\u043D\u0438\u0439 \u043E\u0440\u0434\u0435\u0440.")
    # place_market_order("BTC", "BUY", quantity=0.001)


if __name__ == "__main__":
    print("\U0001F50D \u0422\u0435\u0441\u0442 Binance API\n")
    test_balance()
    test_price()
    # test_order()
