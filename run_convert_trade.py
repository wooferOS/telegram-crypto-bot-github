#!/usr/bin/env python3
import os, sys
REPO_DIR = os.path.dirname(__file__)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# гарантуємо, що src — пакет
init_path = os.path.join(REPO_DIR, "src", "__init__.py")
if not os.path.exists(init_path):
    open(init_path, "a").close()

from src.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
