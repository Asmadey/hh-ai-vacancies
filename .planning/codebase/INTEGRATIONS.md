# External Integrations

**Analysis Date:** 2026-07-22

## APIs & External Services

**HeadHunter (hh.ru) — `https://api.hh.ru`:**
- Public vacancy search — `GET /vacancies?text=...&search_field=name&per_page=50&page=0&order_by=publication_time`. Used in `hh-ai-vacancies/src/fetch.py:fetch_all()` across the 13 keywords in `hh-ai-vacancies/src/config.py:KEYWORDS`.
- Vacancy detail enrichment — `GET /vacancies/{id}`. Used in `hh-ai-vacancies/src/enrich.py:enrich_record()` (company, description text, work_format, employment, experience, key_skills, apply_url).
- Apply — `POST /negotiations` with `vacancy_id`, `resume_id`, `message` (cover letter). Used in `hh-ai-vacancies/src/apply.py:_post_negotiation()`. Success = HTTP 201.
- OAuth token refresh — `POST /token` with `grant_type=refresh_token`. Used in `hh-ai-vacancies/src/auth.py:refresh()`. Returns new single-use `refresh_token` + `access_token`; saved atomically via `hh-ai-vacancies/src/auth.py:save_tokens()` (temp + `os.replace`).
- One-time user OAuth setup (authorization_code flow) documented in `hh-ai-vacancies/docs/DEPLOY.md` Step 0 against `https://hh.ru/oauth/authorize` + `POST https://api.hh.ru/oauth/token`.
- SDK/Client: stdlib `urllib` only, routed through `hh-ai-vacancies/src/http_client.py:request()`. Every HH call is wrapped by `hh-ai-vacancies/src/auth.py:api_request()` which injects `Authorization: Bearer {access_token}` and `User-Agent: Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)`.
- Auth: user OAuth token pair stored in `data/hh_tokens.json` (path from `hh-ai-vacancies/src/config.py:tokens_path()`). App token (`HH_APP_TOKEN` env) is used only by the legacy monolith `hh-ai-vacancies/scripts/hh_ai_vacancies.py` for public search; `/negotiations` rejects app tokens with `403 oauth/user_auth_expected`.
- Error contract (verified against `github.com/hhru/api`, 2026-07-18): `hh-ai-vacancies/docs/api-contract.md` §1 maps every `/negotiations` error `type`/`value` to a pipeline status and action (`test_required`, `limit_exceeded`, `already_applied`, `invalid_vacancy`, `archived`, `resume_not_found`, `application_denied`, `captcha_required`, 429, 5xx). `limit_exceeded`, `resume_not_found`, `captcha_required`, 5xx/network raise `BatchStop` (`hh-ai-vacancies/src/apply.py:BatchStop`).
- Auto-refresh policy: any `403 {"errors":[{"type":"oauth",...}]}` triggers one `refresh()` + one retry; second consecutive 403 → fatal `AuthError` + Telegram alert (`hh-ai-vacancies/src/auth.py:api_request()`).

**Ollama Cloud — `https://ollama.com/v1` (OpenAI-compatible):**
- `POST /chat/completions` for cover-letter generation. Used in `hh-ai-vacancies/src/cover.py:call_ollama()`.
- Also used as an independent LLM rubric scorer in `hh-ai-vacancies/evals/rate_cover_letters.py:rate()` (threshold ≥7/10).
- SDK/Client: stdlib `urllib` via `hh-ai-vacancies/src/http_client.py:request()`, `Authorization: Bearer {OLLAMA_API_KEY}`.
- Auth: `OLLAMA_API_KEY` env var. When absent, `call_ollama` returns `""` and `hh-ai-vacancies/src/cover.py:fallback_letter()` produces a deterministic template.
- Model: `OLLAMA_MODEL` (default `deepseek-v4-flash`). When model name contains `deepseek`, payload sets `reasoning_effort: "none"`.
- Generation params: `temperature=COVER_LETTER_TEMP` (0.4), `max_tokens=COVER_LETTER_MAX_TOKENS` (900). Parallelized via `ThreadPoolExecutor(max_workers=COVER_LETTER_WORKERS)` (default 10) in `hh-ai-vacancies/src/cover.py:generate_all()`.
- Timeout: 90s per call (vs. 25s default in `http_client.request`).

