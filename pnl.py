import json
from datetime import datetime
import os

def get_daily_pnl(trade_history_path="trade_history.json"):
    if not os.path.exists(trade_history_path):
        return {"pnl": 0.0, "pnl_percent": 0.0, "details": []}

    with open(trade_history_path, "r") as f:
        data = json.load(f)

    today = datetime.now().strftime("%Y-%m-%d")
    total_buy = 0.0
    total_sell = 0.0
    details = []

    for item in data:
        if item["timestamp"].startswith(today):
            if item["action"] == "buy":
                total_buy += item["usdt_amount"]
                details.append(f"🟢 Куплено {item['symbol']} на {item['usdt_amount']} USDT")
            elif item["action"] == "sell":
                total_sell += item["usdt_amount"]
                details.append(f"🔴 Продано {item['symbol']} на {item['usdt_amount']} USDT")

    pnl = total_sell - total_buy
    pnl_percent = (pnl / total_buy) * 100 if total_buy > 0 else 0

    return {
        "pnl": round(pnl, 2),
        "pnl_percent": round(pnl_percent, 2),
        "details": details,
    }
