import os


def load_env_file(path: str) -> None:
    """Load environment variables from a simple KEY=VALUE file."""
    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()
    except FileNotFoundError:
        # Silently ignore missing env file
        pass

__all__ = ["load_env_file"]
