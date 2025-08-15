import re, json, logging
log = logging.getLogger(__name__)


def safe_load_json(path: str):
    """
    Лояльний лоадер JSON для локальних службових файлів:
    - прибирає //... та /* ... */ коментарі
    - прибирає зайві коми перед } або ]
    - за потреби замінює одинарні лапки на подвійні
    Повертає Python-об'єкт або кидає виняток з детальним логом.
    """
    with open(path, "r", encoding="utf-8") as f:
        s = f.read()
    s1 = re.sub(r"//.*?$|/\*.*?\*/", "", s, flags=re.S | re.M)  # comments
    s1 = re.sub(r",(\s*[}\]])", r"\1", s1)  # trailing commas
    try:
        return json.loads(s1)
    except Exception as e1:
        s2 = re.sub(r"'", '"', s1)  # single→double quotes
        try:
            return json.loads(s2)
        except Exception as e2:
            log.error("❌ JSON load failed for %s: %s | after sanitize: %s", path, e1, e2)
            raise
