import pathlib
import re

def test_no_spot_order_endpoints_present():
    bad = []
    for p in pathlib.Path('.').rglob('*.py'):
        if p.name.startswith('test_'):
            continue
        text = p.read_text(encoding='utf-8', errors='ignore')
        if re.search(r'/api/v3/order|newOrder|MARKET|LIMIT', text):
            bad.append(str(p))
    assert not bad, f"Spot order endpoints must not be present in DEV7: {bad}"