**Google Sheets API v4 — `https://sheets.googleapis.com/v4/spreadsheets/{id}`:**
- Full rewrite of the `HH_AI` tab every run (clear `A:K` then batch-write 200 rows at a time). Used in `hh-ai-vacancies/src/sheets_export.py:export()`.
- Batch write: `PUT /values/{range}?valueInputOption=USER_ENTERED` with `majorDimension=ROWS`, batches of 200 rows.
- Clear: `POST /values/{encoded_range}:clear`.
- SDK/Client: stdlib `urllib` via `hh-ai-vacancies/src/http_client.py:request()`.
- Visualization-only contract: no module reads cell data back; source of truth is `data/vacancies.json` (`hh-ai-vacancies/src/store.py`). Documented in `hh-ai-vacancies/src/sheets_export.py` module docstring.
- 11-column layout (`hh-ai-vacancies/src/sheets_export.py:COLUMNS`): `date | title | company | salary | location | level | url | match | cover-letter | respond | статус`. `respond` column is a `=HYPERLINK(...)` formula pointing at `apply_url`.

**Google OAuth2 — `https://oauth2.googleapis.com/token`:**
- Refresh-token flow to mint a Sheets access token each export. Used in `hh-ai-vacancies/src/sheets_export.py:get_access_token()`.
- Auth: `~/.config/gws/credentials.json` (`hh-ai-vacancies/src/config.py:GOOGLE_CREDS_PATH`) holds `client_id`, `client_secret`, `refresh_token`. If file missing → `get_access_token()` returns `None` and dry-run skips, live run raises `RuntimeError("no google credentials")`.

**Telegram Bot API — `https://api.telegram.org/bot{TOKEN}/sendMessage`:**
- Reports and alerts. Used in `hh-ai-vacancies/src/telegram.py:_send()`.
- Always `parse_mode=HTML`, `disable_web_page_preview=true`. Dynamic content escaped via `hh-ai-vacancies/src/telegram.py:esc()` (`html.escape(..., quote=False)`). Markdown is forbidden — see `hh-ai-vacancies/references/telegram-html-vs-markdownv2.md`.
- Auth: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env vars. If either missing, `_send` returns `False` and the report is only printed to stdout (Hermes `deliver: origin` mirrors stdout to Telegram).
- Two entry points: `send_report(metrics)` (formatted run summary with sheet link) and `send_alert(text)` (error/fatal notifications from `auth.py` and `apply.py`).

## Data Storage

**Databases:**
- None. All state is file-based JSON.

**File Storage:**
- Local filesystem only on the Hermes host.
  - `data/vacancies.json` — single source of truth, dict keyed by `vacancy_id`. Managed by `hh-ai-vacancies/src/store.py` (`load`, `save` with `.bak` backup + atomic temp-rename, `merge`, `duplicates`, `migrate_seen`). Path via `hh-ai-vacancies/src/config.py:vacancies_path()`; overridable with `HH_PIPELINE_HOME`.
  - `data/hh_tokens.json` — HH user OAuth pair. Atomic save in `hh-ai-vacancies/src/auth.py:save_tokens()`.
  - `data/last_run_report.json` — run metrics for `hh-ai-vacancies/evals/check_metrics.py`. Written by `hh-ai-vacancies/src/pipeline.py:write_report()`.
  - Legacy `~/.hermes/hh_ai_seen.json` — old URL→timestamp dedup state; migrated once via `hh-ai-vacancies/scripts/migrate_seen.py` / `hh-ai-vacancies/src/store.py:migrate_seen()` (path constant `hh-ai-vacancies/src/config.py:LEGACY_SEEN_PATH`).
- Google Sheets (described above) is write-only visualization, not a data store for the pipeline.

**Caching:**
- None explicit. The store file acts as a persistent dedup cache (existing records are preserved/refreshed; `status`, `cover_letter`, `first_seen` are never overwritten on re-fetch — see `hh-ai-vacancies/src/store.py:merge()`).

## Authentication & Identity

