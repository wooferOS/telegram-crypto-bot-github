#!/usr/bin/env python3
import time, importlib.util, sys
P="/root/telegram-crypto-bot-github/config_dev3.py"
spec=importlib.util.spec_from_file_location("cfg", P); cfg=importlib.util.module_from_spec(spec); spec.loader.exec_module(cfg)
ts=time.strftime("[%F %T]")
need=["BINANCE_API_KEY","BINANCE_API_SECRET","TELEGRAM_CHAT_ID"]
missing=[k for k in need if not getattr(cfg,k, None)]
if missing:
    print(f"{ts} protect_balance: STUB — відсутні у config_dev3.py: {', '.join(missing)}"); sys.exit(0)
print(f"{ts} protect_balance: STUB OK (усе зчитано з config_dev3.py)")
