"""
Core package: explicit imports only (no lazy getattr) to avoid import recursion.
"""

from . import binance_client  # HTTP client wrappers for Binance
from . import convert_api     # Convert endpoints + helpers
from . import utils           # misc helpers
from . import balance         # balance & accounting helpers

__all__ = ["binance_client", "convert_api", "utils", "balance"]
