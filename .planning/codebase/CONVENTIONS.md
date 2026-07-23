# Coding Conventions

**Analysis Date:** 2026-07-22

Scope: application code under `hh-ai-vacancies/` (the `src/` package, `tests/`, `evals/`, `scripts/`). The repo root holds only `.claude/` config and the `hh-ai-vacancies/` app dir.

## Language & Runtime

- Python 3.10 (cache files: `*.cpython-310.pyc` across `src/__pycache__/`, `tests/__pycache__/`).
- **Stdlib only** for the `src/` pipeline — no `requests`, no third-party HTTP/JSON deps. HTTP is done via `urllib.request`/`urllib.error`/`urllib.parse` (see `hh-ai-vacancies/src/http_client.py`). Do not add third-party runtime dependencies; CLAUDE.md explicitly forbids it.
- `pytest` is the only test dependency (not pinned in a `requirements.txt` — none exists).

## Naming Patterns

**Files:**
- `src/` modules: single lowercase word, snake_case, one stage per file: `auth.py`, `fetch.py`, `store.py`, `enrich.py`, `cover.py`, `apply.py`, `sheets_export.py`, `telegram.py`, `http_client.py`, `config.py`, `pipeline.py`.
- Tests: `test_<module>.py` mirroring the module under test — `tests/test_apply.py` ↔ `src/apply.py`, `tests/test_fetch_enrich.py` covers `src/fetch.py` + `src/enrich.py`, `tests/test_sheets_telegram.py` covers `src/sheets_export.py` + `src/telegram.py`. `tests/test_pipeline_e2e.py` covers `src/pipeline.py` end-to-end.
- Evals: `evals/check_metrics.py`, `evals/rate_cover_letters.py` — verb-noun snake_case.
- Scripts: `scripts/hh_ai_vacancies.py`, `scripts/hh_token_updater.py`, `scripts/migrate_seen.py`.

**Functions:**
- snake_case: `apply_one`, `fetch_all`, `enrich_new`, `build_prompts`, `generate_for_record`, `select_candidates`, `vacancy_id_from_url`, `format_salary`, `parse_level`, `match_reason`, `record_to_row`, `build_rows`.
- Private helpers prefixed `_`: `_post_negotiation` (`hh-ai-vacancies/src/apply.py:21`), `_negotiation_error` (`src/apply.py:32`), `_set_status` (`src/apply.py:41`), `_is_auth_error` (`src/auth.py:68`), `_work_format` (`src/enrich.py:18`), `_send` (`src/telegram.py:12`), `_sheets_url` (`src/sheets_export.py:52`), `_rec`/`_vac` test helpers.
- Boolean predicates: `is_active`, `is_relevant` (`src/fetch.py:37,41`), `letter_ok` (`src/cover.py:125`), `dry_run` (`src/config.py:41`).

**Variables:**
- snake_case: `found_total`, `new_ids`, `seen_ids`, `candidate_ids`, `apply_metrics`.
- Module-level constants SCREAMING_SNAKE_CASE: `KEYWORDS`, `JUNK_RE`, `RESUME_RE`, `ARCHIVE_RE`, `SCHEMA`, `NEGOTIATIONS_URL`, `TOKEN_URL`, `MAX_RETRIES_429`, `COVER_LETTER_MAX_TOKENS`, `COVER_LETTER_WORKERS`, `RESUME`, `CLOSING`, `PLACEHOLDER_RE`, `COLUMNS`, `SPREADSHEET_ID`, `SHEET_GID`, `SHEET_NAME`, `SHEET_URL`, `HH_API`, `HH_USER_AGENT`, `STATUS_SENT`, `STATUS_NOT_SENT`, `STATUS_TEST`, `VALID_STATUSES`, `LEGACY_SEEN_PATH`, `TOKENS` (test fixture data in `tests/conftest.py:78`).
- Env-derived runtime values are accessed via accessor functions, not bare constants: `dry_run()`, `apply_limit()`, `resume_id()`, `ollama_api_key()`, `telegram_bot_token()`, `telegram_chat_id()`, `data_dir()`, `vacancies_path()`, `tokens_path()`, `run_report_path()` (all in `hh-ai-vacancies/src/config.py`). Follow this pattern for any new env-overridable setting so `HH_PIPELINE_HOME` / test monkeypatching works.

