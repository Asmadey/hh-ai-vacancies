# Codebase Structure

**Analysis Date:** 2026-07-22

## Directory Layout

```
hh-ai-vacancies/
├── README.md                          # Project overview, env vars, keywords, filters
├── CLAUDE.md                          # Codebase guidance for Claude Code (authoritative)
├── SKILL.md                           # Umbrella Hermes skill: recipes + incident history
├── config/
│   └── cron.yaml                       # Hermes cron job definition (new pipeline)
├── docs/
│   ├── api-contract.md                 # Verified HH API contract (negotiations, token, errors)
│   └── DEPLOY.md                       # Step-by-step deploy + cutover (T7–T9)
├── src/                                # NEW modular pipeline (apply-enabled)
│   ├── __init__.py
│   ├── pipeline.py                     # Orchestrator (8 stages)
│   ├── config.py                       # Env, paths, keywords, regexes, statuses
│   ├── http_client.py                  # Single HTTP entrypoint
│   ├── auth.py                         # User OAuth tokens + refresh-on-403
│   ├── fetch.py                        # GET /vacancies + filters
│   ├── store.py                        # vacancies.json source of truth + schema
│   ├── enrich.py                       # GET /vacancies/{id} full details
│   ├── cover.py                        # Ollama cover letters + fallback
│   ├── apply.py                        # POST /negotiations + status machine
│   ├── sheets_export.py                # Full-rewrite of HH_AI tab
│   └── telegram.py                     # HTML report + alerts
├── scripts/                            # Production scripts (legacy + ops)
│   ├── __init__.py
│   ├── hh_ai_vacancies.py              # Legacy monolith scraper (~900 lines)
│   ├── hh_token_updater.py             # Playwright HH app-token renewal (OTP)
│   └── migrate_seen.py                 # One-shot legacy seen.json → vacancies.json
├── tests/                              # Pytest suite (53 cases), stdlib + pytest
│   ├── __init__.py
│   ├── conftest.py                     # home/mock_http/no_sleep/tg_capture/tokens_file + fixtures
│   ├── test_apply.py
│   ├── test_auth.py
│   ├── test_cover.py
│   ├── test_cron_config.py
│   ├── test_fetch_enrich.py
│   ├── test_pipeline_e2e.py
│   ├── test_sheets_telegram.py
│   └── test_store.py
├── evals/                              # Post-run verification + LLM rubric
│   ├── __init__.py
│   ├── check_metrics.py               # Deterministic goal check (exit 0 = goal reached)
│   └── rate_cover_letters.py           # Ollama rubric, threshold ≥7/10
├── references/                         # Dated design notes + incident logs
│   ├── hh-api-notes.md
│   ├── hh-token-types-and-revocation.md
│   ├── hh-token-automation.md
│   ├── hh-cover-letter-generation.md
│   ├── hh-sheet-columns-correction-2026-06-28.md
│   ├── hh-userscript-auto-response.md
│   ├── ai-pm-hh-api-migration.md
│   ├── ai-pm-vacancies-processor.py
│   ├── archive-filter-incident-2026-06-27.md
│   ├── google-sheets-color-feedback-loop.md
│   ├── gws-batch-write-pattern.md
│   ├── proactive-cron-failure-handling.md
│   ├── skill-patch-marker-2026-07-05.md
│   ├── telegram-bot-patterns.md
│   ├── telegram-html-vs-markdownv2.md
│   ├── upwork-title-link-correction-2026-06-25.md
│   └── vacancy-cron-timeout-case-2026-06.md
└── templates/                          # Boilerplate for new HH trackers
    ├── hh_vacancy_scraper.py
    └── hh_auto_response.user.js        # Tampermonkey/Violentmonkey userscript
```

Runtime-only (not in repo, created at runtime under `HH_PIPELINE_HOME` or `~/.hermes/hh-ai-vacancies/`):

```
data/
├── vacancies.json          # Source of truth (vacancy_id -> record)
├── vacancies.json.bak      # Previous version backup
├── hh_tokens.json          # User OAuth {access, refresh, expires_in, obtained_at}
└── last_run_report.json    # Written by pipeline.run(), read by evals/check_metrics.py
```

## Directory Purposes

**`hh-ai-vacancies/src/`:**
- Purpose: the new modular pipeline package (apply-enabled)
- Contains: 11 Python modules, one orchestrator + 8 stage modules + config + http_client
- Key files: `pipeline.py` (orchestrator), `store.py` (schema + source of truth), `http_client.py` (single HTTP seam), `apply.py` (negotiations status machine)

**`hh-ai-vacancies/scripts/`:**
- Purpose: production scripts — legacy monolith, ops/token renewal, one-shot migrations
- Contains: 3 Python scripts
- Key files: `hh_ai_vacancies.py` (legacy 900-line scraper), `hh_token_updater.py` (Playwright OTP), `migrate_seen.py`

