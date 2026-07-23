# Testing Patterns

**Analysis Date:** 2026-07-22

Scope: tests under `hh-ai-vacancies/tests/`, evals under `hh-ai-vacancies/evals/`. The repo root holds only `.claude/` config and the `hh-ai-vacancies/` app dir.

## Test Framework

**Runner:**
- `pytest` (version not pinned; cache tags show `pytest-9.1.1`, `cpython-310`).
- No config file — no `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, or `conftest.py` at repo root. pytest runs on defaults.
- `tests/__init__.py` makes `tests/` an importable package so `from tests.conftest import ...` works (see `hh-ai-vacancies/tests/test_apply.py:8`).

**Assertion Library:**
- Plain `assert` statements throughout — no `unittest` asserts, no `assertpy`. `pytest.raises` for exception assertions.

**Run Commands:**
```bash
python3 -m pytest                                  # run all (53 cases)
python3 -m pytest tests/test_apply.py               # single file
python3 -m pytest tests/test_apply.py::test_429_backoff_respects_retry_after  # single test
python3 -m pytest -k cover                         # by keyword
python3 -m pytest --cov=src --cov-report=term-missing   # coverage (see Coverage below)
```

There is also a coverage artifact at `hh-ai-vacancies/.coverage` (53 KB) indicating coverage has been run, though no coverage config is committed.

## Test File Organization

**Location:**
- Tests live in `hh-ai-vacancies/tests/`, separate from `src/` (not co-located). Each test file mirrors one or two source modules.
- Eval scripts live in `hh-ai-vacancies/evals/` — these are runtime goal-checks invoked after a pipeline run, not part of the pytest suite (importable but not collected as tests).

**Naming:**
- `test_<module>.py` for module-focused tests: `test_apply.py`, `test_auth.py`, `test_store.py`, `test_cover.py`, `test_cron_config.py`.
- Composite names for cross-module coverage: `test_fetch_enrich.py` (`src/fetch.py` + `src/enrich.py`), `test_sheets_telegram.py` (`src/sheets_export.py` + `src/telegram.py`).
- End-to-end: `test_pipeline_e2e.py` (`src/pipeline.py` driving the whole flow).
- Fixtures + helpers: `conftest.py` only — no `helpers.py` or `utils.py`.

**Structure:**
```
hh-ai-vacancies/tests/
├── __init__.py            # empty, makes tests/ importable
├── conftest.py            # fixtures: home, mock_http, no_sleep, tg_capture, tokens_file; helpers make_resp/search_item/vacancy_details
├── test_apply.py          # TC-10, TC-11, TC-12 — apply statuses, backoff, batch
├── test_auth.py           # TC-02, TC-03 — refresh loop, alerts
├── test_cover.py          # TC-09 — letter bounds/cleaning, fallback, 100% generation
├── test_cron_config.py    # TC-01 — cron.yaml shape + pipeline.run importable
├── test_fetch_enrich.py   # fetch filters/dedup + TC-08 enrichment
├── test_pipeline_e2e.py   # TC-01, TC-04, TC-06, TC-12, evals — full DRY_RUN run
├── test_sheets_telegram.py # TC-05, TC-13, TC-14 — rows, no-read rule, report numbers
└── test_store.py          # TC-04, TC-06, TC-07 — schema, merge idempotency, migration
```

## Test Structure

**Suite Organization:**
```python
"""TC-10, TC-11, TC-12: отклики, статусы, backoff, паузы."""   # TC IDs in module docstring
import urllib.parse

import pytest

from src import apply as apply_mod
from src import config, http_client, store
from tests.conftest import TOKENS, make_resp


def _rec(vid="100", letter="..."):                              # private helper at top
    r = store.new_record(vid, f"https://hh.ru/vacancy/{vid}", f"AI Lead {vid}")
    r["cover_letter"] = letter
    return r


