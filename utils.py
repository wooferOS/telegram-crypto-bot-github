import requests

def get_price_usdt():
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTUAH")
        return float(res.json()["price"])
    except:
        return 39.5  # резервний курс, якщо Binance не працює

def convert_to_uah(usdt_amount):
    rate = get_price_usdt()
    return round(usdt_amount * rate, 2)
