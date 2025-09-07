# Telegram Crypto Bot

This project interacts with Binance Convert endpoints. Binance API keys are **not** stored in `.env` files or systemd unit definitions.

## Binance credentials

The only canonical location for Binance keys on the host is `/root/telegram-crypto-bot-github/config_dev3.py` (or a path pointed to by `DEV_CONFIG_PATH`). The file must define:

```python
BINANCE_API_KEY = "..."
BINANCE_API_SECRET = "..."
```

At runtime the application **only** loads these credentials from `config_dev3.py`. Environment variables and `.env` files are **not** used or supported for secrets.

Systemd units do not embed secrets; they rely exclusively on the above configuration file.
