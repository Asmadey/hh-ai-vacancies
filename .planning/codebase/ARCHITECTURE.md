<!-- refreshed: 2026-07-22 -->
# Architecture

**Analysis Date:** 2026-07-22

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         Trigger / Entry Layer                         │
│   Hermes cron (config/cron.yaml)  →  `python3 -m src.pipeline`       │
│   Legacy: scripts/hh_ai_vacancies.py (monolith, cron 99a55e0f5ac4)    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Orchestrator                                       │
│   `hh-ai-vacancies/src/pipeline.py:run()`  (8-stage linear flow)      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
   ┌──────────┬──────────┬──────┴───────┬───────────┬───────────┬──────┐
   ▼          ▼          ▼              ▼           ▼           ▼       ▼
┌──────┐  ┌──────┐   ┌──────┐       ┌──────┐    ┌──────┐   ┌─────────┐ ┌──────┐
│auth  │  │fetch │   │store │       │enrich│    │cover │   │apply    │ │telegram│
│`auth │  │`fetch│   │`store│       │`enrich│   │`cover│   │`apply   │ │`telegram│
│.py`  │  │.py`  │   │.py`  │       │.py`  │    │.py`  │   │.py`     │ │.py`    │
└──┬───┘  └──┬───┘  └──┬───┘      └──┬───┘  └──┬───┘   └────┬────┘ └────────┘
   │         │         │             │         │            │
   └─────────┴─────────┴─────────────┴─────────┴────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ Single HTTP entrypoint  │
                  │ `hh-ai-vacancies/src/  │
                  │     http_client.py`    │
                  └────────────┬──────────┘
                               │
   ┌───────────────────────────┼──────────────────────────────┐
   ▼                           ▼                              ▼
┌──────────┐          ┌─────────────────┐            ┌────────────────┐
│HH.ru API │          │ Ollama Cloud     │            │ Google Sheets  │
│api.hh.ru │          │ ollama.com/v1    │            │ (visualization │
│/vacancies│          │ /chat/completions│            │  only — write) │
│/negotiations        │                 │            │                │
│/token     │          └─────────────────┘            └────────────────┘
└──────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ Source of truth          │
                  │ `data/vacancies.json`    │
                  │ + `data/hh_tokens.json`   │
                  │ + `data/last_run_report. │
                  │        json`             │
                  └─────────────────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ Telegram Bot API        │
                  │ api.telegram.org/bot... │
                  │ (alerts + report, HTML) │
                  └─────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Orchestrator | 8-stage linear pipeline; writes `last_run_report.json`; exit codes 0/2/3 | `hh-ai-vacancies/src/pipeline.py` |
| Config / env | Loads `~/.hermes/.env`, path helpers, keywords, regex filters, statuses | `hh-ai-vacancies/src/config.py` |
| HTTP client | Single `request()` entrypoint over `urllib`; `HttpResponse` + `NetworkError`; every module routes HTTP here | `hh-ai-vacancies/src/http_client.py` |
| Auth | User OAuth token load/save (atomic), refresh-on-403-once, `AuthError` + Telegram alert | `hh-ai-vacancies/src/auth.py` |
| Fetch | `GET /vacancies` over 13 keywords; junk/archive/resume/relevance filters; `parse_level`, `match_reason` | `hh-ai-vacancies/src/fetch.py` |
| Store | `data/vacancies.json` source of truth, schema/validate, atomic save with `.bak`, merge/duplicates, legacy migration | `hh-ai-vacancies/src/store.py` |
| Enrich | `GET /vacancies/{id}` full details; strips HTML, truncates description to 4000 chars, detects archive-flip | `hh-ai-vacancies/src/enrich.py` |
| Cover | Ollama Cloud cover letters (parallel `ThreadPoolExecutor`), deterministic fallback template, `letter_ok` validation | `hh-ai-vacancies/src/cover.py` |
| Apply | `POST /negotiations`; status machine (отправлено/не отправлено/тест); `BatchStop` on fatal errors; 429 backoff | `hh-ai-vacancies/src/apply.py` |
| Sheets export | Full-rewrite of `HH_AI` tab each run; clear + batched PUT (200 rows); visualization only — never reads back | `hh-ai-vacancies/src/sheets_export.py` |
| Telegram | `send_report` + `send_alert`; `parse_mode=HTML`; `esc()` helper; also prints to stdout (Hermes deliver: origin) | `hh-ai-vacancies/src/telegram.py` |
| Goal check | Deterministic post-run verifier (exit 0 = goal reached); reads JSON + report | `hh-ai-vacancies/evals/check_metrics.py` |
| Cover letter rubric | Independent Ollama call, LLM rubric (threshold ≥7/10) | `hh-ai-vacancies/evals/rate_cover_letters.py` |
| Legacy monolith | Original 900-line standalone scraper (search → Sheets → Telegram only); reference impl, cron `99a55e0f5ac4` | `hh-ai-vacancies/scripts/hh_ai_vacancies.py` |
| Token updater | Playwright-based HH app-token renewal (OTP technique) | `hh-ai-vacancies/scripts/hh_token_updater.py` |
| Seen migration | One-shot legacy `seen.json` → `vacancies.json` | `hh-ai-vacancies/scripts/migrate_seen.py` |

