"""data/vacancies.json — единый source of truth. Ключ: vacancy_id.
Sheets НИКОГДА не читается — только пишется (sheets_export)."""
import json
import os
import re
import shutil
from datetime import datetime, timezone

from . import config

# Schema: field -> (type, required)
SCHEMA = {
    "vacancy_id":    (str, True),
    "url":           (str, True),
    "apply_url":     (str, False),
    "title":         (str, True),
    "company":       (str, False),
    "salary":        (str, False),
    "location":      (str, False),
    "level":         (str, False),
    "work_format":   (str, False),
    "employment":    (str, False),
    "experience":    (str, False),
    "key_skills":    (list, False),
    "description":   (str, False),
    "match":         (str, False),
    "cover_letter":  (str, False),
    "status":        (str, True),   # ∈ VALID_STATUSES
    "status_reason": (str, False),
    "first_seen":    (str, True),
    "updated_at":    (str, True),
    "applied_at":    (str, False),
    "enriched":      (bool, False),
    "migrated":      (bool, False),
}

VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def vacancy_id_from_url(url):
    m = VACANCY_ID_RE.search(url or "")
    return m.group(1) if m else None


def new_record(vacancy_id, url, title, **kw):
    ts = now_iso()
    rec = {
        "vacancy_id": str(vacancy_id), "url": url, "apply_url": kw.get("apply_url", url),
        "title": title, "company": kw.get("company", ""), "salary": kw.get("salary", ""),
        "location": kw.get("location", ""), "level": kw.get("level", ""),
        "work_format": kw.get("work_format", ""), "employment": kw.get("employment", ""),
        "experience": kw.get("experience", ""), "key_skills": kw.get("key_skills", []),
        "description": kw.get("description", ""), "match": kw.get("match", ""),
        "cover_letter": kw.get("cover_letter", ""),
        "status": kw.get("status", config.STATUS_NOT_SENT),
        "status_reason": kw.get("status_reason", "new"),
        "first_seen": ts, "updated_at": ts, "applied_at": "",
        "enriched": False, "migrated": kw.get("migrated", False),
    }
    return rec


def validate_record(rec):
    """Return list of problems (empty = valid)."""
    problems = []
    if not isinstance(rec, dict):
        return ["not a dict"]
    for field, (ftype, required) in SCHEMA.items():
        if field not in rec:
            if required:
                problems.append(f"missing:{field}")
            continue
        if not isinstance(rec[field], ftype):
            problems.append(f"type:{field}")
    if rec.get("status") not in config.VALID_STATUSES:
        problems.append(f"bad_status:{rec.get('status')!r}")
    return problems


def load(path=None):
    path = path or config.vacancies_path()
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("vacancies.json must be an object keyed by vacancy_id")
    return data


def save(store, path=None):
    """Atomic save with .bak backup of previous version (никогда не перезаписываем без бэкапа)."""
    path = path or config.vacancies_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def merge(store, fetched_records):
    """Merge fetched records into store. Existing records preserved & refreshed
    (title/salary/etc updated; status/cover_letter/first_seen NEVER touched).
    Returns list of vacancy_ids that are NEW."""
    new_ids = []
    for rec in fetched_records:
        vid = rec["vacancy_id"]
        if vid in store:
            old = store[vid]
            for f in ("title", "company", "salary", "location", "level", "match", "url", "apply_url"):
                if rec.get(f):
                    old[f] = rec[f]
            old["updated_at"] = now_iso()
        else:
            store[vid] = rec
            new_ids.append(vid)
    return new_ids


def duplicates(store):
    """0 by construction (dict), but verify id integrity: key == record.vacancy_id."""
    return [k for k, v in store.items() if str(v.get("vacancy_id")) != str(k)]


def migrate_seen(seen_path=None, store=None):
    """Migrate legacy seen.json (url -> iso_ts) into store as skeleton records.
    Marked migrated=True → apply step never touches them."""
    seen_path = seen_path or config.LEGACY_SEEN_PATH
    store = store if store is not None else {}
    if not os.path.exists(seen_path):
        return store, 0
    with open(seen_path, encoding="utf-8") as fh:
        seen = json.load(fh)
    n = 0
    for url, ts in seen.items():
        vid = vacancy_id_from_url(url)
        if not vid or vid in store:
            continue
        rec = new_record(vid, url, title="(migrated from seen.json)",
                         status=config.STATUS_NOT_SENT, status_reason="migrated",
                         migrated=True)
        rec["first_seen"] = ts if isinstance(ts, str) else rec["first_seen"]
        store[vid] = rec
        n += 1
    return store, n
