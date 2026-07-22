# Codebase Structure

**Analysis Date:** 2026-07-22

## Directory Layout

```
hh-ai-vacancies/
├── src/                  # New modular apply pipeline (primary code path)
│   ├── __init__.py
│   ├── pipeline.py       # Orchestrator: 8 stages, run() entrypoint
│   ├── auth.py           # HH user OAuth load/refresh, api_request wrapper
│   ├── config.py         # Env loading, paths, KEYWORDS, regexes, statuses
│   ├── http_client.py    # Single urllib HTTP entrypoint (monkeypatchable)
│   ├── fetch.py          # GET /vacancies search + filters
│   ├── store.py          # vacancies.json source-of-truth, schema, merge, save
│   ├── enrich.py         # GET /vacancies/{id} full details
│   ├── cover.py          # Ollama cover letters (parallel) + fallback
│   ├── apply.py          # POST /negotiations, status mapping, batch control
│   ├── sheets_export.py  # Google Sheets clear+rewrite (visualization only)
│   └── telegram.py       # Bot API report/alert, parse_mode=HTML
├── scripts/              # Standalone ops scripts
│   ├── __init__.py
│   ├── hh_ai_vacancies.py        # Old monolith scraper (reference impl, deployed cron 99a55e0f5ac4)
│   ├── hh_token_updater.py       # Playwright HH OAuth refresh for old app-token scraper
│   └── migrate_seen.py           # One-shot legacy seen.json -> vacancies.json
├── evals/                # Post-run evaluation
│   ├── __init__.py
│   ├── check_metrics.py          # Deterministic goal check (exit 0 = ready)
│   └── rate_cover_letters.py     # LLM rubric scorer (threshold >=7/10)
├── tests/                # pytest suite (53 cases, stdlib + pytest only)
│   ├── __init__.py
│   ├── conftest.py               # home/mock_http/no_sleep/tg_capture/tokens_file + fixtures
│   ├── test_apply.py
│   ├── test_auth.py
│   ├── test_cover.py
│   ├── test_cron_config.py
│   ├── test_fetch_enrich.py
│   ├── test_pipeline_e2e.py
│   ├── test_sheets_telegram.py
│   └── test_store.py
├── config/
│   └── cron.yaml          # Hermes cron definition for the new pipeline
├── docs/                  # Architecture/contract docs
│   ├── api-contract.md    # Verified HH /negotiations + /token contract
│   └── DEPLOY.md          # Cutover + deployment steps
├── references/            # Dated incident logs + design notes (search here first when debugging)
│   ├── archive-filter-incident-2026-06-27.md
│   ├── hh-api-notes.md
│   ├── hh-cover-letter-generation.md
│   ├── hh-token-automation.md
│   ├── hh-token-types-and-revocation.md
│   ├── gws-batch-write-pattern.md
│   ├── google-sheets-color-feedback-loop.md
│   ├── telegram-bot-patterns.md
│   ├── telegram-html-vs-markdownv2.md
│   ├── proactive-cron-failure-handling.md
│   ├── vacancy-cron-timeout-case-2026.md
│   └── ... (see references/ for full list)
├── templates/             # Reusable starter templates
│   ├── hh_auto_response.user.js  # Tampermonkey userscript for HH auto-respond
│   └── hh_vacancy_scraper.py      # Copy-and-adjust scraper template
├── CLAUDE.md              # Guidance for Claude Code (read before editing)
├── SKILL.md               # Umbrella skill doc, recipes, incident history
├── README.md              # Project overview (documents the OLD monolith path)
└── .gitignore
```

Note: runtime `data/` (vacancies.json, hh_tokens.json, last_run_report.json) is created at runtime under `$HH_PIPELINE_HOME` (default repo root) — not committed. Legacy seen file lives at `~/.hermes/hh_ai_seen.json`. Google creds at `~/.config/gws/credentials.json`. Secrets in `~/.hermes/.env`.

## Directory Purposes

**`src/`:**
- Purpose: The new autonomous apply pipeline — the primary code path
- Contains: One module per pipeline stage + shared infra (`http_client`, `config`); all stdlib-only
- Key files: `src/pipeline.py` (orchestrator), `src/store.py` (source of truth), `src/auth.py` (OAuth), `src/apply.py` (`/negotiations`)

**`scripts/`:**
- Purpose: Standalone operator scripts, not imported by the pipeline
- Contains: Old monolith reference scraper, Playwright token updater, one-shot migration
- Key files: `scripts/hh_ai_vacancies.py` (900-line legacy scraper, still the active cron until cutover), `scripts/migrate_seen.py`

**`evals/`:**
- Purpose: Post-run quality checks (deterministic + LLM rubric)
- Contains: `check_metrics.py` (goal gate, reads `data/last_run_report.json`), `rate_cover_letters.py` (independent Ollama judge)
- Key files: `evals/check_metrics.py`, `evals/rate_cover_letters.py`

