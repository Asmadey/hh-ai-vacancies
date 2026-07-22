# Coding Conventions

**Analysis Date:** 2026-07-22

## Language & Dependency Policy

**Python stdlib only** in the `src/` pipeline. Do not add `requests`, `httpx`, or any
third-party runtime dep — the project deliberately has no `requirements.txt` /
`pyproject.toml`. Permitted stdlib modules: `urllib.request`, `urllib.parse`,
`urllib.error`, `json`, `re`, `os`, `sys`, `time`, `shutil`, `html`,
`concurrent.futures`, `datetime`, `threading`. The only dev dependency is `pytest`
(for tests). `evals/` and `scripts/` follow the same rule.

Rationale (documented in `CLAUDE.md`): cron host has no venv pip install step;
stdlib-only guarantees the pipeline runs on a bare `python3`.

## Naming Patterns

**Files:**
- `src/` modules: single-word lowercase, one stage per file — `fetch.py`, `enrich.py`, `cover.py`, `apply.py`, `store.py`, `auth.py`, `telegram.py`, `sheets_export.py`, `http_client.py`, `pipeline.py`, `config.py`.
- `snake_case` for multiword: `sheets_export.py`, `http_client.py`.
- Tests: `tests/test_<module>.py` mirroring the `src/` module under test — `tests/test_apply.py` ↔ `src/apply.py`. E2E tests: `tests/test_pipeline_e2e.py`.
- Scripts: `scripts/<verb>_<noun>.py` — `hh_ai_vacancies.py`, `hh_token_updater.py`, `migrate_seen.py`.
- Evals: `evals/<verb>_<noun>.py` — `check_metrics.py`, `rate_cover_letters.py`.

**Functions:**
- `snake_case` everywhere: `apply_one`, `enrich_record`, `fetch_all`, `generate_for_record`, `vacancy_id_from_url`, `parse_level`, `match_reason`, `format_salary`.
- Internal helpers prefixed with `_`: `_post_negotiation`, `_negotiation_error`, `_set_status`, `_is_auth_error`, `_work_format`, `_sheets_url`, `_send`, `_add_search_responses` (test helper), `_mock_full_run` (test helper), `_vac` / `_rec` (test fixture builders).
- Public entry points are the unprefixed names: `apply_one`, `apply_batch`, `select_candidates`, `enrich_new`, `fetch_all`, `generate_all`, `generate_for_record`, `merge`, `load`, `save`, `run` (orchestrator).

**Variables:**
- `snake_case` for locals: `new_ids`, `found_total`, `seen_ids`, `retry_after`, `tokens_path`.
- Single-letter loop counters `i`, `n` are acceptable.
- Module-level dicts keyed by id: `store` / `vac` / `store_dict` (the `vacancies.json` object keyed by `vacancy_id`); records are `rec`.

**Constants:**
- `UPPER_SNAKE_CASE` at module top: `JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`, `VACANCY_ID_RE`, `PLACEHOLDER_RE`, `TAG_RE`, `MAX_RETRIES_429`, `NEGOTIATIONS_URL`, `TOKEN_URL`, `CLOSING`, `COLUMNS`, `COVER_LETTER_MAX_TOKENS`, `COVER_LETTER_TEMP`, `COVER_LETTER_WORKERS`, `KEYWORDS`, `STATUS_SENT`, `STATUS_NOT_SENT`, `STATUS_TEST`, `VALID_STATUSES`, `LEGACY_SEEN_PATH`, `HH_API`, `HH_USER_AGENT`, `SPREADSHEET_ID`, `SHEET_GID`, `SHEET_NAME`, `SHEET_URL`.
- Regex patterns use the `_RE` suffix and are `re.compile`-d at module load (not inline).

**Types:**
- No type hints anywhere in `src/`. Do not add them piecemeal — the codebase is intentionally hint-free for brevity.
- The `SCHEMA` dict in `src/store.py` is the de-facto type spec: `{field: (python_type, required_bool)}`. `validate_record()` enforces it.
- Domain status values are Russian string constants (`"отправлено"` / `"не отправлено"` / `"тест"`) — never inline string literals; reference `config.STATUS_*`.

## Module Structure

Every `src/` module follows this layout (see `src/apply.py`, `src/enrich.py`, `src/cover.py`):

1. **Module docstring** — triple-quoted, first line gives the pipeline step number and purpose, often in Russian. Example: `"""Step 6: POST /negotiations. Статусы: отправлено | не отправлено | тест."""`
2. **Stdlib imports** (alphabetical): `import json`, `import os`, `import re`, `import sys`, `import time`, `import urllib.parse`.
3. **Relative imports** — `from . import auth, config, http_client, telegram` or `from .store import now_iso`. Relative only; never `import src.X` inside the package.
4. **Module-level constants** (regex, URLs, limits).
5. **Exception classes** if any (`class BatchStop(Exception)`, `class AuthError(Exception)`, `class NetworkError(Exception)`).
6. **Private `_helpers`**.
7. **Public functions**.
8. **No `if __name__ == "__main__"` in stage modules** — only `src/pipeline.py` and standalone scripts/evals have it.

