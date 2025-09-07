import pathlib
import re

def test_no_env_or_dotenv_anywhere():
    pat = re.compile(r'\.env|dotenv|os\.getenv|EnvironmentFile')
    offenders = []
    for p in pathlib.Path('.').rglob('*.py'):
        if p.name in {'config_dev3.py', 'utils_dev3.py'} or p.name.startswith('test_'):
            continue
        text = p.read_text(encoding='utf-8', errors='ignore')
        if pat.search(text):
            offenders.append(str(p))
    assert not offenders, f'Forbidden patterns detected: {offenders}'
