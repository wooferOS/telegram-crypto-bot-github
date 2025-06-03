# binance_api.py

import os
from binance.client import Client
from binance.exceptions import BinanceAPIException
from typing import Optional

# Завантаження ключів із оточення
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# Ініціалізація клієнта Binance
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Перевірка підключення
def ping_binance():
    try:
        client.ping()
        return True
    except Exception as e:
        print(f"❌ Binance ping failed: {e}")
        return False
# Отримати повний баланс акаунту
def get_account_balances():
    try:
        balances = client.get_account()['balances']
        return {b['asset']: float(b['free']) + float(b['locked']) for b in balances if float(b['free']) + float(b['locked']) > 0}
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException: {e}")
        return {}
    except Exception as e:
        print(f"❌ Error getting account balances: {e}")
        return {}

# Отримати баланс лише в USDT
def get_usdt_balance():
    balances = get_account_balances()
    return balances.get('USDT', 0.0)
# Отримати останні ціни всіх пар
def get_all_prices():
    try:
        prices = client.get_all_tickers()
        return {p['symbol']: float(p['price']) for p in prices}
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException: {e}")
        return {}
    except Exception as e:
        print(f"❌ Error getting prices: {e}")
        return {}

# Побудувати портфель у USDT
def get_current_portfolio() -> Dict[str, float]:
    balances = get_account_balances()
    prices = get_all_prices()
    portfolio = {}

    for asset, amount in balances.items():
        if asset == 'USDT':
            portfolio['USDT'] = amount
        else:
            symbol = f"{asset}USDT"
            price = prices.get(symbol)
            if price:
                value_usdt = amount * price
                portfolio[asset] = value_usdt

    return portfolio

# Отримати історію угод по символу
def get_trade_history(symbol: str):
    try:
        trades = client.get_my_trades(symbol=symbol)
        return trades
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException (trades): {e}")
        return []
    except Exception as e:
        print(f"❌ Error getting trade history: {e}")
        return []

# Підрахунок прибутку/збитку по символу
def calculate_pnl(symbol: str):
    trades = get_trade_history(symbol)
    total_qty = 0.0
    total_cost = 0.0
    total_income = 0.0

    for trade in trades:
        qty = float(trade['qty'])
        price = float(trade['price'])
        commission = float(trade['commission'])

        if trade['isBuyer']:
            total_qty += qty
            total_cost += qty * price + commission
        else:
            total_qty -= qty
            total_income += qty * price - commission

    realized_pnl = total_income - total_cost
    return round(realized_pnl, 2)
# Купити криптовалюту за маркет-ордером
def market_buy(symbol: str, quote_quantity: float):
    try:
        order = client.order_market_buy(
            symbol=symbol,
            quoteOrderQty=round(quote_quantity, 2)
        )
        print(f"✅ Куплено {symbol} на {quote_quantity} USDT")
        return order
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException (buy): {e}")
        return None
    except Exception as e:
        print(f"❌ Error placing buy order: {e}")
        return None
# Продати криптовалюту за маркет-ордером
def market_sell(symbol: str, quantity: float):
    try:
        order = client.order_market_sell(
            symbol=symbol,
            quantity=round(quantity, 6)  # округлення для мінімальної точності
        )
        print(f"✅ Продано {symbol} у кількості {quantity}")
        return order
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException (sell): {e}")
        return None
    except Exception as e:
        print(f"❌ Error placing sell order: {e}")
        return None
# Отримати історію ордерів для символу
def get_order_history(symbol: str, limit: int = 10):
    try:
        orders = client.get_all_orders(symbol=symbol, limit=limit)
        print(f"📜 Історія ордерів для {symbol} отримана")
        return orders
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException (order history): {e}")
        return []
    except Exception as e:
        print(f"❌ Error getting order history: {e}")
        return []
# Отримати всі відкриті ордери
def get_open_orders(symbol: str = None):
    try:
        if symbol:
            orders = client.get_open_orders(symbol=symbol)
        else:
            orders = client.get_open_orders()
        print(f"📂 Відкриті ордери отримані")
        return orders
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException (open orders): {e}")
        return []
    except Exception as e:
        print(f"❌ Error getting open orders: {e}")
        return []

# Скасувати ордер за ID
def cancel_order(symbol: str, order_id: int):
    try:
        result = client.cancel_order(symbol=symbol, orderId=order_id)
        print(f"🛑 Ордер {order_id} скасовано")
        return result
    except BinanceAPIException as e:
        print(f"❌ BinanceAPIException (cancel): {e}")
        return None
    except Exception as e:
        print(f"❌ Error cancelling order: {e}")
        return None
# Отримати мінімальні кроки для символу (кількість і ціна)
def get_symbol_filters(symbol: str):
    try:
        info = client.get_symbol_info(symbol)
        filters = {f['filterType']: f for f in info['filters']}
        lot_size = float(filters['LOT_SIZE']['stepSize'])
        price_tick = float(filters['PRICE_FILTER']['tickSize'])
        return lot_size, price_tick
    except Exception as e:
        print(f"❌ Error getting symbol filters: {e}")
        return 0.001, 0.01  # safe defaults

# Округлення кількості згідно з правилами Binance
def round_quantity(symbol: str, quantity: float) -> float:
    lot_size, _ = get_symbol_filters(symbol)
    rounded = math.floor(quantity / lot_size) * lot_size
    return round(rounded, 8)

# Округлення ціни згідно з правилами Binance
def round_price(symbol: str, price: float) -> float:
    _, price_tick = get_symbol_filters(symbol)
    rounded = round(math.floor(price / price_tick) * price_tick, 8)
    return rounded
# Створення стоп-лосу
def set_stop_loss(symbol: str, quantity: float, stop_price: float) -> Optional[str]:
    try:
        stop_price = round_price(symbol, stop_price)
        quantity = round_quantity(symbol, quantity)

        order = client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_STOP_LOSS_LIMIT,
            quantity=quantity,
            stopPrice=stop_price,
            price=stop_price * 0.99,  # трохи нижче
            timeInForce=TIME_IN_FORCE_GTC
        )
        print(f"✅ Stop-loss set for {symbol}: {order}")
        return order['orderId']
    except Exception as e:
        print(f"❌ Error setting stop-loss: {e}")
        return None

# Створення тейк-профіту
def set_take_profit(symbol: str, quantity: float, target_price: float) -> Optional[str]:
    try:
        target_price = round_price(symbol, target_price)
        quantity = round_quantity(symbol, quantity)

        order = client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_LIMIT,
            quantity=quantity,
            price=target_price,
            timeInForce=TIME_IN_FORCE_GTC
        )
        print(f"✅ Take-profit set for {symbol}: {order}")
        return order['orderId']
    except Exception as e:
        print(f"❌ Error setting take-profit: {e}")
        return None