**`hh-ai-vacancies/tests/`:**
- Purpose: pytest suite (53 cases), no live network
- Contains: `conftest.py` + 8 test modules mirroring the `src/` stages
- Key files: `conftest.py` (fixtures: `home`, `mock_http`, `no_sleep`, `tg_capture`, `tokens_file`; helpers: `make_resp`, `search_item`, `vacancy_details`)

**`hh-ai-vacancies/evals/`:**
- Purpose: post-run verification + LLM rubric for cover letters
- Contains: `check_metrics.py` (deterministic goal gate) and `rate_cover_letters.py` (Ollama rubric)

**`hh-ai-vacancies/references/`:**
- Purpose: dated design notes and incident logs — search here before debugging a known area
- Contains: markdown notes + one reference Python processor
- Generated: No; committed: Yes

**`hh-ai-vacancies/templates/`:**
- Purpose: boilerplate for spinning up new HH vacancy trackers
- Contains: `hh_vacancy_scraper.py` (boilerplate) + `hh_auto_response.user.js` (Tampermonkey userscript)
- Generated: No; committed: Yes

**`hh-ai-vacancies/config/`:**
- Purpose: Hermes cron job definition for the new pipeline
- Contains: `cron.yaml` only
- Generated: No; committed: Yes

**`hh-ai-vacancies/docs/`:**
- Purpose: verified external API contract + deploy runbook
- Contains: `api-contract.md` (HH negotiations/token/errors), `DEPLOY.md` (setup + cutover T7–T9)

## Key File Locations

**Entry Points:**
- `hh-ai-vacancies/src/pipeline.py`: orchestrator; `python3 -m src.pipeline`
- `hh-ai-vacancies/evals/check_metrics.py`: post-run goal check
- `hh-ai-vacancies/scripts/hh_ai_vacancies.py`: legacy monolith (cron `99a55e0f5ac4`)
- `hh-ai-vacancies/scripts/hh_token_updater.py`: legacy app-token renewal
- `hh-ai-vacancies/scripts/migrate_seen.py`: one-shot migration

**Configuration:**
- `hh-ai-vacancies/src/config.py`: env loader, path helpers, keywords, regex filters, statuses, Sheet IDs
- `hh-ai-vacancies/config/cron.yaml`: Hermes cron (schedule, env, workdir)
- `~/.hermes/.env`: secrets (HH_APP_TOKEN, HH_RESUME_ID, TELEGRAM_*, OLLAMA_*) — NOT in repo
- `~/.config/gws/credentials.json`: Google OAuth refresh token — NOT in repo

**Core Logic:**
- `hh-ai-vacancies/src/pipeline.py:run()`: 8-stage flow
- `hh-ai-vacancies/src/store.py`: SCHEMA, `new_record`, `validate_record`, `merge`, `save` (atomic)
- `hh-ai-vacancies/src/apply.py`: `apply_one`, `apply_batch`, `select_candidates`, `BatchStop`
- `hh-ai-vacancies/src/auth.py`: `api_request` (refresh-on-403-once), `refresh`, `save_tokens`
- `hh-ai-vacancies/src/http_client.py`: `request`, `HttpResponse`, `NetworkError`

**Testing:**
- `hh-ai-vacancies/tests/conftest.py`: `MockHttp`, `home`, `tokens_file`, helpers
- `hh-ai-vacancies/tests/test_pipeline_e2e.py`: end-to-end pipeline test
- `hh-ai-vacancies/tests/test_apply.py`: apply status machine + BatchStop
- `hh-ai-vacancies/tests/test_store.py`: schema, merge, migration

**External Contract / Docs:**
- `hh-ai-vacancies/docs/api-contract.md`: HH API contract (negotiations, token, error mapping)
- `hh-ai-vacancies/docs/DEPLOY.md`: deploy + cutover runbook

## Naming Conventions

**Files:**
- `src/` modules: single lowercase word per stage (`fetch.py`, `enrich.py`, `cover.py`, `apply.py`, `store.py`, `auth.py`, `telegram.py`, `sheets_export.py`, `http_client.py`, `pipeline.py`, `config.py`). Underscore only for compound names (`sheets_export.py`, `http_client.py`).
- Tests: `test_<module>.py` mirroring the `src/` module under test (`test_apply.py`, `test_store.py`, `test_fetch_enrich.py`, `test_pipeline_e2e.py`, `test_sheets_telegram.py`, `test_cron_config.py`).
- Scripts: `hh_ai_vacancies.py`, `hh_token_updater.py`, `migrate_seen.py` — snake_case, verb-oriented.
- Evals: `check_metrics.py`, `rate_cover_letters.py` — verb phrase.
- References: `kebab-case-with-date.md` for incident logs (`archive-filter-incident-2026-06-27.md`, `upwork-title-link-correction-2026-06-25.md`); `kebab-case.md` for design notes (`hh-api-notes.md`, `telegram-html-vs-markdownv2.md`).