def test_apply_success_message_is_cover_letter(home, mock_http, no_sleep):
    """TC-10: message == cover_letter записи; статус отправлено; applied_at выставлен."""
    rec = _rec()
    mock_http.add("/negotiations", make_resp(201, b"", {"Location": "/negotiations/xyz"}))
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_SENT and rec["applied_at"]
```

(See `hh-ai-vacancies/tests/test_apply.py:1-29`.)

**Patterns:**
- **Setup:** via pytest fixtures (`home`, `mock_http`, `tokens_file`) — no `setUp`/`tearDown`, no class-based tests. Every test is a top-level function.
- **Teardown:** `tmp_path` + `monkeypatch` auto-cleaned by pytest; the `home` fixture (`tests/conftest.py:12`) sets `HH_PIPELINE_HOME` to a temp dir so all `data/` writes land there and clear Telegram/Ollama env. No manual teardown needed.
- **Assertion style:** plain `assert` with boolean composition: `assert rec["status"] == config.STATUS_SENT and rec["applied_at"]` (`tests/test_apply.py:26`). Multiple asserts per test are fine.
- **One concern per test:** tests are short (3-12 lines) and named `test_<behavior>_<condition>`: `test_429_backoff_respects_retry_after`, `test_limit_exceeded_stops_batch`, `test_batch_stop_defers_remaining`, `test_e2e_second_run_idempotent`.
- **Docstrings:** Russian, lead with the TC ID — `"""TC-10: message == cover_letter записи; статус отправлено; applied_at выставлен."""`. Match this for new tests.

## Mocking

**Framework:** `monkeypatch` (pytest built-in). No `unittest.mock`, no `pytest-mock` plugin.

**Patterns:**
- **Single HTTP entrypoint mocked.** All HTTP goes through `src.http_client.request`; tests monkeypatch that one function. The `MockHttp` class (`hh-ai-vacancies/tests/conftest.py:29-50`) is a callable FIFO queue matched by URL substring:
  ```python
  @pytest.fixture
  def mock_http(monkeypatch):
      mock = MockHttp()
      monkeypatch.setattr(http_client, "request", mock)
      return mock
  ```
  Usage in a test (`tests/test_apply.py:24`):
  ```python
  mock_http.add("/negotiations", make_resp(201, b"", {"Location": "/negotiations/xyz"}))
  apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
  assert mock_http.calls_to("/negotiations")[0]["data"]  # assert on recorded calls
  ```
- **Raising on unmatched calls.** `MockHttp.__call__` raises `AssertionError(f"Unexpected HTTP call: {method} {url}")` (`conftest.py:47`) when no queued substring matches — every live-network leak in tests fails loudly. Always route new HTTP through `http_client.request` or it bypasses this harness.
- **Simulating failures.** Queue an exception instance instead of a response: `mock_http.add("/negotiations", http_client.NetworkError("conn refused"))` (`tests/test_apply.py:53`) — `MockHttp` raises it on match (`conftest.py:44`).
- **Sleep patching.** `no_sleep` fixture (`conftest.py:60-66`) patches `time.sleep` in `src.apply` and records the requested delays into a list:
  ```python
  @pytest.fixture
  def no_sleep(monkeypatch):
      sleeps = []
      import src.apply as apply_mod
      monkeypatch.setattr(apply_mod.time, "sleep", lambda s: sleeps.append(s))
      return sleeps
  ```
  Tests assert on delays: `assert any(s >= 7 for s in no_sleep)` (`tests/test_apply.py:73`).
- **Telegram capture.** `tg_capture` (`conftest.py:69-75`) replaces `telegram._send` with a list-append lambda:
  ```python
  monkeypatch.setattr(telegram, "_send", lambda text: (sent.append(text), True)[1])
  ```
  Tests assert alerts fired: `assert any("auth failure" in t for t in tg_capture)` (`tests/test_auth.py:52`).
- **Config/env patching.** `monkeypatch.setenv` / `setattr` for `HH_PIPELINE_HOME`, `DRY_RUN`, `APPLY_LIMIT`, `LEGACY_SEEN_PATH` — see `tests/conftest.py:14-20` and `tests/test_pipeline_e2e.py:11` (`monkeypatch.setattr(config, "LEGACY_SEEN_PATH", "/nonexistent/seen.json")`).

**What to Mock:**
- `http_client.request` — for every HTTP call (HH API, Ollama, Telegram, Google Sheets token + write).
- `time.sleep` in `src.apply` (via `no_sleep`) — never let tests actually sleep.
- `telegram._send` (via `tg_capture`) — never send real Telegram messages from tests.
- `config.LEGACY_SEEN_PATH` — point at a tmp file or `/nonexistent` to control migration behavior.
- Env vars via `monkeypatch.setenv` / `delenv` — `HH_PIPELINE_HOME`, `DRY_RUN`, `TELEGRAM_BOT_TOKEN`, `OLLAMA_API_KEY`, `HH_RESUME_ID`, `APPLY_LIMIT`.

**What NOT to Mock:**
- `store` file I/O — let it write to the real filesystem under `HH_PIPELINE_HOME` (a temp dir). Tests assert by `store.load()` / `json.load(open(...))` against the real file (see `tests/test_store.py:25-31`, `tests/test_pipeline_e2e.py:26-35`).
- `config` accessors — call them for real after setting env; the `home` fixture primes the env so `config.dry_run()`, `config.vacancies_path()` resolve to temp-dir values.
- `cover` fallback logic — `test_cover.py` runs `generate_for_record` for real with no `OLLAMA_API_KEY` and asserts the deterministic fallback passes `letter_ok` (`tests/test_cover.py:34-39`).

## Fixtures and Factories

**Test Data (builders in `hh-ai-vacancies/tests/conftest.py`):**
```python
def make_resp(status, body=None, headers=None):
    raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else (body or b"")
    return http_client.HttpResponse(status, raw, headers or {})