## Pattern Overview

**Overall:** Linear staged pipeline with a single orchestrator and a single HTTP entrypoint.

**Key Characteristics:**
- **Linear 8-stage flow** in `pipeline.py:run()` — auth → fetch → merge/dedup → enrich → cover → apply → store.save → sheets → telegram. No branching DAG, no queue.
- **Single HTTP entrypoint** — every module calls `http_client.request(...)`. This is the only network seam, which is why tests can mock all I/O by monkeypatching one symbol (`tests/conftest.py:MockHttp`).
- **JSON file as source of truth** — `data/vacancies.json` keyed by `vacancy_id`. Google Sheets is visualization-only and rewritten in full each run.
- **Atomic persistence** — `store.save()` writes `.tmp` then `os.replace`, with `.bak` backup of the previous version; same pattern for token refresh in `auth.save_tokens()` (refresh_token is single-use — losing the pair means re-running OAuth).
- **stdlib-only** — `urllib`, `json`, `re`, `concurrent.futures`. No `requests`, no third-party runtime deps.
- **DRY_RUN safe default** — `config.dry_run()` returns `True` unless `DRY_RUN=0`; apply step writes no POSTs in dry mode.
- **Two coexisting code paths** — the new modular `src/` pipeline (apply-enabled) and the legacy monolith `scripts/hh_ai_vacancies.py` (search/reporting only). CLAUDE.md is explicit about which path to edit.

## Layers

**Entry / Trigger:**
- Purpose: invoke the pipeline on a schedule
- Location: `hh-ai-vacancies/config/cron.yaml` (Hermes cron, `0 9 */2 * *`, `no_agent: true`, `deliver: origin`); script `python3 -m src.pipeline`
- Contains: schedule, env vars, workdir
- Depends on: Hermes Agent host
- Used by: operators

**Orchestrator:**
- Purpose: sequence the 8 stages and aggregate metrics
- Location: `hh-ai-vacancies/src/pipeline.py`
- Contains: `run()`, `write_report()`
- Depends on: every other `src/` module
- Used by: cron entry, tests (`tests/test_pipeline_e2e.py`)

**Domain stages (stateless functions operating on the store dict):**
- Purpose: each stage reads/mutates the in-memory `vac` dict and returns tokens/metrics
- Location: `hh-ai-vacancies/src/{auth,fetch,enrich,cover,apply,sheets_export,telegram,store}.py`
- Contains: pure functions + `auth.api_request` wrapper
- Depends on: `config`, `http_client`, `store`
- Used by: `pipeline.run()`

**Infrastructure / I/O:**
- Purpose: single HTTP seam; path/env config; schema/validate
- Location: `hh-ai-vacancies/src/http_client.py`, `hh-ai-vacancies/src/config.py`, `hh-ai-vacancies/src/store.py`
- Contains: `request()`, `HttpResponse`, `NetworkError`; env loader; SCHEMA, `validate_record`
- Depends on: `urllib`
- Used by: all domain stages

**External services (out of repo):**
- HH.ru API (`api.hh.ru`), Ollama Cloud (`ollama.com/v1`), Google Sheets API, Telegram Bot API
- Local files under `data/` (source of truth), `~/.hermes/.env` (secrets), `~/.config/gws/credentials.json` (Google OAuth)

## Data Flow

### Primary Request Path (pipeline run)

