<!-- GSD:project-start source:PROJECT.md -->

## Project

**HH-AI-Vacancies**

Autonomous cron pipeline that searches HeadHunter (hh.ru) for AI/PM vacancies across 13 keywords, filters and enriches them, generates cover letters via Ollama Cloud, auto-applies through the HH `/negotiations` endpoint, exports results to Google Sheets, and reports to Telegram. Private project; runs on a Hermes Agent cron host (Linux, Python 3.10), every 2 days at 09:00 MSK via `python3 -m src.pipeline`.

**Core Value:** Reliably surface relevant AI/PM vacancies on hh.ru and auto-apply to them with generated cover letters every run — without manual token babysitting.

### Constraints

- **Tech stack**: stdlib only (`urllib`, `json`, `re`, `concurrent.futures`) — no `requests` or third-party runtime deps — Why: test harness and host simplicity
- **Single HTTP seam**: all HTTP goes through `src/http_client.request()` — Why: `MockHttp` test harness monkeypatches that one symbol
- **Telegram HTML only**: `parse_mode=HTML`, dynamic content escaped via `telegram.esc()` — Why: MarkdownV2 renders as raw text
- **User-Agent mandatory**: `config.HH_USER_AGENT` on all HH requests — Why: HH returns `400 bad_user_agent` otherwise
- **Live apply is irreversible**: real `POST /negotiations` to real vacancies — first live run capped at `APPLY_LIMIT=2` — Why: CLAUDE.md policy; outward-facing action
- **Atomic token save**: `refresh_token` is single-use; temp+rename only — Why: losing the pair forces full re-OAuth
- **Compatibility**: code must run on both Python 3.10 (host) and 3.13 (this Mac) for the live e2e

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.10 — all application logic in `hh-ai-vacancies/src/*.py`, `hh-ai-vacancies/scripts/*.py`, `hh-ai-vacancies/evals/*.py`, `hh-ai-vacancies/tests/*.py` (pytest cache shows cpython-310 pycs).
- JavaScript — Tampermonkey userscript template `hh-ai-vacancies/templates/hh_auto_response.user.js` (browser-side auto-response helper, not part of the cron pipeline).
- YAML — cron job definition `hh-ai-vacancies/config/cron.yaml`.

## Runtime

- Python 3.10 stdlib only for the new modular pipeline (`hh-ai-vacancies/src/`). No `requests`, no third-party HTTP libs. Uses `urllib.request`, `urllib.parse`, `urllib.error`, `json`, `re`, `concurrent.futures`, `datetime`, `html`, `shutil`, `os`, `sys`, `argparse`.
- Runs on a Hermes Agent cron host (Linux). Workdir `~/.hermes/hh-ai-vacancies` per `hh-ai-vacancies/config/cron.yaml`.
- `scripts/hh_token_updater.py` additionally requires Playwright + Chromium and `xvfb-run` on headless hosts (`pip install playwright; python3 -m playwright install chromium`).
- None declared. No `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, or `poetry.lock` exist.
- Lockfile: missing — stdlib-only by design; only runtime extra is Playwright (used solely by the offline token updater script, documented inline in its header).
- pytest is expected to be preinstalled on the host for `python3 -m pytest`.

## Frameworks

- None (no web/CLI framework). The application is a batch pipeline invoked as `python3 -m src.pipeline` (`hh-ai-vacancies/src/pipeline.py`).
- pytest 9.1.1 — 53 test cases across `hh-ai-vacancies/tests/` (per `hh-ai-vacancies/CLAUDE.md`). Cache artifacts in `hh-ai-vacancies/.pytest_cache/` and `__pycache__/test_*.cpython-310-pytest-9.1.1.pyc` confirm version.
- No coverage tool configured (`.coverage` file present at `hh-ai-vacancies/.coverage` but no `.coveragerc`/coverage config).
- No build step. Python runs from source.
- Cron scheduler: Hermes Agent cron (job `99a55e0f5ac4` for the old monolith; `config/cron.yaml` defines the new modular job, schedule `0 9 */2 * *`).

## Key Dependencies

- Python 3.10 stdlib (`urllib`, `json`, `re`, `concurrent.futures`, `html`, `shutil`, `argparse`) — the entire HTTP surface goes through the single entrypoint `hh-ai-vacancies/src/http_client.py:request()`.
- Playwright + Chromium — only for `hh-ai-vacancies/scripts/hh_token_updater.py` (interactive HH.ru admin login to rotate the app token). Not used by the cron pipeline.
- Telegram Bot API — reports + alerts via `hh-ai-vacancies/src/telegram.py` (stdlib `urllib`, no SDK).
- Google Sheets API v4 — full-rewrite export via `hh-ai-vacancies/src/sheets_export.py` (OAuth refresh-token flow against `https://oauth2.googleapis.com/token`).
- Ollama Cloud — cover-letter generation + LLM-rubric eval via `hh-ai-vacancies/src/cover.py` and `hh-ai-vacancies/evals/rate_cover_letters.py` (OpenAI-compatible `/chat/completions` endpoint, default model `deepseek-v4-flash`, base URL `https://ollama.com/v1`).
- HeadHunter (hh.ru) public REST API — search, vacancy details, OAuth token refresh, and `/negotiations` apply via `hh-ai-vacancies/src/fetch.py`, `hh-ai-vacancies/src/enrich.py`, `hh-ai-vacancies/src/auth.py`, `hh-ai-vacancies/src/apply.py`.

