#!/usr/bin/env python3
import os
import sys
from pathlib import Path

REPO_DIR = os.path.dirname(__file__)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Ensure 'src' is a package so `from src.cli import main` works
init_path = os.path.join(REPO_DIR, "src", "__init__.py")
Path(init_path).touch()

from src.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