**Types:**
- No type hints anywhere in the codebase. Do not add them to match style — parameters and returns are documented in docstrings only.
- Schema declared as a dict literal: `SCHEMA` in `hh-ai-vacancies/src/store.py:12` maps field -> `(type, required)` tuple; `validate_record` (`src/store.py:67`) enforces it.
- Custom exceptions: `BatchStop` (`src/apply.py:14`, carries `.reason`), `AuthError` (`src/auth.py:13`), `NetworkError` (`src/http_client.py:27`). Subclass `Exception` directly; no shared base class.

## Code Style

**Formatting:**
- No formatter config (no `.flake8`, `pyproject.toml`, `setup.cfg`, `ruff.toml`, `.pre-commit-config.yaml` present). Style is enforced by review and pattern-matching.
- 4-space indentation; UTF-8 source; line lengths stay well under 100 generally but there is no hard limit.
- Strings: double quotes (`"..."`) for module docstrings and most literals; single quotes for `re.compile` raw strings (`r"\b(...)\b"`) and short inline literals. Prefer double quotes for new code.

**Linting:**
- None configured. `# noqa: E402` markers appear after `sys.path.insert` in `tests/conftest.py:8`, `evals/check_metrics.py:19`, `evals/rate_cover_letters.py:13` — replicate this when a module must manipulate `sys.path` before its first import.

**Shebangs:**
- `#!/usr/bin/env python3` on executables only: `evals/check_metrics.py:1`, `evals/rate_cover_letters.py:1`, `scripts/hh_token_updater.py`, `scripts/hh_ai_vacancies.py`. Library modules in `src/` have no shebang.

## Module Layout

Every `src/` module follows this structure (see `hh-ai-vacancies/src/apply.py` as the canonical example):

1. **Module docstring** — first line names the pipeline step and its purpose, often referencing the test-case ID and `docs/api-contract.md` section. Examples:
   - `src/apply.py:1`: `"""Step 6: POST /negotiations. Статусы: отправлено | не отправлено | тест. Полный маппинг ошибок — docs/api-contract.md §1."""`
   - `src/fetch.py:1`: `"""Step 2: GET /vacancies по 13 AI-ключам + фильтры junk/archive/relevance."""`
   - `src/store.py:1`: `"""data/vacancies.json — единый source of truth. Ключ: vacancy_id. Sheets НИКОГДА не читается — только пишется (sheets_export)."""`
2. stdlib imports.
3. intra-package imports (`from . import auth, config, http_client, telegram` — **relative**, not `from src.`).
4. Module-level constants (SCREAMING_SNAKE) and compiled regexes.
5. Custom exception classes (if any).
6. Private helpers (`_`-prefixed).
7. Public functions.
8. No `if __name__ == "__main__"` in `src/` modules except `src/pipeline.py:108` (`sys.exit(run())`).

Docstrings are written in Russian (project context is HH.ru, a Russian job board). Code identifiers stay English/Russian-mixed as needed (`STATUS_SENT = "отправлено"`). New modules should keep docstrings in Russian to match.

## Import Organization

**Order:**
1. stdlib (`json`, `os`, `re`, `sys`, `time`, `urllib.parse`, `urllib.request`, `urllib.error`, `shutil`, `datetime`, `concurrent.futures`).
2. intra-package relative imports (`from . import auth, config, http_client, telegram`).
3. intra-package named imports (`from .store import now_iso`, `from .fetch import format_salary`).
4. Test/eval imports: `import pytest` then `from src import ...` then `from tests.conftest import TOKENS, make_resp, search_item, vacancy_details` — see `hh-ai-vacancies/tests/test_apply.py:1-8`.

