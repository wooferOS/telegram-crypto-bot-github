import logging
import urllib.parse

try:
    import requests
except Exception:
    requests = None

if requests and not getattr(requests.Session, "_dev3_acceptquote_patched", False):
    _orig = requests.Session.request
    _log = logging.getLogger("dev3.acceptQuote.guard")

    def _patched(self, method, url, *args, **kw):
        m = (method or "").upper()
        u = str(url)
        # Якщо абсолютний URL і це не наш спец-кейс acceptQuote — нічого не змінюємо
        if u.startswith(("http://", "https://")) and "/sapi/v1/convert/acceptQuote" not in u:
            return _orig(self, method, url, *args, **kw)
        m = (method or "").upper()
        u = str(url)
        if m == "POST" and "/sapi/v1/convert/acceptQuote" in u:
            # 1) quoteId з URL або kw["params"]
            qid = None
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(u).query or "")
                v = qs.get("quoteId", [])
                if v:
                    qid = "" if v[0] is None else str(v[0])
            except Exception as e:
                _log.warning("acceptQuote url-parse warn: %s", e)
            p = kw.get("params")
            if isinstance(p, dict) and "quoteId" in p and p["quoteId"] not in (None, "", [], b""):
                qid = str(p["quoteId"])

            # 2) data як dict; підкласти quoteId у body, якщо є в query
            d = kw.get("data")
            if d is None:
                d = {}
            elif not isinstance(d, dict):
                try:
                    d = dict(d)
                except Exception:
                    pass
            if isinstance(d, dict):
                if "quoteId" not in d and qid not in (None, ""):
                    d["quoteId"] = qid
                    kw["data"] = d

            body_qid = (kw.get("data") or {}).get("quoteId") if isinstance(kw.get("data"), dict) else None
            if (qid in (None, "")) and (body_qid in (None, "")):
                raise RuntimeError("acceptQuote blocked due to empty quoteId")

        return _orig(self, method, url, *args, **kw)

    requests.Session.request = _patched
    requests.Session._dev3_acceptquote_patched = True
