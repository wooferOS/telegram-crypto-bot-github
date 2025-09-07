"""DEV7 runtime utilities."""

import pathlib
import re

FORBIDDEN = [r'\.env\b', r'\bdotenv\b', r'os\.getenv\(', r'EnvironmentFile=']


def assert_config_only_credentials() -> None:
    """Ensure no forbidden credential sources are present."""
    root = pathlib.Path(__file__).resolve().parent
    for path in root.rglob('*.py'):
        if path.name == 'config_dev3.py':
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        if any(re.search(pat, text) for pat in FORBIDDEN):
            raise RuntimeError(f'Forbidden cred source in {path}')
    if not (root / 'config_dev3.py').exists():
        raise RuntimeError('config_dev3.py missing (single source of secrets)')