1. Cron triggers `python3 -m src.pipeline` (`hh-ai-vacancies/config/cron.yaml`)
2. `pipeline.run()` loads env + paths (`hh-ai-vacancies/src/config.py:21`) and starts; prints `[pipeline] start (DRY_RUN=...)`
3. `auth.load_tokens()` reads `data/hh_tokens.json` (`hh-ai-vacancies/src/auth.py:17`); on missing → `AuthError` + Telegram alert, exit 2
4. `store.load()` reads `data/vacancies.json`; if empty and `LEGACY_SEEN_PATH` exists → `store.migrate_seen()` (`hh-ai-vacancies/src/store.py:131`)
5. `fetch.fetch_all(tokens)` (`hh-ai-vacancies/src/fetch.py:87`) loops 13 keywords → `auth.api_request("GET", .../vacancies?...)` → `item_to_record` → filter (`is_active`, `is_relevant`) → dedup within run via `seen_ids`; returns `(records, found_total, tokens)`
6. `store.merge(vac, fetched)` (`hh-ai-vacancies/src/store.py:107`) — existing records refreshed (title/salary/etc), status/cover_letter/first_seen never touched; returns `new_ids`
7. `enrich.enrich_new(vac, new_ids, tokens)` (`hh-ai-vacancies/src/enrich.py:62`) — `GET /vacancies/{id}` per new id; mutates records; detects archive-flip
8. `cover.generate_all(vac, new_ids)` (`hh-ai-vacancies/src/cover.py:146`) — parallel `ThreadPoolExecutor` over `generate_for_record`; Ollama call + `clean_letter` + `letter_ok` validation + `fallback_letter`
9. `apply_mod.select_candidates(vac, new_ids)` (`hh-ai-vacancies/src/apply.py:146`) — new + retryable prior misses, only those with cover letters
10. `apply_mod.apply_batch(vac, candidates, resume, tokens)` (`hh-ai-vacancies/src/apply.py:104`) — `POST /negotiations` per candidate; `BatchStop` halts batch and defers rest; 429 backoff (`Retry-After` or 5→10→20s, max 3)
11. `store.save(vac)` (`hh-ai-vacancies/src/store.py:95`) — atomic write **before** sheets/telegram so source of truth persists even if downstream fails
12. `sheets_export.export(vac)` (`hh-ai-vacancies/src/sheets_export.py:56`) — clear `HH_AI!A:K` + batched PUT (200 rows); failures alert but don't fail the run
13. `telegram.send_report(metrics)` (`hh-ai-vacancies/src/telegram.py:54`) — HTML report; also printed to stdout for Hermes `deliver: origin`
14. `write_report(metrics)` → `data/last_run_report.json` for `evals/check_metrics.py`

### Auth refresh flow

1. Any `auth.api_request(...)` gets `403 {"errors":[{"type":"oauth"}]}` (`hh-ai-vacancies/src/auth.py:68`)
2. `auth.refresh(tokens)` → `POST /token grant_type=refresh_token` (`hh-ai-vacancies/src/auth.py:35`); on 200, atomic save of new token pair; on `invalid_grant / not expired` keep old tokens
3. One retry of the original request with new tokens (`_retried=True`)
4. Second 403 → fatal `AuthError` + Telegram alert; pipeline returns exit code 2

### Apply status flow

- `201` → `отправлено` (or `already_applied` → `отправлено` reason=already_applied)
- `test_required` → `тест`
- `limit_exceeded` / `resume_not_found` / `captcha_required` / 5xx / `NetworkError` → `BatchStop`, rest deferred with `reason=deferred_<cause>`
- `429` → backoff loop, then `не отправлено` reason=rate_limited
- `invalid_vacancy` / `archived` → `не отправлено`, not retried

**State Management:**
- In-memory `vac` dict (vacancy_id → record) threaded through every stage; mutated in place
- Persisted only via `store.save()` (atomic, with `.bak`)
- Tokens threaded explicitly as `(resp, tokens)` returns so refreshes propagate
- No global mutable state except module-level compiled regexes in `config.py` (`JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`)

## Key Abstractions

**Vacancy record:**
- Purpose: unit of data flowing through the pipeline
- Schema: `hh-ai-vacancies/src/store.py:SCHEMA` (22 fields, typed, required flags)
- Constructor: `store.new_record(vacancy_id, url, title, **kw)`
- Validator: `store.validate_record(rec)` — returns list of problems
- Status enum: `config.VALID_STATUSES = {отправлено, не отправлено, тест}`

**HttpResponse:**
- Purpose: uniform response object across the single HTTP seam
- Location: `hh-ai-vacancies/src/http_client.py:7`
- Pattern: `request()` returns `HttpResponse` for ANY HTTP status (no raise on 4xx/5xx); only network failures raise `NetworkError`

**AuthError:**
- Purpose: fatal auth signal bubbled to orchestrator
- Location: `hh-ai-vacancies/src/auth.py:13`
- Pattern: raised after refresh fails; pipeline catches and alerts via Telegram

