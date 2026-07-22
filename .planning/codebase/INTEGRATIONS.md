# External Integrations

**Analysis Date:** 2026-07-22

## APIs & External Services

**HeadHunter (hh.ru) — primary data source + apply channel:**
- `GET https://api.hh.ru/vacancies` — search across 13 keywords (`config.KEYWORDS`), `per_page=50`, `search_field=name`, `order_by=publication_time`. Called from `src/fetch.py:fetch_all`.
- `GET https://api.hh.ru/vacancies/{id}` — full vacancy detail (company, description, work_format, employment, experience, key_skills, salary, apply_url). Called from `src/enrich.py:enrich_record`.
- `POST https://api.hh.ru/negotiations` — apply to a vacancy with `vacancy_id` + `resume_id` + `message` (cover letter). Returns 201 on success; error types map to record statuses. Called from `src/apply.py:_post_negotiation` / `apply_one`.
- `POST https://api.hh.ru/token` — OAuth refresh_token grant. Single-use refresh_token; new access+refresh pair saved atomically. Called from `src/auth.py:refresh`.
- SDK/Client: none — raw `urllib.request` via `src/http_client.py:request()` and `src/auth.py:api_request()`.
- Auth: user OAuth Bearer token from `data/hh_tokens.json` (new pipeline). The OLD monolith `scripts/hh_ai_vacancies.py` uses `HH_APP_TOKEN` (app token `APPL...`) instead — `/negotiations` rejects app tokens with `403 oauth/user_auth_expected`.
- Mandatory headers: `User-Agent: Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)` (`config.HH_USER_AGENT`), `Accept: application/json`. Token refresh posts `application/x-www-form-urlencoded`; negotiations posts `application/x-www-form-urlencoded` (code uses urlencoded, NOT multipart as the api-contract doc states).
- Rate limiting: 429 → backoff (`Retry-After` header or 5→10→20s exponential, max 3 retries → `status_reason=rate_limited`). Product limit ~200 applies/day surfaces as `limit_exceeded` → `BatchStop`.
- Auth refresh flow: any `403 {"errors":[{"type":"oauth",...}]}` → one refresh + one retry; second consecutive 403 → fatal + Telegram alert (`src/auth.py:api_request`).
- Contract docs: `docs/api-contract.md` (verified 2026-07-18 against `github.com/hhru/api`).

**Ollama Cloud — LLM cover-letter generation + rubric eval:**
- `POST {OLLAMA_BASE_URL}/chat/completions` (default `https://ollama.com/v1`) — OpenAI-compatible chat completions. Called from `src/cover.py:call_ollama` and `evals/rate_cover_letters.py:rate`.
- Auth: `Authorization: Bearer {OLLAMA_API_KEY}` env var.
- Default model `deepseek-v4-flash` (`OLLAMA_MODEL`); for any `deepseek*` model the client sets `reasoning_effort: "none"`.
- Generation params: `temperature=0.4` (`COVER_LETTER_TEMP`), `max_tokens=900` (`COVER_LETTER_MAX_TOKENS`), timeout 90s. Parallelized via `ThreadPoolExecutor` (`COVER_LETTER_WORKERS`, default 10).
- Fallback: if Ollama call fails or letter fails `letter_ok()` validation (400–1500 chars, no placeholders/HTML), a deterministic template letter is used (`src/cover.py:fallback_letter`).
- Evals: `evals/rate_cover_letters.py` uses the same endpoint as an independent LLM judge (rubric 0–10, threshold ≥7 avg and ≥80% letters ≥7; `temperature=0.0`, `max_tokens=200`).

