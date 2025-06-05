# Telegram GPT Crypto Bot

Simple Telegram bot that sends daily crypto reports and example trade alerts.

## Features
- Daily portfolio report via `daily_analysis.py`.
- Commands `/start`, `/zarobyty`, `/stats`, `/history`, `/statsday`, `/alerts_on`.
- Tokens are loaded from `.env` (expected at `~/.env`) using `python-dotenv`.
- Works with `aiogram==2.25.2`.
- Can be run with systemd using `systemd/crypto-bot.service`.

## Setup
1. Install dependencies: `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and fill your secrets.
3. Run `python3 main.py` or enable systemd service. Scheduler runs inside the
   bot event loop via `asyncio.run(main())`.
