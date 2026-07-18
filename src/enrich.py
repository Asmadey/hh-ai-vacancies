"""Step 4: GET /vacancies/{id} → company, role, description(text), work_format,
employment, experience, key_skills, salary, apply_url."""
import re
import sys

from . import auth, config
from .fetch import format_salary
from .store import now_iso

TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text):
    text = TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _work_format(data):
    wf = data.get("work_format") or []
    if wf:
        return ", ".join(x.get("name", "") for x in wf if x.get("name"))
    sched = (data.get("schedule") or {}).get("name", "")
    return sched or ""


def enrich_record(rec, tokens, tokens_path=None):
    """Mutates rec in place. Returns (ok, tokens)."""
    url = f"{config.HH_API}/vacancies/{rec['vacancy_id']}"
    try:
        resp, tokens = auth.api_request("GET", url, tokens, tokens_path=tokens_path)
    except auth.AuthError:
        raise
    if resp.status != 200:
        print(f"[enrich] {rec['vacancy_id']} HTTP {resp.status}", file=sys.stderr)
        return False, tokens
    data = resp.json()
    rec["title"] = (data.get("name") or rec["title"]).strip()
    rec["company"] = ((data.get("employer") or {}).get("name") or rec.get("company", ""))
    desc = strip_html(data.get("description", ""))
    if len(desc) > 4000:
        desc = desc[:4000].rsplit(".", 1)[0] + "."
    rec["description"] = desc
    rec["work_format"] = _work_format(data)
    rec["employment"] = ((data.get("employment") or {}).get("name") or "")
    rec["experience"] = ((data.get("experience") or {}).get("name") or "")
    rec["key_skills"] = [s.get("name", "") for s in data.get("key_skills", []) if s.get("name")]
    if data.get("salary"):
        rec["salary"] = format_salary(data["salary"])
    if data.get("apply_alternate_url"):
        rec["apply_url"] = data["apply_alternate_url"]
    if data.get("alternate_url"):
        rec["url"] = data["alternate_url"]
    rec["enriched"] = True
    rec["updated_at"] = now_iso()
    # Вакансия ушла в архив между fetch и enrich
    if data.get("archived"):
        rec["status"] = config.STATUS_NOT_SENT
        rec["status_reason"] = "archived"
    return True, tokens


def enrich_new(store_dict, new_ids, tokens, tokens_path=None):
    """Returns (enriched_count, tokens)."""
    ok = 0
    for vid in new_ids:
        success, tokens = enrich_record(store_dict[vid], tokens, tokens_path=tokens_path)
        if success:
            ok += 1
    return ok, tokens
