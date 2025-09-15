import json, time, os
from top_tokens_utils import allowed_tos_for
from convert_cycle import _get_legal_money_set

def test_no_fiat_in_allowed_tos():
    os.makedirs("logs", exist_ok=True)
    data = {"version":"v1","region":"dev3","generated_at":int(time.time()*1000),
            "pairs":[{"from":"USDT","to":"EUR"},{"from":"USDT","to":"BTC"}]}
    with open("logs/top_tokens.dev3.json","w",encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tos = allowed_tos_for("USDT","dev3")
    fiats = _get_legal_money_set(1)
    assert "EUR" not in tos and not (set(tos) & fiats)
