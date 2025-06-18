import re


def parse_gpt_forecast(text: str) -> dict:
    do_not_sell = set()
    do_not_buy = set()
    recommend_buy = set()

    for line in text.splitlines():
        line = line.lower()
        if "не продавати" in line or "залишити" in line:
            do_not_sell.update(re.findall(r"\b[A-Z0-9]{2,10}\b", line.upper()))
        if "не купувати" in line or "уникати" in line or "смітник" in line:
            do_not_buy.update(re.findall(r"\b[A-Z0-9]{2,10}\b", line.upper()))
        if "купити" in line or "рекомендується" in line or "високий потенціал" in line:
            recommend_buy.update(re.findall(r"\b[A-Z0-9]{2,10}\b", line.upper()))

    return {
        "do_not_sell": list(do_not_sell),
        "do_not_buy": list(do_not_buy),
        "recommend_buy": list(recommend_buy),
    }
