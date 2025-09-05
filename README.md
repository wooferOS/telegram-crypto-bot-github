# Telegram Crypto Bot

This project interacts with Binance Convert endpoints. Binance API keys are **not** stored in `.env` files or systemd unit definitions.

## Binance credentials

The only canonical location for Binance keys on the host is `/root/telegram-crypto-bot-github/config_dev3.py` (or a path pointed to by `DEV_CONFIG_PATH`). The file must define:

```python
BINANCE_API_KEY = "..."
BINANCE_API_SECRET = "..."
```

At runtime the application loads these credentials from that file. If the file is missing, it falls back to `BINANCE_API_KEY` and `BINANCE_API_SECRET` environment variables.

For temporary shells you can export the variables without duplicating secrets:

```bash
export BINANCE_KEY=$(python3 - <<'PY'
import importlib.util
p="/root/telegram-crypto-bot-github/config_dev3.py"
spec=importlib.util.spec_from_file_location("cfg", p)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(getattr(m, "BINANCE_API_KEY", ""))
PY
)

export BINANCE_SECRET=$(python3 - <<'PY'
import importlib.util
p="/root/telegram-crypto-bot-github/config_dev3.py"
spec=importlib.util.spec_from_file_location("cfg", p)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(getattr(m, "BINANCE_API_SECRET", ""))
PY
)
```

Systemd units do not embed secrets; they rely on the above configuration file or explicitly exported environment variables before launch.
