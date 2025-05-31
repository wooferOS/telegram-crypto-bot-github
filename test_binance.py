from binance.client import Client
from binance.exceptions import BinanceAPIException

api_key = "7zu1Xp37QaruOrV5zyHX3wDAn212nIfVQJ1188YNxnArKZ2hOanXJ4VnP8IBP1Ru"
api_secret = "4zNgn93gdCQqjnY3unkoGGHOmHRupMR2POE4cxlG6c2OY5V8XZVe3rxDBS0laLye"

client = Client(api_key=api_key, api_secret=api_secret)

try:
    account_info = client.get_account()
    print("✅ Успіх! Доступ до Binance працює:")
    print(account_info)
except BinanceAPIException as e:
    print("❌ Помилка Binance API:")
    print(e)
