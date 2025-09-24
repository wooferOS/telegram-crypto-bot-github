from typing import Dict, Any
from src.core import binance_client

def get_exchange_info(from_asset: str, to_asset: str) -> Dict[str, Any]:
    # Кешований виклик у binance_client
    return binance_client.get_convert_exchange_info(from_asset, to_asset)

def get_quote(from_asset: str, to_asset: str, amount: float, wallet: str) -> Dict[str, Any]:
    w = (wallet or "SPOT").upper()
    if w not in ("SPOT", "FUNDING"):
        raise ValueError("wallet must be SPOT or FUNDING")
    params = {
        "fromAsset":  from_asset,
        "toAsset":    to_asset,
        "fromAmount": str(amount),
        "walletType": w,
    }
    # Повертає dict (або кине HTTP/RequestException нагору)
    return binance_client.post("/sapi/v1/convert/getQuote", params, signed=True)

def accept_quote(quote_id: str, *_, **__) -> Dict[str, Any]:
    return binance_client.post("/sapi/v1/convert/acceptQuote", {"quoteId": quote_id}, signed=True)

def order_status(order_id: str) -> Dict[str, Any]:
    return binance_client.get("/sapi/v1/convert/orderStatus", {"orderId": order_id}, signed=True)