## Configuration

- Secrets and runtime config live in `~/.hermes/.env`, loaded by `hh-ai-vacancies/src/config.py:load_env_file()` (does not overwrite existing env vars). Hermes blocks `sed`/`patch`/`write_file` edits to this file; update keys with Python `re.sub` (snippet in `hh-ai-vacancies/SKILL.md`).
- Path override knob: `HH_PIPELINE_HOME` (defaults to package parent dir) — every `data/` path flows through `hh-ai-vacancies/src/config.py:data_dir()`. This is the test-isolation switch (see `hh-ai-vacancies/tests/conftest.py:home` fixture).
- `DRY_RUN` — default `"1"` (safe; no applies sent). `0` = live mode.
- `APPLY_LIMIT` — int, default `0` (uncapped). Caps applies per run.
- `APPLY_PAUSE_SEC` — float, default `5`. Delay between `/negotiations` POSTs.
- `HH_RESUME_ID` — required for live applies; missing in live mode triggers Telegram alert and exit 2.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram delivery (optional; absent → stdout fallback, no error).
- `OLLAMA_BASE_URL` — default `https://ollama.com/v1`.
- `OLLAMA_MODEL` — default `deepseek-v4-flash`.
- `OLLAMA_API_KEY` — required for LLM cover letters; absent → deterministic template fallback (`hh-ai-vacancies/src/cover.py:fallback_letter`).
- `COVER_LETTER_MAX_TOKENS` (default `900`), `COVER_LETTER_TEMP` (default `0.4`), `COVER_LETTER_WORKERS` (default `10`, parallel `ThreadPoolExecutor`).
- `HH_APP_TOKEN` — used only by the legacy monolith `hh-ai-vacancies/scripts/hh_ai_vacancies.py` for public search; the new pipeline uses user OAuth tokens instead.
- `HH_API = "https://api.hh.ru"`.
- `HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"` — mandatory for all HH requests (HH returns `400 bad_user_agent` without it).
- `SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"`, `SHEET_GID = 1464494667`, `SHEET_NAME = "HH_AI"`.
- `GOOGLE_CREDS_PATH = ~/.config/gws/credentials.json`.
- `KEYWORDS` — 13 AI/PM search terms (Russian + English).
- Regex filters `JUNK_RE`, `RESUME_RE`, `ARCHIVE_RE` (compiled at import).
- Status constants `STATUS_SENT="отправлено"`, `STATUS_NOT_SENT="не отправлено"`, `STATUS_TEST="тест"`; `VALID_STATUSES` set.
- No build config. Cron job config: `hh-ai-vacancies/config/cron.yaml` (Hermes `cronjob create`; edits require `pause → remove → create` because `update` silently no-ops on identical bodies).
- Git ignore: `hh-ai-vacancies/.gitignore` excludes `__pycache__/`, `*.pyc`, `*.pyo`, `.venv/`, `*.log`, `.DS_Store`, model files (`*.tflite`, `*.onnx`, `*.pt`, `*.pth`, `*.safetensors`).