**`tests/`:**
- Purpose: pytest unit/integration/e2e suite, fully network-isolated via `MockHttp`
- Contains: `conftest.py` fixtures + 8 test modules mirroring `src/` stages
- Key files: `tests/conftest.py` (all fixtures and helpers: `home`, `mock_http`, `no_sleep`, `tg_capture`, `tokens_file`, `make_resp`, `search_item`, `vacancy_details`)

**`config/`:**
- Purpose: Hermes cron job definition for the new pipeline
- Contains: `cron.yaml` (schedule, env, `script: python3 -m src.pipeline`)

**`docs/`:**
- Purpose: Verified external contracts and deployment runbook
- Contains: `api-contract.md` (HH `/negotiations` + `/token` error mapping), `DEPLOY.md` (cutover steps)

**`references/`:**
- Purpose: Dated incident logs and design notes — search here before debugging a known-area problem
- Contains: ~17 markdown files covering token automation, archive-filter incident, gws batch-write, telegram HTML vs markdown, cron timeout case, etc.

**`templates/`:**
- Purpose: Copy-and-adjust starter implementations for other HH scraping projects
- Contains: Tampermonkey userscript (`hh_auto_response.user.js`) and scraper template (`hh_vacancy_scraper.py`)

## Key File Locations

**Entry Points:**
- `src/pipeline.py`: New pipeline orchestrator (`python3 -m src.pipeline`); `run()` is the function, exit code is its return
- `scripts/hh_ai_vacancies.py`: Old monolith (standalone `__main__`)
- `evals/check_metrics.py`: Goal gate (run after pipeline)
- `scripts/migrate_seen.py`: One-shot legacy migration
- `scripts/hh_token_updater.py`: Playwright OAuth refresh for old scraper

**Configuration:**
- `src/config.py`: Env loading, paths, `KEYWORDS`, `JUNK_RE`/`ARCHIVE_RE`/`RESUME_RE`, `VALID_STATUSES`, Sheets IDs, Ollama defaults
- `config/cron.yaml`: Hermes cron schedule + env
- `~/.hermes/.env`: Secrets (loaded by `config.load_env_file`, not committed)
- `~/.config/gws/credentials.json`: Google Sheets OAuth refresh token

**Core Logic:**
- `src/http_client.py`: Single HTTP entrypoint (`request`, `HttpResponse`, `NetworkError`)
- `src/auth.py`: `api_request` (Bearer + auto-refresh), `load_tokens`/`save_tokens` (atomic), `refresh`
- `src/store.py`: `SCHEMA`, `new_record`, `validate_record`, `load`/`save` (atomic + `.bak`), `merge`, `duplicates`, `migrate_seen`
- `src/apply.py`: `apply_one`, `apply_batch`, `select_candidates`, `BatchStop`
- `src/cover.py`: `generate_for_record`, `generate_all`, `call_ollama`, `clean_letter`, `letter_ok`, `fallback_letter`

**State (runtime, not committed):**
- `data/vacancies.json`: Source of truth (keyed by `vacancy_id`)
- `data/hh_tokens.json`: User OAuth tokens (atomic save)
- `data/last_run_report.json`: Metrics consumed by `evals/check_metrics.py`
- `data/vacancies.json.bak` / `data/hh_tokens.json.tmp`: Backup/temp from atomic writes

**Testing:**
- `tests/conftest.py`: `home`, `mock_http` (`MockHttp` FIFO queue), `no_sleep`, `tg_capture`, `tokens_file`, plus `make_resp`/`search_item`/`vacancy_details` fixture builders
- `tests/test_pipeline_e2e.py`: End-to-end pipeline test with full `MockHttp` queue

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (`http_client.py`, `sheets_export.py`)
- Test files: `test_<module>.py` co-located in `tests/` (`test_apply.py`, `test_store.py`, `test_fetch_enrich.py`, `test_sheets_telegram.py`, `test_pipeline_e2e.py`)
- Evals: verb-noun (`check_metrics.py`, `rate_cover_letters.py`)
- Scripts: `hh_<purpose>.py` (`hh_ai_vacancies.py`, `hh_token_updater.py`); migration as `migrate_<entity>.py`
- Reference notes: `<topic>-<type>-<YYYY-MM-DD>.md` for incidents (`archive-filter-incident-2026-06-27.md`), otherwise `<topic>.md` (`hh-api-notes.md`)
- Templates: `hh_<purpose>.<ext>` (`hh_auto_response.user.js`, `hh_vacancy_scraper.py`)

**Directories:**
- Lowercase, no separators (`src`, `tests`, `evals`, `references`, `templates`, `config`, `docs`, `scripts`)

