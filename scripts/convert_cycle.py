#!/usr/bin/env python3
import logging
import sys
import subprocess

# 1) одноразовий лог конфіга + git ревізії
try:
    import config_dev3 as _cfg
except Exception:
    _cfg = None
try:
    git_rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
except Exception:
    git_rev = "<nogit>"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.info("config in use: %s (rev %s)", getattr(_cfg, "__file__", "<unknown>"), git_rev)

# 2) виконуємо фази в одному процесі
from src import app  # app.run(region:str, phase:str, dry_run:bool)->int


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: convert_cycle.py <region>", file=sys.stderr)
        return 2
    region = sys.argv[1]
    phases = ["pre-analyze", "analyze", "trade", "guard"]
    rc_total = 0
    for ph in phases:
        rc = app.run(region=region, phase=ph, dry_run=False)
        rc_total |= 0 if rc is None else int(rc)
    return rc_total


if __name__ == "__main__":
    sys.exit(main())
