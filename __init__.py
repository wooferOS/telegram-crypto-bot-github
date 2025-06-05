"""Load environment variables for package."""

import os
from dotenv import load_dotenv

# Load .env from home directory if it exists
load_dotenv(dotenv_path=os.path.expanduser("~/.env"))