## Platform Requirements

- Python 3.10. pytest 9.1.1 for tests. No virtualenv mandated (`.venv/` ignored if used).
- For token rotation only: Playwright + Chromium + `xvfb-run -a` on headless hosts (`hh-ai-vacancies/scripts/hh_token_updater.py`).
- Tests run fully offline — `hh-ai-vacancies/tests/conftest.py:MockHttp` monkeypatches `http_client.request` with a FIFO URL-substring queue; no live network.
- Hermes Agent cron host (Linux). New pipeline cron: `python3 -m src.pipeline` from workdir `~/.hermes/hh-ai-vacancies`, schedule every 2 days at 09:00 MSK, `no_agent: true`, `deliver: origin` (stdout mirrored to Telegram in addition to direct Bot API).
- Legacy monolith cron job id `99a55e0f5ac4` (`no_agent: true`); cutover described in `hh-ai-vacancies/docs/DEPLOY.md` Step 4.
- Required host files: `~/.hermes/.env` (secrets), `data/hh_tokens.json` (user OAuth pair — atomic save because `refresh_token` is single-use), `~/.config/gws/credentials.json` (Google Sheets OAuth).

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Language & Runtime

- Python 3.10 (cache files: `*.cpython-310.pyc` across `src/__pycache__/`, `tests/__pycache__/`).
- **Stdlib only** for the `src/` pipeline — no `requests`, no third-party HTTP/JSON deps. HTTP is done via `urllib.request`/`urllib.error`/`urllib.parse` (see `hh-ai-vacancies/src/http_client.py`). Do not add third-party runtime dependencies; CLAUDE.md explicitly forbids it.
- `pytest` is the only test dependency (not pinned in a `requirements.txt` — none exists).

## Naming Patterns

- `src/` modules: single lowercase word, snake_case, one stage per file: `auth.py`, `fetch.py`, `store.py`, `enrich.py`, `cover.py`, `apply.py`, `sheets_export.py`, `telegram.py`, `http_client.py`, `config.py`, `pipeline.py`.
- Tests: `test_<module>.py` mirroring the module under test — `tests/test_apply.py` ↔ `src/apply.py`, `tests/test_fetch_enrich.py` covers `src/fetch.py` + `src/enrich.py`, `tests/test_sheets_telegram.py` covers `src/sheets_export.py` + `src/telegram.py`. `tests/test_pipeline_e2e.py` covers `src/pipeline.py` end-to-end.
- Evals: `evals/check_metrics.py`, `evals/rate_cover_letters.py` — verb-noun snake_case.
- Scripts: `scripts/hh_ai_vacancies.py`, `scripts/hh_token_updater.py`, `scripts/migrate_seen.py`.
- snake_case: `apply_one`, `fetch_all`, `enrich_new`, `build_prompts`, `generate_for_record`, `select_candidates`, `vacancy_id_from_url`, `format_salary`, `parse_level`, `match_reason`, `record_to_row`, `build_rows`.
- Private helpers prefixed `_`: `_post_negotiation` (`hh-ai-vacancies/src/apply.py:21`), `_negotiation_error` (`src/apply.py:32`), `_set_status` (`src/apply.py:41`), `_is_auth_error` (`src/auth.py:68`), `_work_format` (`src/enrich.py:18`), `_send` (`src/telegram.py:12`), `_sheets_url` (`src/sheets_export.py:52`), `_rec`/`_vac` test helpers.
- Boolean predicates: `is_active`, `is_relevant` (`src/fetch.py:37,41`), `letter_ok` (`src/cover.py:125`), `dry_run` (`src/config.py:41`).
- snake_case: `found_total`, `new_ids`, `seen_ids`, `candidate_ids`, `apply_metrics`.
- Module-level constants SCREAMING_SNAKE_CASE: `KEYWORDS`, `JUNK_RE`, `RESUME_RE`, `ARCHIVE_RE`, `SCHEMA`, `NEGOTIATIONS_URL`, `TOKEN_URL`, `MAX_RETRIES_429`, `COVER_LETTER_MAX_TOKENS`, `COVER_LETTER_WORKERS`, `RESUME`, `CLOSING`, `PLACEHOLDER_RE`, `COLUMNS`, `SPREADSHEET_ID`, `SHEET_GID`, `SHEET_NAME`, `SHEET_URL`, `HH_API`, `HH_USER_AGENT`, `STATUS_SENT`, `STATUS_NOT_SENT`, `STATUS_TEST`, `VALID_STATUSES`, `LEGACY_SEEN_PATH`, `TOKENS` (test fixture data in `tests/conftest.py:78`).
- Env-derived runtime values are accessed via accessor functions, not bare constants: `dry_run()`, `apply_limit()`, `resume_id()`, `ollama_api_key()`, `telegram_bot_token()`, `telegram_chat_id()`, `data_dir()`, `vacancies_path()`, `tokens_path()`, `run_report_path()` (all in `hh-ai-vacancies/src/config.py`). Follow this pattern for any new env-overridable setting so `HH_PIPELINE_HOME` / test monkeypatching works.
- No type hints anywhere in the codebase. Do not add them to match style — parameters and returns are documented in docstrings only.
- Schema declared as a dict literal: `SCHEMA` in `hh-ai-vacancies/src/store.py:12` maps field -> `(type, required)` tuple; `validate_record` (`src/store.py:67`) enforces it.
- Custom exceptions: `BatchStop` (`src/apply.py:14`, carries `.reason`), `AuthError` (`src/auth.py:13`), `NetworkError` (`src/http_client.py:27`). Subclass `Exception` directly; no shared base class.