**BatchStop:**
- Purpose: halt the apply batch on fatal per-vacancy errors while leaving the rest deferrable
- Location: `hh-ai-vacancies/src/apply.py:14`
- Pattern: carries `reason`; `apply_batch` catches, marks remaining as `deferred_<reason>`, breaks

## Entry Points

**`python3 -m src.pipeline`:**
- Location: `hh-ai-vacancies/src/pipeline.py` (`if __name__ == "__main__": sys.exit(run())`)
- Triggers: Hermes cron (`hh-ai-vacancies/config/cron.yaml`); manual `DRY_RUN=1 python3 -m src.pipeline`
- Responsibilities: run all 8 stages, write report, exit with 0/2/3

**`python3 evals/check_metrics.py`:**
- Location: `hh-ai-vacancies/evals/check_metrics.py`
- Triggers: post-run verification
- Responsibilities: deterministic goal check (schema, dups, enrichment ≥95%, covers 100%, sheets_rows == JSON, telegram_delivered)

**`python3 -m scripts.migrate_seen`:**
- Location: `hh-ai-vacancies/scripts/migrate_seen.py`
- One-shot legacy `~/.hermes/hh_ai_seen.json` → `data/vacancies.json`

**`python3 -u scripts/hh_token_updater.py`:**
- Location: `hh-ai-vacancies/scripts/hh_token_updater.py`
- Playwright-based renewal of the legacy HH **app** token (not used by the new pipeline, which uses user OAuth)

**Legacy monolith:**
- Location: `hh-ai-vacancies/scripts/hh_ai_vacancies.py`
- Trigger: legacy Hermes cron `99a55e0f5ac4` (to be paused/removed at `docs/DEPLOY.md` Step 4)
- Scope: search → Sheets → Telegram only (no apply, no cover letters, no user OAuth)

## Architectural Constraints

- **stdlib only** — do NOT add `requests` or other third-party runtime deps. Tests need `pytest` but it is not in a `requirements.txt` (none exists).
- **Single HTTP seam** — any new module making HTTP calls MUST route through `http_client.request` or it bypasses the `MockHttp` test harness.
- **Single source of truth** — `data/vacancies.json` keyed by `vacancy_id`. No module reads cell data back from Google Sheets.
- **Atomic persistence** — token pair and vacancies store are written via temp+rename; refresh_token is single-use, losing the pair forces re-running OAuth.
- **Sheets is write-only** — full rewrite each run; column shape changes require clearing the sheet first.
- **Telegram HTML only** — `parse_mode=HTML`; dynamic content must be `html.escape()`d via `telegram.esc()`. MarkdownV2 renders as raw text (see `hh-ai-vacancies/references/telegram-html-vs-markdownv2.md`).
- **`User-Agent` mandatory** — all HH requests use `config.HH_USER_AGENT` or HH returns `400 bad_user_agent`.
- **Threading** — only `cover.generate_all` uses `ThreadPoolExecutor` (`COVER_LETTER_WORKERS`, default 10). All other stages are sequential single-threaded.
- **Global state** — module-level compiled regexes in `config.py` (`JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`) and constants (`KEYWORDS`, `COLUMNS`); env loaded once at import via `load_env_file()`.
- **Circular imports** — none detected. Modules import `config`, `http_client`, `store`, `auth` as needed; `auth` imports `store.now_iso` and `telegram`.
- **Path override** — `HH_PIPELINE_HOME` env var redirects all `data/` paths (used by `tests/conftest.py:home` fixture for isolation).
- **Hermes .env edits** — Hermes blocks `sed`/`patch`/`write_file` on `.env`; use Python `re.sub` to update keys (snippet documented in `SKILL.md`).

## Anti-Patterns

### Bypassing the HTTP seam

**What happens:** A module uses `urllib.request.urlopen` directly (or `requests`) instead of `http_client.request`.
**Why it's wrong:** Tests monkeypatch `http_client.request` via `MockHttp` (`hh-ai-vacancies/tests/conftest.py:54`); direct calls bypass the harness, hit live network, and are untestable.
**Do this instead:** Always call `http_client.request(method, url, headers=..., data=..., timeout=...)` — see `hh-ai-vacancies/src/auth.py:42`, `hh-ai-vacancies/src/cover.py:81`, `hh-ai-vacancies/src/sheets_export.py:23`.

### Reporting archived vacancies as new

