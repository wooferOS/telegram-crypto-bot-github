import logging
import os


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger to also log to ``logs/trade.log``."""
    log_path = os.path.join("logs", "trade.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    has_file = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith("trade.log")
        for h in root.handlers
    )
    if not has_file:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(logging.StreamHandler())

