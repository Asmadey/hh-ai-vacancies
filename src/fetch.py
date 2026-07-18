"""Step 2: GET /vacancies по 13 AI-ключам + фильтры junk/archive/relevance."""
import re
import sys
import urllib.parse

from . import auth, config, store


def parse_level(title):
    t = title.lower()
    if "head" in t or "директор" in t or "director" in t or "руководитель направления" in t:
        return "head"
    if "lead" in t or "руководитель" in t or "ведущий" in t:
        return "lead"
    if "senior" in t or "старший" in t:
        return "senior"
    if "principal" in t or "staff" in t:
        return "principal"
    if "junior" in t or "младший" in t or "intern" in t or "стажер" in t:
        return "junior"
    return "middle"


def match_reason(title, snippet=""):
    text = f"{title} {snippet}".lower()
    if "ai" in text or "ии" in text or "artificial intelligence" in text or "machine learning" in text:
        if re.search(r"\b(lead|head|директор|director|руководитель|manager|менеджер|владелец|owner)\b", text):
            return "AI + управленческая роль"
        return "AI-роль"
    if re.search(r"\b(transformation|трансформация|implementation|внедрение)\b", text):
        return "AI-трансформация / внедрение"
    if re.search(r"\b(product|продукт)\b", text) and re.search(r"\b(manager|менеджер|lead|owner|владелец)\b", text):
        return "Product-роль"
    return "Смежная роль"


def is_active(title, snippet=""):
    return not config.ARCHIVE_RE.search(f"{title} {snippet}")


def is_relevant(title, snippet=""):
    text = f"{title} {snippet}".lower()
    has_kw = any(kw.lower() in text for kw in config.KEYWORDS)
    has_ai = re.search(r"\b(ai|artificial intelligence|machine learning|ml|llm|агент|agent)\b", text)
    if not has_kw and not has_ai:
        return False
    if config.JUNK_RE.search(title) or config.RESUME_RE.search(title):
        return False
    return True


def format_salary(salary):
    if not salary:
        return "не указана"
    parts = []
    if salary.get("from"):
        parts.append(f"от {salary['from']:,}")
    if salary.get("to"):
        parts.append(f"до {salary['to']:,}")
    out = " ".join(parts)
    if salary.get("currency"):
        out += f" {salary['currency']}"
    gross = salary.get("gross")
    if gross is not None:
        out += " gross" if gross else " net"
    return out.strip() or "не указана"


def item_to_record(item):
    title = (item.get("name") or "").strip()
    url = (item.get("alternate_url") or "").strip()
    vid = item.get("id") or store.vacancy_id_from_url(url)
    if not title or not url or not vid:
        return None
    snippet = (item.get("snippet") or {}).get("requirement") or ""
    return store.new_record(
        vid, url, title,
        apply_url=item.get("apply_alternate_url") or url,
        company=((item.get("employer") or {}).get("name") or ""),
        salary=format_salary(item.get("salary")),
        location=((item.get("area") or {}).get("name") or "Remote / unspecified"),
        level=parse_level(title),
        match=match_reason(title, snippet),
    )


def fetch_all(tokens, tokens_path=None):
    """Returns (records, found_total, tokens). Any keyword failure is logged; total API-down raises."""
    records, seen_ids = [], set()
    found_total = 0
    errors = 0
    for kw in config.KEYWORDS:
        params = urllib.parse.urlencode({
            "text": kw, "search_field": "name", "per_page": 50, "page": 0,
            "order_by": "publication_time",
        })
        url = f"{config.HH_API}/vacancies?{params}"
        try:
            resp, tokens = auth.api_request("GET", url, tokens, tokens_path=tokens_path)
        except auth.AuthError:
            raise
        if resp.status != 200:
            print(f"[fetch] '{kw}' HTTP {resp.status}", file=sys.stderr)
            errors += 1
            continue
        data = resp.json()
        found_total += data.get("found", 0)
        for item in data.get("items", []):
            rec = item_to_record(item)
            if not rec:
                continue
            snippet = (item.get("snippet") or {}).get("requirement") or ""
            if not is_active(rec["title"], snippet) or not is_relevant(rec["title"], snippet):
                continue
            if rec["vacancy_id"] in seen_ids:
                continue
            seen_ids.add(rec["vacancy_id"])
            records.append(rec)
    if errors == len(config.KEYWORDS):
        raise RuntimeError("fetch failed for ALL keywords — HH API down?")
    return records, found_total, tokens