**What happens:** Skipping the archive filter before enrichment lets closed/archived vacancies surface in the Telegram report.
**Why it's wrong:** Real incident — `hh-ai-vacancies/references/archive-filter-incident-2026-06-27.md`. Report becomes misleading.
**Do this instead:** Apply `config.ARCHIVE_RE` to `title + snippet` in `fetch.is_active()` **before** enrichment (`hh-ai-vacancies/src/fetch.py:37`), and re-check `data.get("archived")` in `enrich.enrich_record` (`hh-ai-vacancies/src/enrich.py:56`) — the vacancy can flip to archive between fetch and enrich.

### Treating `bad_authorization` as revocation

**What happens:** On `403 oauth / bad_authorization`, an operator immediately runs Playwright token renewal.
**Why it's wrong:** Frequently a typo (e.g., `0`/`O`, `1`/`l`, `I`/`l`); Playwright renewal is disruptive and OTP-gated.
**Do this instead:** Compare the token byte-for-byte with `dev.hh.ru/admin` first; only then escalate (per CLAUDE.md pitfall).

### Telegram MarkdownV2 / unescaped dynamic content

**What happens:** Building Telegram messages with `[text](url)` / `**bold**` or unescaped user content.
**Why it's wrong:** The dispatcher sets `parse_mode=HTML`, so Markdown renders as raw text; unescaped `<>&` breaks the payload.
**Do this instead:** Use `telegram.esc()` (`hh-ai-vacancies/src/telegram.py:8`) on all dynamic content; make titles clickable via `<a href="...">` (see `hh-ai-vacancies/src/sheets_export.py:41` for the HYPERLINK formula analogue).

### Non-atomic token save

**What happens:** Writing `hh_tokens.json` in place.
**Why it's wrong:** `refresh_token` is single-use; a crash between writing `access_token` and `refresh_token` loses the pair → forces a full re-OAuth.
**Do this instead:** `auth.save_tokens()` temp+rename pattern (`hh-ai-vacancies/src/auth.py:25`).

## Error Handling

**Strategy:** Two-tier — recoverable (handled in-stage with status/reason) vs fatal (`AuthError`/`BatchStop`/`RuntimeError` bubbled to orchestrator which alerts via Telegram and returns a non-zero exit code).

**Patterns:**
- `NetworkError` from `http_client` → `apply_one` translates to `BatchStop("api_down")`; `auth.refresh` translates to `AuthError`; `telegram._send` swallows (returns `False`).
- HTTP 4xx/5xx never raise from `http_client.request` — caller inspects `resp.status`. Only `auth._is_auth_error(resp)` (403 + `errors[].type=="oauth"`) triggers refresh.
- `apply.apply_one` status machine maps every negotiations error type to a record status + reason; fatal ones raise `BatchStop`; 429 uses `Retry-After` or exponential 5→10→20s capped at `MAX_RETRIES_429=3`.
- `cover.call_ollama` returns `""` on any failure (network or non-200); `cover.letter_ok` validates 400–1500 chars, no placeholders, no HTML; on failure `fallback_letter` produces a deterministic template letter.
- Exit codes: `0` success, `2` auth/config fatal, `3` fetch fatal (all keywords failed → `RuntimeError`).
- `store.save(vac)` is called **before** sheets export so a Sheets/Telegram failure never loses the source of truth.

## Cross-Cutting Concerns

**Logging:** `print(..., file=sys.stderr)` for progress lines prefixed with `[module]` (e.g., `[pipeline]`, `[fetch]`, `[apply]`). `telegram._send` also prints the HTML payload to stdout for Hermes `deliver: origin`.

**Validation:** `store.validate_record(rec)` enforces `SCHEMA` types and required fields; `config.VALID_STATUSES` constrains the `status` field; `check_metrics.py` enforces 100% valid records, 0 dups, ≥95% enrichment, 100% covers as the "goal reached" gate.

**Authentication:** User OAuth (`data/hh_tokens.json`) for all HH API calls in the new pipeline; app token (`HH_APP_TOKEN`) only in the legacy monolith. Auto-refresh-once on `403 oauth`; second 403 → fatal + Telegram alert. Google Sheets uses an OAuth refresh token at `~/.config/gws/credentials.json` (refreshed per run via `sheets_export.get_access_token`).

**Secrets:** Stored in `~/.hermes/.env` (HH tokens, Telegram bot token, Ollama API key, resume id) loaded by `config.load_env_file()` without overwriting existing env vars. Never printed in reports/logs — replace with `[REDACTED]`. `~/.hermes/.env` edits must use Python `re.sub`, not `sed`/`patch`/`write_file` (Hermes blocks those).

---

*Architecture analysis: 2026-07-22*