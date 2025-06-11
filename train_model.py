from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
from ml_model import generate_features, MODEL_PATH

SYMBOL = "BTCUSDT"

_, X_full, y_full = generate_features(SYMBOL)
X_train, X_test, y_train, y_test = train_test_split(X_full, y_full, test_size=0.2, random_state=42)

model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
print(classification_report(y_test, y_pred))

joblib.dump(model, MODEL_PATH)
print(f"✅ Model saved to {MODEL_PATH}")