def search_item(vid="100", name="AI Product Manager", **kw):
    return {"id": vid, "name": name, "alternate_url": f"https://hh.ru/vacancy/{vid}",
            "apply_alternate_url": f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}",
            "employer": {"name": kw.get("company", "Acme AI")},
            "area": {"name": kw.get("area", "Москва")},
            "salary": kw.get("salary"),
            "snippet": {"requirement": kw.get("requirement", "Опыт запуска AI продуктов")}}

def vacancy_details(vid="100", **kw):
    return {"id": vid, "name": kw.get("name", "AI Product Manager"),
            "alternate_url": f"https://hh.ru/vacancy/{vid}", /* ...full HH shape... */
            "archived": kw.get("archived", False)}
```
Use these for any new test that needs HH-shaped payloads — they encode the real HH `/vacancies` and `/vacancies/{id}` response shapes.

**Module-level fixture data:**
- `TOKENS` (`conftest.py:78`) — the canonical token dict (`access_token="AT1"`, `refresh_token="RT1"`, `expires_in=1209600`, `obtained_at="2026-07-01T00:00:00+00:00"`). Pass via `dict(TOKENS)` so tests don't mutate the shared constant (see `tests/test_apply.py:25`, `tests/test_auth.py:16`).

**Per-file helpers:** Each test file defines `_rec` / `_vac` / `_add_search_responses` at the top (e.g. `tests/test_apply.py:11`, `tests/test_sheets_telegram.py:8`, `tests/test_fetch_enrich.py:8`). Keep new file-local helpers private (`_`-prefixed) and at the top of the file.

**Location:**
- Shared: `hh-ai-vacancies/tests/conftest.py` (fixtures + builders + `TOKENS`).
- File-local: top of each `tests/test_*.py`.

## Coverage

**Requirements:** No enforced threshold. No `--cov-fail-under` config. Coverage artifact `hh-ai-vacancies/.coverage` (53 KB) exists from prior runs.

**View Coverage:**
```bash
python3 -m pytest --cov=src --cov-report=term-missing
```
(No `.coveragerc`; defaults apply.)

**Effective coverage by design:** every `src/` module has a paired `tests/test_*.py`, and the e2e test (`tests/test_pipeline_e2e.py:19`) exercises the full `src.pipeline.run()` path under DRY_RUN with mocked HTTP. The 53-test suite is tracked in `CLAUDE.md` ("Tests are 53 pytest cases").

## Test Types

**Unit Tests:**
- Module-scoped, one source module per test file. Use `mock_http` to stub HTTP and assert on in-memory record mutations + recorded calls. Examples: `tests/test_store.py` (pure dict/JSON, no HTTP), `tests/test_apply.py` (HTTP mocked, statuses asserted), `tests/test_cover.py` (no `OLLAMA_API_KEY` → deterministic fallback path), `tests/test_auth.py` (refresh + retry loop).

**Integration Tests:**
- `tests/test_pipeline_e2e.py` — drives `pipeline.run()` end-to-end with `_mock_full_run` (`tests/test_pipeline_e2e.py:10`) queueing search responses for every keyword + detail responses per item. Asserts exit code, persisted `vacancies.json`, `last_run_report.json`, and `evals.check_metrics.check()` returning `goal_reached`.
- `tests/test_sheets_telegram.py:test_no_module_reads_sheets` (`tests/test_sheets_telegram.py:36`) — a static source-grep assertion that no `src/` module other than `sheets_export.py` mentions `sheets.googleapis`. This is an architectural-invariant test, not a behavior test.

**E2E Tests:**
- The pytest e2e test is the closest to E2E and runs fully offline (all HTTP mocked). There is no live-network or browser-driven E2E suite in this project.

**Eval scripts (post-run checks, not pytest):**
- `hh-ai-vacancies/evals/check_metrics.py` — deterministic goal check reading `data/vacancies.json` + `data/last_run_report.json`; exit `0` when all criteria pass (`status_100pct`, `duplicates_zero`, `enrichment_ge_95`, `covers_100pct`, `sheets_eq_json`, `telegram_delivered`). Run after a pipeline run.
- `hh-ai-vacancies/evals/rate_cover_letters.py` — LLM rubric scorer (separate Ollama call, threshold avg ≥7 and ≥80% of letters ≥7). Run via `python3 -m evals.rate_cover_letters --sample 5`.

## Common Patterns

**Async Testing:**
- N/A — no `asyncio` in the codebase. The only concurrency is `concurrent.futures.ThreadPoolExecutor` in `src/cover.py:151`, exercised synchronously by `tests/test_cover.py:test_generate_all_covers_100pct` (`tests/test_cover.py:42-50`) which just calls `cover.generate_all` and asserts all three records got letters.

**Error Testing:**
```python
def test_limit_exceeded_stops_batch(home, mock_http, no_sleep):
    """TC-12: limit_exceeded → «не отправлено» + BatchStop."""
    rec = _rec()
    mock_http.add("/negotiations", neg_403("limit_exceeded"))
    with pytest.raises(apply_mod.BatchStop):
        apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_NOT_SENT
    assert rec["status_reason"] == "limit_exceeded"