**Google Sheets API v4 — visualization-only export:**
- `POST https://oauth2.googleapis.com/token` — refresh OAuth access token from `~/.config/gws/credentials.json` (`client_id`, `client_secret`, `refresh_token`, `grant_type=refresh_token`). Called from `src/sheets_export.py:get_access_token`.
- `POST https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}:clear` — clear `HH_AI!A:K` before each rewrite.
- `PUT https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}?valueInputOption=USER_ENTERED` — batch write rows in chunks of 200.
- SDK/Client: none — raw `urllib.request` via `src/http_client.py`.
- Auth: OAuth2 refresh token at `config.GOOGLE_CREDS_PATH` (`~/.config/gws/credentials.json`).
- Spreadsheet ID `1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok`, tab `HH_AI` (GID `1464494667`).
- Columns (`src/sheets_export.py:COLUMNS`): `date | title | company | salary | location | level | url | match | cover-letter | respond | статус`. The `respond` column is a `=HYPERLINK(...)` formula.
- Invariant: Sheets is write-only; no module ever reads cell data back. Full rewrite every run so the sheet always equals `data/vacancies.json`. The OLD monolith (`scripts/hh_ai_vacancies.py`) additionally reads column G / uses `values:batchUpdate` for the legacy "Update Respond" flow.

**Telegram Bot API — reporting + alerts:**
- `POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage` — `chat_id`, `text`, `parse_mode=HTML`, `disable_web_page_preview=true`. Called from `src/telegram.py:_send` (also prints to stdout for Hermes `deliver: origin`).
- Auth: `TELEGRAM_BOT_TOKEN` env var; target `TELEGRAM_CHAT_ID` env var.
- `send_report(metrics)` posts a 5-number summary with a link to the Sheet; `send_alert(text)` posts operational alerts (auth failure, captcha, resume_not_found, Sheets export failure).
- HTML parse mode mandatory (not Markdown) — dynamic content escaped via `html.escape()` (`src/telegram.py:esc`); job titles rendered as `<a href>` links. See `references/telegram-html-vs-markdownv2.md`.

**Hermes Agent cron host (operational platform, not an API):**
- Cronjob definition: `config/cron.yaml` (new pipeline) — schedule `0 9 */2 * *`, `deliver: origin` (stdout → Telegram), `no_agent: true`, `script: python3 -m src.pipeline`, `workdir: ~/.hermes/hh-ai-vacancies`, env `DRY_RUN=0`, `APPLY_LIMIT=0`, `APPLY_PAUSE_SEC=5`.
- Legacy cronjob `99a55e0f5ac4` runs `scripts/hh_ai_vacancies.py` (app-token scraper, reporting only). Cutover documented in `docs/DEPLOY.md` Step 4.
- Operator guidance: `cronjob update` silently no-ops if body matches current state — to change schedule/prompt/script use `cronjob pause` → `cronjob remove` → `cronjob create`.

## Data Storage

**Databases:**
- None. No SQL/NoSQL/Redis.

**File Storage (all local JSON on the cron host):**
- `data/vacancies.json` — single source of truth, dict keyed by `vacancy_id`. Atomic save (temp + `os.replace`) with `.bak` backup of previous version (`src/store.py:save`). Schema validated by `src/store.py:validate_record`.
- `data/hh_tokens.json` — HH user OAuth tokens `{access_token, refresh_token, obtained_at, expires_in}`. Atomic save (`src/auth.py:save_tokens`) because refresh_token is single-use — losing the pair forces re-authorization.
- `data/last_run_report.json` — metrics from the last pipeline run, consumed by `evals/check_metrics.py`.
- `~/.hermes/hh_ai_seen.json` — legacy dedup state (url → iso timestamp, 30-day window). Migrated into `vacancies.json` by `src/store.py:migrate_seen` / `scripts/migrate_seen.py`; records marked `migrated=True` are never applied.
- `~/.hermes/.env` — secrets/config (KEY=VALUE; never read contents, never print).
- `~/.config/gws/credentials.json` — Google OAuth client_id/client_secret/refresh_token.

**Caching:**
- None explicit. `vacancies.json` acts as the persistent dedup cache (existing records preserved & refreshed; status/cover_letter/first_seen never overwritten on merge — `src/store.py:merge`).

## Authentication & Identity

**HH.ru user OAuth (new pipeline):**
- One-time authorization_code flow on hh.ru (see `docs/DEPLOY.md` Step 0) → access + refresh tokens stored in `data/hh_tokens.json`.
- Auto-refresh on `403 oauth` (one refresh + one retry; second 403 fatal + alert). `refresh_token` is single-use; new pair must be saved atomically.
- `HH_RESUME_ID` env var selects the resume sent with each application (`GET /resumes/mine` during setup).

