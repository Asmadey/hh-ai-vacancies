# HeadHunter (hh.ru) native API notes

Session: 2026-06-28 — set up `HH.ru AI Vacancies Daily` cron job.
Updated 2026-06-29 — documented `token_revoked` failure and recovery options.

## Endpoint for full vacancy details

Always fetch full details before generating a cover letter or writing a detailed report:

```
GET https://api.hh.ru/vacancies/{id}
```

Important fields to extract:

| Field | Path | Notes |
|---|---|---|
| title | `name` | exact vacancy title |
| description | `description` | full HTML description; strip tags for LLM |
| key skills | `key_skills[].name` | list of required skills |
| experience | `experience.name` | required experience level |
| schedule | `schedule.name` | remote / office / hybrid |
| employment | `employment.name` | full-time / part-time / project |
| salary | `salary.from`, `salary.to`, `salary.currency`, `salary.gross` | |
| employer | `employer.name` | company name |
| area | `area.name` | city |
| alternate_url | `alternate_url` | human vacancy page |
| apply_alternate_url | `apply_alternate_url` | direct response URL for HYPERLINK button |

Do NOT rely on the `snippet` returned by `/vacancies` search — it is truncated to ~200–300 characters.

## Endpoint for search

```
GET https://api.hh.ru/vacancies
```

Common parameters:

| Parameter | Example | Notes |
|---|---|---|
| `text` | `AI Product Manager` | Required. Search query. |
| `search_field` | `name` | Search only in vacancy title. Use `name` for precise keyword matching. |
| `per_page` | `50` | Max 100, but 50 is a safe default. |
| `page` | `0` | Pagination. |
| `order_by` | `publication_time` | Sort by newest first. |

Other useful filters: `area` (city/region id), `experience` (`noExperience`, `between1And3`, etc.), `schedule` (`remote`).

## Required headers

```
User-Agent: MyApp/1.0 (my-app-feedback@example.com)
```

The docs allow `HH-User-Agent` as a fallback. If neither is sent, HH returns **400 Bad Request**. We use:

```
User-Agent: Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)
```

## Authentication

For **public vacancy search** OAuth is **not required**. Pass an application token in `Authorization: Bearer *** to get higher rate limits.

OAuth is only needed for personalized endpoints: saved searches, negotiations, applicant-specific methods.

## Application token

Stored in the cron script as a fallback default:

```python
HH_APP_TOKEN=*** "APPL...")
```

If the token is revoked, requests will return 403. The script degrades gracefully if the env var is empty (still works, but with lower limits).

## Response shape

```json
{
  "found": 32,
  "pages": 2,
  "page": 0,
  "per_page": 20,
  "items": [
    {
      "id": "133610060",
      "name": "AI Product Manager",
      "alternate_url": "https://hh.ru/vacancy/133610060",
      "url": "https://api.hh.ru/vacancies/133610060?host=hh.ru",
      "published_at": "2026-06-27T15:45:04+0300",
      "employer": {"name": "Моё дело"},
      "area": {"name": "Москва"},
      "salary": {"from": 300000, "to": null, "currency": "RUR", "gross": false},
      "snippet": {"requirement": "...", "responsibility": "..."}
    }
  ]
}
```

## Rate-limit hints

- With `User-Agent` + app token we fetched 8 queries × 20–50 results without hitting limits in a single run.
- HH returns `429 Too Many Requests` when the limit is exceeded. The script currently retries at next cron tick; add exponential backoff only if this becomes frequent.

## Token revocation (`token_revoked`)

Real failure 2026-06-29: a previously working `HH_APP_TOKEN` began returning:

```
HTTP 403
{
  "description": "Unrecognized authorization",
  "oauth_error": "token-revoked",
  "errors": [{"value": "token_revoked", "type": "oauth"}]
}
```

This error means the token was revoked by HH and cannot be used anymore. The search endpoint also returns 403 without a valid token.

### Recovery options

1. **Generate a new app token** at https://dev.hh.ru/admin under the registered application. This is the fastest fix.
2. **Use OAuth** if a stable long-lived credential is required. Requires a one-time authorization-code flow and storing a `refresh_token`.
3. **Fallback to web scraping** (Firecrawl) if API tokens are unavailable. Slower and consumes credits, but independent of HH API auth.

### Do not

- Keep retrying the same revoked token.
- Try to call `/vacancies` without any `Authorization` header — it also returns 403 in practice.
- Assume the `User-Agent` alone is sufficient once a token has been configured.

## OAuth credentials supplied by user (for reference)

- `user_type`: applicant
- `user_id`: 30656564
- `email`: sagestaf@gmail.com
- `Client Id` / `Client Secret` / `Redirect Uri`: reserved for future OAuth flows if personalized methods are needed.

## Links

- Docs: https://api.hh.ru/openapi/redoc
- Working script: `~/.hermes/scripts/hh_ai_vacancies.py`