**Module-level constants:**
- `UPPER_SNAKE` (`KEYWORDS`, `JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`, `VALID_STATUSES`, `STATUS_SENT`, `SCHEMA`, `MAX_RETRIES_429`, `COLUMNS`, `NEGOTIATIONS_URL`, `SPREADSHEET_ID`, `SHEET_GID`)

**Functions:**
- `snake_case` (`fetch_all`, `enrich_new`, `apply_batch`, `select_candidates`, `generate_all`, `format_report`, `vacancy_id_from_url`)
- Predicates prefixed `is_`/`has_` (`is_active`, `is_relevant`, `letter_ok`) — note `title_ok` is not used; relevance lives in `is_relevant`
- Private helpers prefixed `_` (`_post_negotiation`, `_negotiation_error`, `_set_status`, `_is_auth_error`, `_work_format`, `_sheets_url`, `_send`)

**Classes/exceptions:**
- `CapWord` for errors and wrappers: `AuthError`, `BatchStop`, `NetworkError`, `HttpResponse`, `MockHttp`

## Where to Add New Code

**New pipeline stage:**
- Create `src/<stage>.py` as a self-contained module with pure functions operating on the `store` dict (and `tokens` where HH calls are needed).
- Wire it into `src/pipeline.py:run()` at the correct position; persist via `store.save()` before any external sink.
- Route ALL HTTP through `src/http_client.request` (never `urllib.request.urlopen` directly).
- Add a `tests/test_<stage>.py` mirroring existing test style; use `mock_http`, `home`, `tokens_file` fixtures from `tests/conftest.py`.

**New HH API endpoint integration:**
- Add the call in the relevant stage module via `auth.api_request(method, url, tokens, ...)` so you inherit Bearer auth + auto-refresh.
- Always set `User-Agent: config.HH_USER_AGENT` (handled inside `api_request`).
- Extend `docs/api-contract.md` with verified request/response/error mapping.

**New search keyword / filter:**
- Add to `config.KEYWORDS` (list) or extend `JUNK_RE`/`ARCHIVE_RE`/`RESUME_RE` in `src/config.py`.
- Add regression coverage in `tests/test_fetch_enrich.py` using `search_item(...)`.

**New env var / runtime flag:**
- Add a getter in `src/config.py` (follow `dry_run()`/`apply_limit()` pattern); set a safe default.
- Mirror in `config/cron.yaml:env` if it should be set on the cron host.
- Document in `CLAUDE.md` "Config & secrets".

**New status / status_reason:**
- Add status constant + include in `config.VALID_STATUSES` if it is a terminal status; otherwise use a free-form `status_reason`.
- Update `apply.select_candidates` `RETRYABLE` set if the new reason should be re-queued across runs.
- Add `validate_record` / `evals/check_metrics.py` coverage.

**New Google Sheets column:**
- Edit `sheets_export.COLUMNS` and `record_to_row` in `src/sheets_export.py`.
- Confirm the new shape before the first write — changing columns later requires clearing and rewriting the sheet (see `references/hh-sheet-columns-correction-2026-06-28.md`).
- Update `evals/check_metrics.py` if it asserts column count.

**New Telegram report field:**
- Edit `telegram.format_report` (`src/telegram.py`); escape dynamic content with `telegram.esc`; keep `parse_mode=HTML`.

**New test fixture/helper:**
- Add to `tests/conftest.py`; reuse `make_resp`, `search_item`, `vacancy_details` to build HH-shaped payloads.

**New eval:**
- Add `evals/<name>.py` reading from `data/vacancies.json` / `data/last_run_report.json`; exit 0 on pass.

**New ops script:**
- Add `scripts/<name>.py` with `sys.path.insert(0, ...)` and import from `src`; run as `python3 -m scripts.<name>`.

**Utilities:**
- Shared helpers belong in the relevant `src/<stage>.py` (no separate `utils.py` exists); cross-stage helpers go in `src/store.py` (`now_iso`, `vacancy_id_from_url`) or `src/config.py`.

## Special Directories

**`data/` (runtime, not committed):**
- Purpose: All mutable runtime state — `vacancies.json`, `hh_tokens.json`, `last_run_report.json`, plus `.bak`/`.tmp` artifacts
- Generated: Yes (created on first run / by tests under `HH_PIPELINE_HOME`)
- Committed: No (override root via `HH_PIPELINE_HOME` env var; tests set it to a tmp path)

**`references/`:**
- Purpose: Dated incident logs and design notes — read before debugging a known-area problem
- Generated: No (hand-curated)
- Committed: Yes

**`templates/`:**
- Purpose: Copy-and-adjust starter implementations for new HH scraping projects
- Generated: No
- Committed: Yes

**`__pycache__/` (and `.pytest_cache/`, `.coverage*`):**
- Purpose: Python bytecode / pytest cache / coverage artifacts
- Generated: Yes
- Committed: No (per `.gitignore`)

---

*Structure analysis: 2026-07-22*