**Directories:**
- Lowercase, no separators (`src`, `tests`, `evals`, `scripts`, `templates`, `references`, `config`, `docs`).

**Module symbols:**
- Functions: `snake_case` (`fetch_all`, `apply_one`, `apply_batch`, `select_candidates`, `record_to_row`, `build_rows`, `generate_for_record`, `generate_all`, `vacancy_id_from_url`).
- Constants: `UPPER_SNAKE` (`KEYWORDS`, `JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`, `COLUMNS`, `MAX_RETRIES_429`, `NEGOTIATIONS_URL`, `SPREADSHEET_ID`, `SHEET_GID`).
- Config accessors: `lower_snake()` functions (`dry_run()`, `apply_limit()`, `resume_id()`, `telegram_bot_token()`, `telegram_chat_id()`, `ollama_api_key()`, `vacancies_path()`, `tokens_path()`, `run_report_path()`, `data_dir()`).
- Status string literals are Russian (`отправлено`, `не отправлено`, `тест`) — defined in `hh-ai-vacancies/src/config.py:107-110`.

## Where to Add New Code

**New pipeline stage:**
- Create `hh-ai-vacancies/src/<stage>.py` (one-word lowercase name).
- Route all HTTP through `http_client.request`; thread `(result, tokens)` returns if it calls HH.
- Add the call in sequence inside `hh-ai-vacancies/src/pipeline.py:run()` (numbered comment block).
- Add `hh-ai-vacancies/tests/test_<stage>.py` using `home`, `mock_http`, `tokens_file` fixtures from `hh-ai-vacancies/tests/conftest.py`.
- Add any new env vars / regexes / constants to `hh-ai-vacancies/src/config.py`.

**New HH API endpoint:**
- Reuse `auth.api_request(method, url, tokens, ...)` — it handles `User-Agent`, Bearer header, and refresh-on-403-once (`hh-ai-vacancies/src/auth.py:75`).
- If the endpoint needs a new error mapping, extend the relevant stage module (e.g., add a branch to `apply._negotiation_error`).
- Document the contract in `hh-ai-vacancies/docs/api-contract.md`.

**New env var / config knob:**
- Add to `hh-ai-vacancies/src/config.py` — either a module-level constant or an accessor function (prefer accessor for secrets / overridable values).
- Document in `hh-ai-vacancies/README.md` env table and `hh-ai-vacancies/CLAUDE.md`.
- For cron env, also add to `hh-ai-vacancies/config/cron.yaml:env`.

**New test fixture / helper:**
- Add to `hh-ai-vacancies/tests/conftest.py` — keep all shared fixtures here so individual test files stay focused.
- HH-shaped response builders: extend `make_resp`, `search_item`, `vacancy_details` patterns.

**New utility / shared helper:**
- If used across stages, add as a function in the relevant `src/` module (e.g., `store.now_iso`, `store.vacancy_id_from_url`).
- Avoid creating a generic `utils.py` — the project keeps helpers co-located with their domain.

**New reference / incident note:**
- Add a `kebab-case[-date].md` file under `hh-ai-vacancies/references/`.
- Cross-link from `hh-ai-vacancies/CLAUDE.md` and `hh-ai-vacancies/SKILL.md` if the lesson affects future edits.

**New tracker (separate project):**
- Start from `hh-ai-vacancies/templates/hh_vacancy_scraper.py` (boilerplate).

## Special Directories

**`hh-ai-vacancies/references/`:**
- Purpose: dated incident logs + design notes — the "lessons learned" archive
- Generated: No
- Committed: Yes
- Convention: search here first when debugging filtering, Sheets columns, Telegram formatting, or token issues

**`data/` (runtime, under `HH_PIPELINE_HOME` or workdir):**
- Purpose: source of truth + tokens + last run report
- Generated: Yes (at runtime)
- Committed: No (gitignored)
- Critical files: `vacancies.json` (source of truth), `vacancies.json.bak` (backup), `hh_tokens.json` (OAuth pair), `last_run_report.json` (eval input)

**`hh-ai-vacancies/.planning/codebase/`:**
- Purpose: GSD codebase map output (this document lives here)
- Generated: Yes (by `/gsd-map-codebase`)
- Committed: as per GSD workflow

**`hh-ai-vacancies/.pytest_cache/` and `__pycache__/`:**
- Purpose: pytest + Python bytecode cache
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-07-22*