## Code Style

- No formatter config (no `.flake8`, `pyproject.toml`, `setup.cfg`, `ruff.toml`, `.pre-commit-config.yaml` present). Style is enforced by review and pattern-matching.
- 4-space indentation; UTF-8 source; line lengths stay well under 100 generally but there is no hard limit.
- Strings: double quotes (`"..."`) for module docstrings and most literals; single quotes for `re.compile` raw strings (`r"\b(...)\b"`) and short inline literals. Prefer double quotes for new code.
- None configured. `# noqa: E402` markers appear after `sys.path.insert` in `tests/conftest.py:8`, `evals/check_metrics.py:19`, `evals/rate_cover_letters.py:13` — replicate this when a module must manipulate `sys.path` before its first import.
- `#!/usr/bin/env python3` on executables only: `evals/check_metrics.py:1`, `evals/rate_cover_letters.py:1`, `scripts/hh_token_updater.py`, `scripts/hh_ai_vacancies.py`. Library modules in `src/` have no shebang.

## Module Layout

## Import Organization

- `tests/conftest.py:7` and eval entrypoints insert the repo root onto `sys.path` before importing `src`:
- None. No package alias, no `pyproject.toml` `[tool.setuptools]` config. `src/` is a plain package (`src/__init__.py` is empty).

## Error Handling

- `http_client.request()` (`hh-ai-vacancies/src/http_client.py:31`) returns an `HttpResponse` for **any** HTTP status (4xx/5xx included). Only DNS/timeout/connection failures raise `NetworkError`. Never raise on a non-2xx HTTP status — inspect `resp.status` and `resp.json()`.
- Records carry `status` + `status_reason` rather than throwing. `apply.py:_set_status` (`src/apply.py:41`) is the canonical mutation: sets `status`, `status_reason`, `updated_at`, and `applied_at` (only on `STATUS_SENT` and not `already_applied`).
- `BatchStop` (`src/apply.py:14`) halts a batch and defers remaining records with `status_reason = f"deferred_{reason}"` (`src/apply.py:133`). Always re-raise `AuthError`; always catch `BatchStop` in the batch loop.
- `apply_one` (`src/apply.py:49`) maps every HH error code to a status: `test_required` → `STATUS_TEST`, `already_applied` → `STATUS_SENT`/`already_applied`, `limit_exceeded`/`resume_not_found`/`captcha_required`/5xx → `STATUS_NOT_SENT` + `BatchStop`, 429 → backoff then retry then `rate_limited`.
- Auth refresh-once: `auth.api_request` (`src/auth.py:75`) auto-refreshes the OAuth token on `403 oauth` exactly once (`_retried` flag); second `403 oauth` → `AuthError` + Telegram alert. Always thread `tokens` through return values (`resp, tokens`) so refreshed tokens propagate.
- Atomic file writes for tokens and store: write to `path + ".tmp"`, then `os.replace(tmp, path)` — see `auth.save_tokens` (`src/auth.py:25`) and `store.save` (`src/store.py:95`). `store.save` also backs up the previous file to `path + ".bak"` first (`src/store.py:100`). Follow this temp+rename pattern for any new persisted state — `refresh_token` is single-use, losing the pair means re-running OAuth.
- Pipeline-level exit codes in `hh-ai-vacancies/src/pipeline.py:run()`: `0` success, `2` auth/config fatal, `3` fetch fatal. Always `store.save(vac)` before returning on a mid-stage failure (`src/pipeline.py:55,67,72,75`).
- Telegram alerts via `telegram.send_alert` on every fatal condition; wrap dynamic content with `telegram.esc` (= `html.escape(..., quote=False)`, `src/telegram.py:8`).

