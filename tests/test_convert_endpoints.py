import pathlib
import re


def test_convert_endpoints_present():
    pattern = re.compile(r"sapi/v1/convert/(getQuote|acceptQuote|orderStatus|tradeFlow|exchangeInfo|assetInfo|limit)")
    found = []
    for p in pathlib.Path(".").rglob("*.py"):
        if "tests" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            found.append(str(p))
    assert found, "Convert endpoints must be present in code"
