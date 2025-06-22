from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from binance.client import Client
from ml_model import generate_features, MODEL_PATH
import joblib
import numpy as np
import os
import time
import subprocess
import logging
from config import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
)

client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)


def get_all_usdt_symbols(min_volume=500000):
    tickers = client.get_ticker()
    result = []
    for t in tickers:
        if (
            t.get('symbol').endswith("USDT")
            and not t.get('symbol').startswith(("USDT", "XUSD", "TUSD", "EUR", "BIFI", "USDP"))
            and float(t.get("quoteVolume", 0)) > min_volume
        ):
            result.append(t.get('symbol'))
    return list(set(result))


logger = logging.getLogger(__name__)

symbols = get_all_usdt_symbols()
logger.info("🔍 Знайдено %d монет для тренування.", len(symbols))

X_all = []
y_all = []

for symbol in symbols:
    try:
        _, X_raw, y_raw = generate_features(symbol)
        if len(X_raw) > 10:
            X = X_raw.replace([np.inf, -np.inf], np.nan)
            X = X.dropna()
            y = y_raw[-len(X):]

            if len(X) > 10:
                X_all.append(X)
                y_all.append(y)
                logger.info("✅ Додано %s: %d зразків", symbol, len(X))
        time.sleep(0.3)
    except Exception as e:
        logger.warning("⚠️ Пропущено %s: %s", symbol, e)

if not X_all:
    logger.error("❌ Дані не зібрано.")
    exit(1)

X_all = np.vstack([x.values for x in X_all])
y_all = np.concatenate(y_all)

X_train, X_test, y_train, y_test = train_test_split(X_all, y_all, test_size=0.2, random_state=42)

model = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
logger.info("\n" + classification_report(y_test, y_pred))

joblib.dump(model, MODEL_PATH)
logger.info("✅ Model saved to %s", MODEL_PATH)

# 🔁 Автоматичний перезапуск Telegram бота
subprocess.call(["sudo", "systemctl", "restart", "crypto-bot"])
logger.info("🔁 Бот перезапущено після оновлення моделі")