## Logging

- Stage progress lines: `print(f"[pipeline] start (DRY_RUN={dry})", file=sys.stderr)` (`src/pipeline.py:21`), `print(f"[fetch] '{kw}' HTTP {resp.status}", file=sys.stderr)` (`src/fetch.py:103`), `print(f"[enrich] {rec['vacancy_id']} HTTP {resp.status}", file=sys.stderr)` (`src/enrich.py:34`), `print(f"[cover] ollama HTTP {resp.status}", file=sys.stderr)` (`src/cover.py:90`), `print(f"[apply] batch stopped: {e.reason}", file=sys.stderr)` (`src/apply.py:129`).
- Tag prefix in square brackets identifies the stage: `[pipeline]`, `[fetch]`, `[enrich]`, `[cover]`, `[apply]`. Replicate this for new stages.
- Only `telegram._send` writes to stdout (the report payload). Everything else goes to stderr.

## Comments

- Russian inline comments for non-obvious business rules: `src/store.py:96` `# бэкап = предыдущая версия`, `src/apply.py:131` `# остальные — «не отправлено», перенос на следующий прогон`, `src/pipeline.py:74` `# persist source of truth ДО экспорта`, `src/enrich.py:55` `# Вакансия ушла в архив между fetch и enrich`.
- English comments only for `# noqa` markers.
- No block comments; use inline `#` on their own line above the code they explain.
- N/A (Python). Use triple-quoted module docstrings and function docstrings in Russian, terse (1-3 lines). Examples: `src/store.py:107-110` (`merge`), `src/apply.py:49-50` (`apply_one`), `src/store.py:67-68` (`validate_record`).

## Function Design

- HTTP-calling functions return `(result, tokens)` tuples so refreshed tokens propagate: `auth.api_request` → `(resp, tokens)`, `enrich_record` → `(ok, tokens)`, `apply_one` → `tokens`, `apply_batch` → `(metrics, tokens)`, `fetch_all` → `(records, found_total, tokens)`.
- Status-bearing functions mutate the record in place AND return a small value: `enrich_record(rec, tokens)` mutates `rec` and returns `(ok, tokens)`; `apply_one(rec, ...)` mutates `rec` and returns `tokens`.
- `store.save` / `auth.save_tokens` return `None`. `cover.generate_for_record` returns the letter string.

## Module Design

- `src/__init__.py` is empty (0 lines) — `src` is a namespace package, not a re-export hub.
- `tests/__init__.py`, `evals/__init__.py` likewise empty.

## Concurrency

- Cover-letter generation uses `concurrent.futures.ThreadPoolExecutor` with `as_completed` (`hh-ai-vacancies/src/cover.py:146-155`), capped at `min(COVER_LETTER_WORKERS, len(new_ids))`. Threads are acceptable because work is I/O-bound (Ollama HTTP).
- The rest of the pipeline is sequential. Do not introduce threads/async elsewhere without a measured bottleneck; `apply_batch` deliberately serializes with `APPLY_PAUSE_SEC` sleep between posts (`src/apply.py:124`).

## Security Conventions

