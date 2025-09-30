#!/usr/bin/env bash
set -euo pipefail
# 1. лише config_dev3
if grep -RIl -E 'from\s+config_(?!dev3)\w+\s+import|import\s+config_(?!dev3)\w+' src >/dev/null; then
  echo "❌ Знайдено імпорти НЕ з config_dev3"; exit 1; fi
# 2. абстрактного import config немає
if grep -RIn -E '(^|[^a-zA-Z0-9_])import\s+config($|[^a-zA-Z0-9_])|from\s+config\s+import' src >/dev/null; then
  echo "❌ Знайдено абстрактний import config"; exit 1; fi
# 3. рантайм-інваріанти
PYTHONPATH="$(pwd):${PYTHONPATH:-}" python3 - <<'PY'
import importlib
m = importlib.import_module("config_dev3")
need = ["BINANCE_API_KEY","BINANCE_API_SECRET","BINANCE_SECRET_KEY","BASE","TIMEOUT","RECV_WINDOW_MS","RECV_WINDOW","RECVWINDOW"]
missing = [k for k in need if not hasattr(m,k)]
print("Config path:", m.__file__)
assert not missing, f"Missing: {missing}"
print("OK")
PY
echo "✅ Все ок"