**Path manipulation:**
- `tests/conftest.py:7` and eval entrypoints insert the repo root onto `sys.path` before importing `src`:
  ```python
  sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  from src import http_client  # noqa: E402
  ```
  `src/` itself uses **relative imports** (`from . import ...`) so it also works as `python3 -m src.pipeline`.

**Path Aliases:**
- None. No package alias, no `pyproject.toml` `[tool.setuptools]` config. `src/` is a plain package (`src/__init__.py` is empty).

## Error Handling

**Strategy:** explicit status fields + typed exceptions; HTTP never raises on 4xx/5xx.

**Patterns:**
- `http_client.request()` (`hh-ai-vacancies/src/http_client.py:31`) returns an `HttpResponse` for **any** HTTP status (4xx/5xx included). Only DNS/timeout/connection failures raise `NetworkError`. Never raise on a non-2xx HTTP status — inspect `resp.status` and `resp.json()`.
- Records carry `status` + `status_reason` rather than throwing. `apply.py:_set_status` (`src/apply.py:41`) is the canonical mutation: sets `status`, `status_reason`, `updated_at`, and `applied_at` (only on `STATUS_SENT` and not `already_applied`).
- `BatchStop` (`src/apply.py:14`) halts a batch and defers remaining records with `status_reason = f"deferred_{reason}"` (`src/apply.py:133`). Always re-raise `AuthError`; always catch `BatchStop` in the batch loop.
- `apply_one` (`src/apply.py:49`) maps every HH error code to a status: `test_required` → `STATUS_TEST`, `already_applied` → `STATUS_SENT`/`already_applied`, `limit_exceeded`/`resume_not_found`/`captcha_required`/5xx → `STATUS_NOT_SENT` + `BatchStop`, 429 → backoff then retry then `rate_limited`.
- Auth refresh-once: `auth.api_request` (`src/auth.py:75`) auto-refreshes the OAuth token on `403 oauth` exactly once (`_retried` flag); second `403 oauth` → `AuthError` + Telegram alert. Always thread `tokens` through return values (`resp, tokens`) so refreshed tokens propagate.
- Atomic file writes for tokens and store: write to `path + ".tmp"`, then `os.replace(tmp, path)` — see `auth.save_tokens` (`src/auth.py:25`) and `store.save` (`src/store.py:95`). `store.save` also backs up the previous file to `path + ".bak"` first (`src/store.py:100`). Follow this temp+rename pattern for any new persisted state — `refresh_token` is single-use, losing the pair means re-running OAuth.
- Pipeline-level exit codes in `hh-ai-vacancies/src/pipeline.py:run()`: `0` success, `2` auth/config fatal, `3` fetch fatal. Always `store.save(vac)` before returning on a mid-stage failure (`src/pipeline.py:55,67,72,75`).
- Telegram alerts via `telegram.send_alert` on every fatal condition; wrap dynamic content with `telegram.esc` (= `html.escape(..., quote=False)`, `src/telegram.py:8`).

**Never print secrets.** Replace with `[REDACTED]` in reports/logs/alerts (CLAUDE.md rule).

## Logging

**Framework:** none — `print(..., file=sys.stderr)` for diagnostics, `print(...)` to stdout for the Hermes cron dispatcher (see `telegram._send` `src/telegram.py:14` which prints the report to stdout before POSTing).

**Patterns:**
- Stage progress lines: `print(f"[pipeline] start (DRY_RUN={dry})", file=sys.stderr)` (`src/pipeline.py:21`), `print(f"[fetch] '{kw}' HTTP {resp.status}", file=sys.stderr)` (`src/fetch.py:103`), `print(f"[enrich] {rec['vacancy_id']} HTTP {resp.status}", file=sys.stderr)` (`src/enrich.py:34`), `print(f"[cover] ollama HTTP {resp.status}", file=sys.stderr)` (`src/cover.py:90`), `print(f"[apply] batch stopped: {e.reason}", file=sys.stderr)` (`src/apply.py:129`).
- Tag prefix in square brackets identifies the stage: `[pipeline]`, `[fetch]`, `[enrich]`, `[cover]`, `[apply]`. Replicate this for new stages.
- Only `telegram._send` writes to stdout (the report payload). Everything else goes to stderr.