**Auth Provider:**
- HeadHunter user OAuth 2.0 (authorization_code → refresh_token rotation). Implementation: `hh-ai-vacancies/src/auth.py`. One-time setup in `hh-ai-vacancies/docs/DEPLOY.md` Step 0. Token rotation is automatic with one retry on `403 oauth`.
- Google OAuth2 (refresh_token grant for Sheets). Implementation: `hh-ai-vacancies/src/sheets_export.py:get_access_token()`.
- Telegram Bot token (static). Implementation: `hh-ai-vacancies/src/telegram.py:_send()`.
- Ollama API key (static bearer). Implementation: `hh-ai-vacancies/src/cover.py:call_ollama()`.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/external tracker). Fatal auth/fetch/resume/captcha failures are pushed to the operator via `hh-ai-vacancies/src/telegram.py:send_alert()`. Pipeline exit codes: `0` success, `2` auth/config fatal, `3` fetch fatal (`hh-ai-vacancies/src/pipeline.py:run()`).

**Logs:**
- stderr `print(..., file=sys.stderr)` with stage-prefixed lines (`[pipeline]`, `[fetch]`, `[enrich]`, `[cover]`, `[apply]`).
- Telegram report (`send_report`) is the structured per-run summary (5 aggregates: found / new / covers / sent / tests + sheet link).
- Hermes cron `deliver: origin` mirrors stdout to Telegram, complementing the direct Bot API send.

## CI/CD & Deployment

**Hosting:**
- Hermes Agent cron host (Linux). Not a cloud platform; runs on the operator's server.

**CI Pipeline:**
- None. No GitHub Actions / CI config detected.
- Deployment is manual via Hermes `cronjob` commands (`pause` / `remove` / `create`) per `hh-ai-vacancies/docs/DEPLOY.md` Step 4 and `hh-ai-vacancies/config/cron.yaml`.
- Quality gate: `python3 evals/check_metrics.py` (exit 0 = goal reached) and `python3 -m evals.rate_cover_letters --sample 5` (LLM rubric ≥7/10) run after each pipeline invocation.

## Environment Configuration

**Required env vars (in `~/.hermes/.env`, loaded by `hh-ai-vacancies/src/config.py:load_env_file()`):**
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — alerts + reports.
- `OLLAMA_API_KEY` — cover-letter LLM (absent → deterministic fallback).
- `HH_RESUME_ID` — required for live applies.
- Optional runtime knobs: `DRY_RUN` (default `1`), `APPLY_LIMIT` (default `0`), `APPLY_PAUSE_SEC` (default `5`), `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `COVER_LETTER_MAX_TOKENS`, `COVER_LETTER_TEMP`, `COVER_LETTER_WORKERS`.
- Legacy monolith only: `HH_APP_TOKEN`.
- Token updater only: `HH_ADMIN_EMAIL`, `HH_ADMIN_PASSWORD`.

**Secrets location:**
- `~/.hermes/.env` — primary secrets store (Hermes-protected; edit via Python `re.sub`, not `sed`/`patch`/`write_file`).
- `data/hh_tokens.json` — HH OAuth pair (in-repo data dir, gitignored in practice via `data/` not being committed; atomic writes).
- `~/.config/gws/credentials.json` — Google Sheets OAuth client_id/client_secret/refresh_token.
- `/tmp/hh_otp.txt` — transient OTP written by the operator during `hh-ai-vacancies/scripts/hh_token_updater.py` runs.

## Webhooks & Callbacks

**Incoming:**
- None. The pipeline is purely outbound (cron-triggered).

**Outgoing:**
- HH `/vacancies` (search), `/vacancies/{id}` (enrich), `/negotiations` (apply), `/token` (refresh) — `hh-ai-vacancies/src/fetch.py`, `hh-ai-vacancies/src/enrich.py`, `hh-ai-vacancies/src/apply.py`, `hh-ai-vacancies/src/auth.py`.
- Ollama `/chat/completions` — `hh-ai-vacancies/src/cover.py:call_ollama()`, `hh-ai-vacancies/evals/rate_cover_letters.py`.
- Google `https://oauth2.googleapis.com/token` — `hh-ai-vacancies/src/sheets_export.py:get_access_token()`.
- Google Sheets `https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/...` — `hh-ai-vacancies/src/sheets_export.py:export()`.
- Telegram `https://api.telegram.org/bot{TOKEN}/sendMessage` — `hh-ai-vacancies/src/telegram.py:_send()`.

---

*Integration audit: 2026-07-22*