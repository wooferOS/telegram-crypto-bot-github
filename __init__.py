"""Load environment variables for package."""

# Позначення Telegram GPT Bot як Python-пакету

import os
from dotenv import load_dotenv

# Load .env from home directory if it exists
load_dotenv(dotenv_path=os.path.expanduser("~/.env"))