## Comments

**When to Comment:**
- Russian inline comments for non-obvious business rules: `src/store.py:96` `# бэкап = предыдущая версия`, `src/apply.py:131` `# остальные — «не отправлено», перенос на следующий прогон`, `src/pipeline.py:74` `# persist source of truth ДО экспорта`, `src/enrich.py:55` `# Вакансия ушла в архив между fetch и enrich`.
- English comments only for `# noqa` markers.
- No block comments; use inline `#` on their own line above the code they explain.

**JSDoc/TSDoc:**
- N/A (Python). Use triple-quoted module docstrings and function docstrings in Russian, terse (1-3 lines). Examples: `src/store.py:107-110` (`merge`), `src/apply.py:49-50` (`apply_one`), `src/store.py:67-68` (`validate_record`).

## Function Design

**Size:** Small, single-purpose. Most functions 5-30 lines; the largest (`pipeline.run` at `src/pipeline.py:19-105`, `apply.apply_one` at `src/apply.py:49-101`, `apply.apply_batch` at `src/apply.py:104-143`) stay under ~60 lines. If a function grows past that, extract helpers (see how `apply_one` delegates to `_post_negotiation`/`_negotiation_error`/`_set_status`).

**Parameters:** Use `**kw` for record builders that accept many optional fields — `store.new_record(vacancy_id, url, title, **kw)` (`src/store.py:49`) and `tests/conftest.py:search_item(vid, name, **kw)`, `vacancy_details(vid, **kw)`. Default `None` means "fall back to config": `apply_batch(..., dry_run=None, limit=None, pause=None)` resolves via `config.dry_run() if dry_run is None else dry_run` (`src/apply.py:108-110`). Replicate this pattern so callers can override per-call while the default still reads env.

**Return Values:**
- HTTP-calling functions return `(result, tokens)` tuples so refreshed tokens propagate: `auth.api_request` → `(resp, tokens)`, `enrich_record` → `(ok, tokens)`, `apply_one` → `tokens`, `apply_batch` → `(metrics, tokens)`, `fetch_all` → `(records, found_total, tokens)`.
- Status-bearing functions mutate the record in place AND return a small value: `enrich_record(rec, tokens)` mutates `rec` and returns `(ok, tokens)`; `apply_one(rec, ...)` mutates `rec` and returns `tokens`.
- `store.save` / `auth.save_tokens` return `None`. `cover.generate_for_record` returns the letter string.

## Module Design

**Exports:** No `__all__` declarations anywhere. Public = not `_`-prefixed. Modules expose their full public surface implicitly.

**Barrel Files:**
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

Tests and module docstrings reference test-case IDs (`TC-01` through `TC-14`) that map to the goal criteria in `evals/check_metrics.py` and `docs/`. Examples:
- `tests/test_pipeline_e2e.py:1` `"""TC-01, TC-04, TC-06, TC-12, evals: e2e DRY_RUN..."""`
- `tests/test_apply.py:1` `"""TC-10, TC-11, TC-12..."""`
- `tests/test_auth.py:1` `"""TC-02, TC-03..."""`
- `tests/test_store.py:1` `"""TC-04, TC-06, TC-07..."""`
- `tests/test_cover.py:1` `"""TC-09..."""`
- `tests/test_fetch_enrich.py:1` `"""...TC-08 enrichment."""`
- `tests/test_sheets_telegram.py:1` `"""TC-05, TC-13, TC-14."""`

When adding a test, tag the docstring with the relevant TC ID. When adding a stage, add TC IDs to `evals/check_metrics.py` criteria.

---

*Convention analysis: 2026-07-22*