`src/pipeline.py:run()` is the single orchestrator entry point; it returns an exit code (`0`/`2`/`3`) and `sys.exit(run())` is in the `__main__` block.

## Import Organization

**Order (observed in every `src/` file):**
1. stdlib (`json`, `os`, `re`, `sys`, `time`, `urllib.parse`, `concurrent.futures`)
2. blank line
3. relative package imports (`from . import auth, config, http_client, telegram`)
4. blank line
5. (in tests/evals) `from tests.conftest import TOKENS, make_resp, search_item` etc., guarded by `# noqa: E402` when a `sys.path.insert` precedes it.

**Path manipulation:** tests and evals insert the repo root with
`sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
before importing `src`. Mark the following import with `# noqa: E402`.

**No path aliases** (no `pyproject.toml`, no `PYTHONPATH` config). Always import as `from src import X` from outside the package and `from . import X` inside it.

## Single HTTP Entry Point

**Every HTTP call goes through `src/http_client.request(method, url, headers=..., data=..., timeout=...)`** (`src/http_client.py`). It returns an `HttpResponse` for any HTTP status (4xx/5xx do NOT raise); only DNS/timeout/connection failures raise `http_client.NetworkError`.

If you add a module that makes HTTP calls, route them through `http_client.request` or they will bypass the test mock harness (`tests/conftest.py:MockHttp` monkeypatches `http_client.request`).

HH API calls go one layer higher through `auth.api_request(method, url, tokens, data=..., headers=..., tokens_path=...)` (`src/auth.py`), which attaches `Authorization: Bearer ...` + `User-Agent` and handles the 403-oauth refresh-once loop. Use `api_request` for HH endpoints, raw `http_client.request` for Telegram/Google/Ollama.

**Mandatory header:** `User-Agent: config.HH_USER_AGENT` on every HH request or HH returns `400 bad_user_agent`.

## Error Handling

**Strategy:** return `HttpResponse` for HTTP statuses (no raise on 4xx/5xx); raise domain exceptions for business halts; let `pipeline.run()` catch at stage boundaries.

**Domain exceptions** (each in its own module):
- `src/http_client.py:NetworkError` — DNS/timeout/connection. Means "API down".
- `src/auth.py:AuthError` — token load/refresh failure. Fatal → exit 2 + Telegram alert.
- `src/apply.py:BatchStop(reason)` — halts the apply batch, defers remaining candidates to next run. `reason` is one of: `api_down`, `limit_exceeded`, `resume_not_found`, `captcha`. Carries `.reason` attribute.

**Patterns:**
- Stage-level try/except in `src/pipeline.py:run()` — catch `auth.AuthError` → `store.save(vac)` then `return 2`; catch `RuntimeError` (fetch all-keywords-down) → Telegram alert + `return 3`; catch bare `Exception` around `sheets_export.export` → log to stderr, alert, set `sheets_rows = -1` (non-fatal — Sheets is visualization-only).
- Retry loop with attempt counter: `apply_one` retries 429 up to `MAX_RETRIES_429` (3), backoff from `Retry-After` header or exponential `5 * 2**(retries-1)`.
- Refresh-once: `auth.api_request` retries exactly once after a successful token refresh (the `_retried` flag param); a second 403-oauth is fatal.
- `_set_status(rec, status, reason="")` is the single mutator for record status — always sets `status`, `status_reason`, `updated_at`, and conditionally `applied_at`. Use it instead of assigning fields directly.
- `store.validate_record(rec)` returns a list of problem strings (`"missing:status"`, `"type:field"`, `"bad_status:..."`); empty list = valid. Tests assert `== []` for valid records.
- `cover.letter_ok(text)` returns bool (400–1500 chars, no placeholders/HTML) — gate fallback letters through it.

**Anti-pattern to avoid:** do not raise on 4xx/5xx HTTP statuses. `http_client.request` deliberately returns `HttpResponse` for them so the caller can branch on `resp.status`. Raise `NetworkError` only for transport failures.

## Atomic File Writes

Files that lose data on crash use the **temp + `os.replace`** pattern:
- `src/store.py:save()` — also copies the previous version to `path + ".bak"` first (`shutil.copy2`).
- `src/auth.py:save_tokens()` — temp + `os.replace` (refresh_token is single-use; losing the pair means re-running OAuth).

New atomic writes must follow the same shape:
```python
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(obj, fh, ensure_ascii=False, indent=2)
os.replace(tmp, path)
```

Always pass `ensure_ascii=False, indent=2` to `json.dump` — the data is Russian and must be human-readable in the file.

## Logging & Output

**`print(text)` to stdout** is reserved for the Hermes `deliver: origin` channel — `telegram._send` prints the full report/alert to stdout so the cron host can forward it to Telegram. Do not print debug noise to stdout.

**`print(msg, file=sys.stderr)`** is the logging channel. Convention: prefix with the module/stage tag — `[pipeline]`, `[fetch]`, `[enrich]`, `[cover]`, `[apply]`. Examples in `src/pipeline.py`, `src/fetch.py:103`, `src/enrich.py:34`, `src/apply.py:129`.

