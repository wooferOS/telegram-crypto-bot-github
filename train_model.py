from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from binance.client import Client
from ml_model import generate_features, MODEL_PATH
import joblib
import numpy as np
import os
import time

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(api_key=api_key, api_secret=api_secret)


def get_all_usdt_symbols():
    exchange_info = client.get_exchange_info()
    symbols = []
    for s in exchange_info["symbols"]:
        if (
            s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
            and not s["isMarginTradingAllowed"]
            and s["isSpotTradingAllowed"]
        ):
            symbols.append(s["symbol"])
    return list(set(symbols))


symbols = get_all_usdt_symbols()
print(f"🔍 Знайдено {len(symbols)} монет для тренування.")

X_all = []
y_all = []

for symbol in symbols:
    try:
        _, X, y = generate_features(symbol)
        X_all.append(X)
        y_all.append(y)
        print(f"✅ Додано {symbol}: {len(X)} зразків")
        time.sleep(0.3)
    except Exception as e:
        print(f"⚠️ Пропущено {symbol}: {e}")

if not X_all:
    print("❌ Дані не зібрано. Перевір Binance API або generate_features.")
    exit(1)

X_all = np.vstack(X_all)
y_all = np.concatenate(y_all)

X_train, X_test, y_train, y_test = train_test_split(X_all, y_all, test_size=0.2, random_state=42)

model = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
print(classification_report(y_test, y_pred))

joblib.dump(model, MODEL_PATH)
print(f"✅ Model saved to {MODEL_PATH}")
