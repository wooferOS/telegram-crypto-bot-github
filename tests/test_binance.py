from binance.client import Client
import os

def test_connection():
    client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"))
    status = client.get_system_status()
    assert status["status"] == 0
