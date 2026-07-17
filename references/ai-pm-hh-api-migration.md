# AI/PM vacancy tracker: migration from web-search stdin to HeadHunter API

Date: 2026-07-05
Context: cron job `Ежедневный поиск вакансий AI/PM` (job_id 6d9bd734b2ab)

## What changed

The deterministic processor `~/.hermes/scripts/ai_pm_vacancies.py` previously:

- read raw results from stdin as a JSON array;
- fell back to Hermes/Firecrawl-style web search if stdin was empty;
- worked with multi-source boards (LinkedIn, RemoteOK, WeWorkRemotely, etc.).

After user request it was rewritten to behave like the other HeadHunter trackers:

- directly queries `https://api.hh.ru/vacancies`;
- fetches full vacancy descriptions via `GET /vacancies/{id}` before scoring `priority`/`match`;
- uses the same `HH_APP_TOKEN` / `HH_USER_AGENT` pattern as `hh_ai_vacancies.py` and `sales_event_vacancies.py`;
- keeps the original 11-column Google Sheets layout (`date`, `title`, `company`, `salary`, `location`, `level`, `source`, `url`, `hash`, `priority`, `match`) on tab `AI`;
- preserves Telegram HTML report format (status, sheet link, TOP-3, source grouping).

## Shared token state

All three HH vacancy crons now depend on the single env variable `HH_APP_TOKEN` in `~/.hermes/.env`:

- `hh_ai_vacancies.py`
- `sales_event_vacancies.py`
- `ai_pm_vacancies.py`

If the token is revoked, **all three** jobs fail with the same message. Updating the token once fixes all three.

## API call pattern used

```python
def search_vacancies(text, per_page=50, page=0):
    params = {
        "text": text,
        "search_field": "name",
        "per_page": per_page,
        "page": page,
        "order_by": "publication_time",
    }
    url = "https://api.hh.ru/vacancies?" + urllib.parse.urlencode(params)
    return hh_api(url)

def get_vacancy_details(vacancy_id):
    url = f"https://api.hh.ru/vacancies/{vacancy_id}"
    return hh_api(url)
```

`hh_api()` adds `User-Agent` and, when present, `Authorization: Bearer <HH_APP_TOKEN>`. It sets a global `HH_TOKEN_REVOKED` flag on 403 `token-revoked` / `unrecognized authorization` and raises a clear message.

## Filter logic

1. Drop archived/closed/expired/suspended titles.
2. Drop junk titles (developer, analyst, engineer, designer, sales manager, etc.).
3. Drop resumes.
4. Require one of:
   - target keyword from `KEYWORDS` list, or
   - explicit AI/ML term (`ai`, `ии`, `llm`, `agent`, `genai`, etc.), or
   - explicit PM term (`product manager`, `product owner`, etc.).
5. Fetch full description for candidates that pass title filter.
6. Re-score `priority`/`match` using description.
7. Dedup by URL against `~/.hermes/vacancies/seen.json` (30-day expiry).
8. Append new rows to Google Sheets tab `AI`.

## Why this is safe to do for a cron

- Deterministic, no LLM inference inside the script.
- Stdlib only (`urllib`, `json`, `re`, `hashlib`, `concurrent.futures`).
- State stored in `seen.json`; re-runs are idempotent.
- Token-revocation handled gracefully with a user-facing message.

## Verification command

```bash
python3 /home/hermes/.hermes/scripts/ai_pm_vacancies.py 2>&1 | tail -40
```

With a valid token it prints counts per keyword, number of new vacancies, and the Telegram HTML report. With a revoked token it prints the revocation message and exits cleanly.
