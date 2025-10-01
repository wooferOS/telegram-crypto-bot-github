#!/usr/bin/env python3
import os
import sys
from pathlib import Path

import logging

try:
    import config_dev3 as _cfg
except Exception:
    _cfg = None
root_logger = logging.getLogger()
if not root_logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
try:
    import subprocess

    git_rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
except Exception:
    git_rev = "<nogit>"
logging.info("config in use: %s (rev %s)", getattr(_cfg, "__file__", "<unknown>"), git_rev)


REPO_DIR = os.path.dirname(__file__)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Ensure 'src' is a package so `from src.cli import main` works
init_path = os.path.join(REPO_DIR, "src", "__init__.py")
Path(init_path).touch()

from src.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