**No logging framework.** No `logging` module usage. stderr print + Telegram alerts (for fatal) is the whole observability story.

**Secrets:** never print tokens, passwords, or `Authorization` headers. Replace with `[REDACTED]`. The `Authorization` header is set from `tokens["access_token"]` in `auth.api_request` and never logged.

## Telegram / HTML

**Telegram messages always use `parse_mode=HTML`** (`src/telegram.py`). Dynamic content must be escaped with `telegram.esc()` (which wraps `html.escape(text, quote=False)`). Never use Markdown — the dispatcher does not set `parse_mode=Markdown` and `[text](url)` / `**bold**` render as raw text (documented incident in `CLAUDE.md`).

Job titles in reports must be clickable `<a href="vacancy_url">` links. Use emoji prefixes for visual scan: `🔍 Найдено`, `🆕 Новых`, `✉️ Cover letters`, `🚀 Отправлено`, `📝 С тестами`, `🔗 <a href>Открыть таблицу</a>`.

Alerts (sent via `telegram.send_alert`) are prefixed with `🚨` (fatal) or `⚠️` (warning).

## Comments & Docstrings

**Module docstrings:** every `src/` module has a triple-quoted docstring as the first statement, giving the step number and a one-line purpose. Mix of Russian and English is normal — Russian for business/domain descriptions (`src/store.py`, `src/apply.py`), English for generic mechanics (`src/http_client.py`).

**Function docstrings:** short, present on public entry points. Russian imperative: `"""Returns tokens. Sets rec status. Raises BatchStop when batch must halt."""` (`src/apply.py:apply_one`). English for helpers.

**Inline comments:** sparse, only for non-obvious business rules. Examples: `# остальные — «не отправлено», перенос на следующий прогон` (`src/apply.py:131`), `# мигрированный не попадает в кандидаты на отклик` (`tests/test_pipeline_e2e.py:89`). No section dividers in `src/` (the monolith `scripts/hh_ai_vacancies.py` uses `# ---` banner comments; do not copy that style into `src/`).

**No JSDoc/TSDoc** (Python project). No type annotations.

## Function Design

**Size:** most `src/` functions are 10–40 lines. The largest is `apply_one` (~50 lines) because of the error-status branch table — that's the ceiling; split anything bigger.

**Parameters:** public functions take the data they operate on as the first arg (`store_dict`, `rec`, `candidate_ids`) plus a `tokens` and optional `tokens_path=None` for anything that calls HH. Optional knobs come last with defaults: `dry_run=None`, `limit=None`, `pause=None` — resolved from `config.*` inside the function when `None`.

**Return values:**
- Functions that call HH return `(resp, tokens)` tuples (tokens may be refreshed mid-call) — `auth.api_request`, `_post_negotiation`, `fetch_all`, `enrich_record`, `enrich_new`.
- `apply_batch` returns `(metrics_dict, tokens)`.
- `pipeline.run()` returns an exit code int (`0`/`2`/`3`).
- `store.merge` returns `list[new_vacancy_ids]`; `store.duplicates` returns `list[keys]`; `store.validate_record` returns `list[str]` (empty = valid).
- `cover.letter_ok` returns `bool`; `sheets_export.export` returns row count or raises `RuntimeError`.

**Mutators:** `enrich_record`, `apply_one`, `_set_status`, `generate_for_record`, `merge` mutate the `rec`/`store_dict` in place AND return a value. Document this in the docstring ("Mutates rec in place. Returns (ok, tokens).").

## Module Design

**Exports:** no `__all__` anywhere. Public names are simply the non-underscore ones. `src/__init__.py` is empty — import submodules explicitly (`from src import apply`, not `from src import *`).

**Barrel files:** none. Import directly from the module that owns the symbol.

**One concern per module:** `src/apply.py` only does apply/negotiations; `src/cover.py` only does cover-letter generation; `src/store.py` only does persistence + schema. Do not add cross-stage logic to a stage module — put orchestration in `src/pipeline.py`.

**Config access:** read env vars through `src/config.py` accessors — `config.dry_run()`, `config.apply_limit()`, `config.resume_id()`, `config.ollama_api_key()`, `config.telegram_bot_token()`, `config.telegram_chat_id()`. Static values are module constants (`config.HH_API`, `config.HH_USER_AGENT`, `config.SPREADSHEET_ID`). Never call `os.environ.get` directly in a stage module — add an accessor to `config.py` instead.

**Test isolation knob:** `HH_PIPELINE_HOME` env var (read in `config.py`) overrides the `data/` directory root. All new path-bearing config must honor it.

## Parallelism

Use `concurrent.futures.ThreadPoolExecutor` with `as_completed` for I/O-bound fan-out. Pattern (from `src/cover.py:generate_all`):
```python
workers = max(1, min(config.COVER_LETTER_WORKERS, len(new_ids)))
with ThreadPoolExecutor(max_workers=workers) as exe:
    futures = {exe.submit(fn, arg): key for key in args}
    for fut in as_completed(futures):
        fut.result()
```
Cap workers to the task count (`min(...)`) to avoid idle threads.

---

*Convention analysis: 2026-07-22*