- `User-Agent` header is mandatory on all HH requests (`config.HH_USER_AGENT`, `src/config.py:50`) — HH returns `400 bad_user_agent` without it. `auth.api_request` sets it on every call (`src/auth.py:78`).
- Telegram `parse_mode=HTML` always (`src/telegram.py:21`). Escape all dynamic content with `telegram.esc` before embedding — Markdown is forbidden (see `references/telegram-html-vs-markdownv2.md`).
- Secrets never printed; redact with `[REDACTED]`. Env loaded from `~/.hermes/.env` via `config.load_env_file` (`src/config.py:5`) which never overwrites existing env vars.
- `data/hh_tokens.json` written atomically (temp + rename) because `refresh_token` is single-use.

## Test-Case IDs

- `tests/test_pipeline_e2e.py:1` `"""TC-01, TC-04, TC-06, TC-12, evals: e2e DRY_RUN..."""`
- `tests/test_apply.py:1` `"""TC-10, TC-11, TC-12..."""`
- `tests/test_auth.py:1` `"""TC-02, TC-03..."""`
- `tests/test_store.py:1` `"""TC-04, TC-06, TC-07..."""`
- `tests/test_cover.py:1` `"""TC-09..."""`
- `tests/test_fetch_enrich.py:1` `"""...TC-08 enrichment."""`
- `tests/test_sheets_telegram.py:1` `"""TC-05, TC-13, TC-14."""`

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

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

- **Linear 8-stage flow** in `pipeline.py:run()` — auth → fetch → merge/dedup → enrich → cover → apply → store.save → sheets → telegram. No branching DAG, no queue.
- **Single HTTP entrypoint** — every module calls `http_client.request(...)`. This is the only network seam, which is why tests can mock all I/O by monkeypatching one symbol (`tests/conftest.py:MockHttp`).
- **JSON file as source of truth** — `data/vacancies.json` keyed by `vacancy_id`. Google Sheets is visualization-only and rewritten in full each run.
- **Atomic persistence** — `store.save()` writes `.tmp` then `os.replace`, with `.bak` backup of the previous version; same pattern for token refresh in `auth.save_tokens()` (refresh_token is single-use — losing the pair means re-running OAuth).
- **stdlib-only** — `urllib`, `json`, `re`, `concurrent.futures`. No `requests`, no third-party runtime deps.
- **DRY_RUN safe default** — `config.dry_run()` returns `True` unless `DRY_RUN=0`; apply step writes no POSTs in dry mode.
- **Two coexisting code paths** — the new modular `src/` pipeline (apply-enabled) and the legacy monolith `scripts/hh_ai_vacancies.py` (search/reporting only). CLAUDE.md is explicit about which path to edit.

## Layers

- Purpose: invoke the pipeline on a schedule
- Location: `hh-ai-vacancies/config/cron.yaml` (Hermes cron, `0 9 */2 * *`, `no_agent: true`, `deliver: origin`); script `python3 -m src.pipeline`
- Contains: schedule, env vars, workdir
- Depends on: Hermes Agent host
- Used by: operators
- Purpose: sequence the 8 stages and aggregate metrics
- Location: `hh-ai-vacancies/src/pipeline.py`
- Contains: `run()`, `write_report()`
- Depends on: every other `src/` module
- Used by: cron entry, tests (`tests/test_pipeline_e2e.py`)
- Purpose: each stage reads/mutates the in-memory `vac` dict and returns tokens/metrics
- Location: `hh-ai-vacancies/src/{auth,fetch,enrich,cover,apply,sheets_export,telegram,store}.py`
- Contains: pure functions + `auth.api_request` wrapper
- Depends on: `config`, `http_client`, `store`
- Used by: `pipeline.run()`
- Purpose: single HTTP seam; path/env config; schema/validate
- Location: `hh-ai-vacancies/src/http_client.py`, `hh-ai-vacancies/src/config.py`, `hh-ai-vacancies/src/store.py`
- Contains: `request()`, `HttpResponse`, `NetworkError`; env loader; SCHEMA, `validate_record`
- Depends on: `urllib`
- Used by: all domain stages
- HH.ru API (`api.hh.ru`), Ollama Cloud (`ollama.com/v1`), Google Sheets API, Telegram Bot API
- Local files under `data/` (source of truth), `~/.hermes/.env` (secrets), `~/.config/gws/credentials.json` (Google OAuth)