**HH.ru app token (old monolith only):**
- `HH_APP_TOKEN` (`APPL...`) in `~/.hermes/.env`, used by `scripts/hh_ai_vacancies.py` for public `/vacancies` search. Higher rate limits than user tokens but CANNOT call `/negotiations`.
- Renewal is interactive via `scripts/hh_token_updater.py` (Playwright + Chromium): logs into `dev.hh.ru/admin`, handles email/password + OTP (digits typed via `page.keyboard.press(f"Digit{d}")`, OTP read from `/tmp/hh_otp.txt`), reveals the token, writes it back to `~/.hermes/.env` via `re.sub`, and tests it against `GET /vacancies`. Requires `xvfb-run -a` on headless hosts.

**Google Sheets OAuth2:**
- Refresh-token grant against `oauth2.googleapis.com/token` using `~/.config/gws/credentials.json`. No service account; no library.

**Telegram:**
- Bot token + chat ID (no OAuth, no end-user identity).

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Datadog). Errors surface as Telegram alerts (`src/telegram.py:send_alert`) and stderr lines prefixed `[module]`. Exit codes from `src/pipeline.py:run()`: `0` success, `2` auth/config fatal, `3` fetch fatal.

**Logs:**
- `print(..., file=sys.stderr)` with `[pipeline] / [fetch] / [enrich] / [cover] / [apply]` prefixes. Hermes cron captures stdout (`deliver: origin` → Telegram) and stderr. No structured logging, no log files (`.gitignore` excludes `*.log`).

**Metrics / evals:**
- `data/last_run_report.json` written every run; `evals/check_metrics.py` reads it + `vacancies.json` and prints a deterministic goal-check JSON (exit 0 = goal reached). Criteria: 100% valid statuses, 0 duplicates, enrichment ≥95%, covers 100%, `sheets_rows == len(json)`, telegram delivered.
- `evals/rate_cover_letters.py` — independent LLM rubric on cover letters (sample N, threshold avg ≥7 and ≥80% pass).

## CI/CD & Deployment

**Hosting:**
- Hermes Agent cron host (Nous Research). Private project; not a cloud PaaS.

**CI Pipeline:**
- None. No `.github/workflows/`, no GitLab CI, no pre-commit. Tests are run manually: `python3 -m pytest`.

**Deployment:**
- Git push to the Hermes-managed checkout at `~/.hermes/hh-ai-vacancies`; cronjob cutover via Hermes `cronjob` CLI (`docs/DEPLOY.md` Step 4: pause + remove old `99a55e0f5ac4`, `cronjob create` from `config/cron.yaml`).

## Environment Configuration

**Required env vars (loaded from `~/.hermes/.env`):**
- New pipeline live apply: `DRY_RUN=0`, `HH_RESUME_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_API_KEY`.
- Optional: `APPLY_LIMIT`, `APPLY_PAUSE_SEC`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `COVER_LETTER_MAX_TOKENS`, `COVER_LETTER_TEMP`, `COVER_LETTER_WORKERS`, `HH_PIPELINE_HOME`.
- Old monolith / token updater: `HH_APP_TOKEN`, `HH_ADMIN_EMAIL`, `HH_ADMIN_PASSWORD`.
- `data/hh_tokens.json` and `~/.config/gws/credentials.json` are files, not env vars.

**Secrets location:**
- `~/.hermes/.env` — HH app/admin creds, Telegram, Ollama, resume ID.
- `data/hh_tokens.json` — HH user OAuth pair (single-use refresh_token; atomic write required).
- `~/.config/gws/credentials.json` — Google OAuth client + refresh token.
- Rule: never print secrets in reports/logs/diffs — replace with `[REDACTED]`. Hermes blocks direct edits to `.env` with `sed`/`patch`/`write_file`; update keys with Python `re.sub` (snippet in `SKILL.md`).

## Webhooks & Callbacks

**Incoming:**
- None. No HTTP server, no webhook receivers.

**Outgoing:**
- HH.ru `/negotiations` POST (apply), HH.ru `/token` POST (refresh), Google Sheets API (clear + batch PUT), Telegram `sendMessage` POST, Ollama `/chat/completions` POST. All initiated by the cron-run pipeline; none are event-driven callbacks.

---

*Integration audit: 2026-07-22*