```
(From `hh-ai-vacancies/tests/test_apply.py:40-47`.) Pattern: queue the error response, `pytest.raises(<specific exception>)`, then assert the status/reason fields the error handler should have set.

**HTTP-error helper:** `neg_403(value)` (`tests/test_apply.py:17`) wraps `make_resp(403, {"errors": [{"type": "negotiations", "value": value}]})` — reuse it for negotiation-error tests.

**Idempotency Testing:**
- `tests/test_store.py:test_merge_idempotent_no_duplicates` (`tests/test_store.py:34-42`) and `tests/test_pipeline_e2e.py:test_e2e_second_run_idempotent` (`tests/test_pipeline_e2e.py:40-55`) run the same input twice and assert `new == 0, duplicates == 0` on the second pass. Replicate this for any new dedup/merge logic.

**E2E mock setup helper:** `_mock_full_run(mock_http, monkeypatch, items)` (`tests/test_pipeline_e2e.py:10`) is the template for a full-pipeline test — it queues one keyword hit and `len(KEYWORDS)-1` empty responses, then a detail response per item. Copy this pattern for new e2e scenarios.

**Invariant tests (source-grep):**
```python
def test_no_module_reads_sheets(home):
    src_dir = os.path.join(...)
    offenders = []
    for path in glob.glob(os.path.join(src_dir, "*.py")):
        if os.path.basename(path) == "sheets_export.py":
            continue
        if "sheets.googleapis" in open(path, encoding="utf-8").read():
            offenders.append(os.path.basename(path))
    assert offenders == []
```
(From `hh-ai-vacancies/tests/test_sheets_telegram.py:36-45`.) Use this style to enforce architectural rules that are otherwise easy to violate silently.

## Test Isolation Guarantees

- `HH_PIPELINE_HOME` (set by `home` fixture) is the override knob for every `data/` path — `config.data_dir()` / `vacancies_path()` / `tokens_path()` / `run_report_path()` all read it (`hh-ai-vacancies/src/config.py:24-36`). Tests never touch the real `data/` dir.
- `DRY_RUN=1` is the default in `home` (`tests/conftest.py:15`) and in `config.dry_run()` (`src/config.py:42`). Live `apply` only happens in tests that explicitly pass `dry_run=False` (e.g. `tests/test_apply.py:89,99,108,118`).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `OLLAMA_API_KEY` are cleared in `home` so no test can leak a real message or a real Ollama call. Tests that need Telegram or Ollama mock them explicitly (via `tg_capture` / by leaving `OLLAMA_API_KEY` unset to hit the deterministic fallback).
- `tokens_file` fixture writes the canonical `TOKENS` dict to `data/hh_tokens.json` under the temp dir so `auth.load_tokens()` succeeds without real credentials.

## Commands Summary (from `hh-ai-vacancies/CLAUDE.md`)

```bash
python3 -m pytest                                       # all tests
python3 -m pytest tests/test_apply.py::test_name        # single test
python3 evals/check_metrics.py                          # goal check (exit 0 = goal)
python3 -m evals.rate_cover_letters --sample 5          # LLM rubric (≥7/10)
```

---

*Testing analysis: 2026-07-22*