## Data Flow

### Primary Request Path (pipeline run)

### Auth refresh flow

### Apply status flow

- `201` → `отправлено` (or `already_applied` → `отправлено` reason=already_applied)
- `test_required` → `тест`
- `limit_exceeded` / `resume_not_found` / `captcha_required` / 5xx / `NetworkError` → `BatchStop`, rest deferred with `reason=deferred_<cause>`
- `429` → backoff loop, then `не отправлено` reason=rate_limited
- `invalid_vacancy` / `archived` → `не отправлено`, not retried
- In-memory `vac` dict (vacancy_id → record) threaded through every stage; mutated in place
- Persisted only via `store.save()` (atomic, with `.bak`)
- Tokens threaded explicitly as `(resp, tokens)` returns so refreshes propagate
- No global mutable state except module-level compiled regexes in `config.py` (`JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`)

## Key Abstractions

- Purpose: unit of data flowing through the pipeline
- Schema: `hh-ai-vacancies/src/store.py:SCHEMA` (22 fields, typed, required flags)
- Constructor: `store.new_record(vacancy_id, url, title, **kw)`
- Validator: `store.validate_record(rec)` — returns list of problems
- Status enum: `config.VALID_STATUSES = {отправлено, не отправлено, тест}`
- Purpose: uniform response object across the single HTTP seam
- Location: `hh-ai-vacancies/src/http_client.py:7`
- Pattern: `request()` returns `HttpResponse` for ANY HTTP status (no raise on 4xx/5xx); only network failures raise `NetworkError`
- Purpose: fatal auth signal bubbled to orchestrator
- Location: `hh-ai-vacancies/src/auth.py:13`
- Pattern: raised after refresh fails; pipeline catches and alerts via Telegram
- Purpose: halt the apply batch on fatal per-vacancy errors while leaving the rest deferrable
- Location: `hh-ai-vacancies/src/apply.py:14`
- Pattern: carries `reason`; `apply_batch` catches, marks remaining as `deferred_<reason>`, breaks

## Entry Points

- Location: `hh-ai-vacancies/src/pipeline.py` (`if __name__ == "__main__": sys.exit(run())`)
- Triggers: Hermes cron (`hh-ai-vacancies/config/cron.yaml`); manual `DRY_RUN=1 python3 -m src.pipeline`
- Responsibilities: run all 8 stages, write report, exit with 0/2/3
- Location: `hh-ai-vacancies/evals/check_metrics.py`
- Triggers: post-run verification
- Responsibilities: deterministic goal check (schema, dups, enrichment ≥95%, covers 100%, sheets_rows == JSON, telegram_delivered)
- Location: `hh-ai-vacancies/scripts/migrate_seen.py`
- One-shot legacy `~/.hermes/hh_ai_seen.json` → `data/vacancies.json`
- Location: `hh-ai-vacancies/scripts/hh_token_updater.py`
- Playwright-based renewal of the legacy HH **app** token (not used by the new pipeline, which uses user OAuth)
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

### Reporting archived vacancies as new

### Treating `bad_authorization` as revocation

### Telegram MarkdownV2 / unescaped dynamic content

### Non-atomic token save

## Error Handling

- `NetworkError` from `http_client` → `apply_one` translates to `BatchStop("api_down")`; `auth.refresh` translates to `AuthError`; `telegram._send` swallows (returns `False`).
- HTTP 4xx/5xx never raise from `http_client.request` — caller inspects `resp.status`. Only `auth._is_auth_error(resp)` (403 + `errors[].type=="oauth"`) triggers refresh.
- `apply.apply_one` status machine maps every negotiations error type to a record status + reason; fatal ones raise `BatchStop`; 429 uses `Retry-After` or exponential 5→10→20s capped at `MAX_RETRIES_429=3`.
- `cover.call_ollama` returns `""` on any failure (network or non-200); `cover.letter_ok` validates 400–1500 chars, no placeholders, no HTML; on failure `fallback_letter` produces a deterministic template letter.
- Exit codes: `0` success, `2` auth/config fatal, `3` fetch fatal (all keywords failed → `RuntimeError`).
- `store.save(vac)` is called **before** sheets export so a Sheets/Telegram failure never loses the source of truth.

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
