# Testing Patterns

**Analysis Date:** 2026-07-22

## Test Framework

**Runner:**
- `pytest` (version not pinned — no `requirements.txt` / `pyproject.toml`; pytest is the only dev dependency).
- No config file. No `pytest.ini`, `setup.cfg`, `pyproject.toml [tool.pytest]`, or `conftest.py` at repo root. Settings come from defaults + `tests/conftest.py` fixtures.
- `tests/conftest.py` is the single fixture/harness file (~117 lines).

**Assertion Library:**
- Plain `assert` statements throughout. No `unittest` TestCase classes, no `pytest.raises` helper beyond exception assertions. No third-party assertion libs.

**Run Commands:**
```bash
python3 -m pytest                       # Run all tests (53 cases across tests/)
python3 -m pytest tests/test_apply.py    # Single file
python3 -m pytest tests/test_apply.py::test_429_backoff_respects_retry_after  # Single test
python3 -m pytest -x                    # Stop on first failure
python3 -m pytest -k dry_run             # Filter by keyword
python3 -m pytest -q                     # Quiet
```
No watch mode, no coverage CLI configured (a `.coverage` file exists from a past run but there is no `coverage` config or `pytest-cov` invocation in docs).

**Test count:** 53 pytest cases per `CLAUDE.md`, spread across 8 test files (`tests/test_apply.py` 12, `tests/test_auth.py` 7, `tests/test_cover.py` 5, `tests/test_cron_config.py` 2, `tests/test_fetch_enrich.py` 7, `tests/test_pipeline_e2e.py` 5, `tests/test_sheets_telegram.py` 6, `tests/test_store.py` 8 — counts as written).

## Test File Organization

**Location:** separate `tests/` directory at repo root (tests are NOT co-located with `src/` modules). One test file per `src/` module + one E2E file:
- `tests/test_apply.py` ↔ `src/apply.py`
- `tests/test_auth.py` ↔ `src/auth.py`
- `tests/test_cover.py` ↔ `src/cover.py`
- `tests/test_fetch_enrich.py` ↔ `src/fetch.py` + `src/enrich.py`
- `tests/test_store.py` ↔ `src/store.py`
- `tests/test_sheets_telegram.py` ↔ `src/sheets_export.py` + `src/telegram.py`
- `tests/test_cron_config.py` ↔ `config/cron.yaml` + `src/pipeline.py` import smoke
- `tests/test_pipeline_e2e.py` ↔ `src/pipeline.py` (full `run()` integration)
- `tests/conftest.py` — shared fixtures and helpers
- `tests/__init__.py` — empty (makes `tests` a package so `from tests.conftest import ...` works)

**Naming:**
- Files: `tests/test_<module_under_test>.py`.
- Functions: `test_<behavior>` in `snake_case`, often starting with the subject (`test_apply_...`, `test_enrich_...`, `test_429_...`, `test_dry_run_...`, `test_e2e_...`).
- Russian words appear in test names where the behavior is Russian-status-bound: `test_limit_exceeded_stops_batch`, `test_test_required_status`, `test_already_applied_counts_as_sent`.

**Structure:**
```
tests/
├── __init__.py
├── conftest.py             # fixtures: home, mock_http, no_sleep, tg_capture, tokens_file
│                            # helpers: make_resp, search_item, vacancy_details, MockHttp
├── test_apply.py            # apply statuses, backoff, batch, dry_run, select
├── test_auth.py             # token refresh loop, 403-oauth retry, alerts
├── test_cover.py            # letter_ok bounds, clean_letter, fallback, parallel
├── test_cron_config.py      # cron.yaml exists & points to pipeline (smoke)
├── test_fetch_enrich.py    # filters, dedup, enrichment, archived
├── test_pipeline_e2e.py     # full DRY_RUN run, idempotency, migration, evals
├── test_sheets_telegram.py  # rows == JSON, no-back-read invariant, report numbers
└── test_store.py            # schema validation, merge idempotency, migration
```

## Test Structure

**Suite organization:** flat module-level `def test_*` functions. No `class` grouping. Test order in a file follows the test-case ID order documented in the module docstring.

**Test docstrings** reference the formal test case IDs from the spec (`docs/`-implied TC-NN):
```python
def test_apply_success_message_is_cover_letter(home, mock_http, no_sleep):
    """TC-10: message == cover_letter записи; статус отправлено; applied_at выставлен."""
```
`tests/test_apply.py` opens with `"""TC-10, TC-11, TC-12: отклики, статусы, backoff, паузы."""` — each test then maps to a TC. Follow this convention for new tests: cite the TC ID in the function docstring.

**Standard test shape:**
```python
def test_X(home, mock_http, no_sleep):
    rec = _rec()                                          # build minimal record
    mock_http.add("/negotiations", make_resp(201, b""))   # queue response(s)
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))  # call SUT
    assert rec["status"] == config.STATUS_SENT            # assert on state + calls
    assert mock_http.calls_to("/negotiations")[0]["data"]  # assert HTTP shape
```

**Setup/teardown:** no explicit setup/teardown functions. Isolation comes from fixtures (`home` sets `HH_PIPELINE_HOME` to a `tmp_path`, so every `data/` write lands in a temp dir; `mock_http` swaps the HTTP entry point; `no_sleep` patches `time.sleep`). `tmp_path` and `monkeypatch` are pytest built-ins — no manual cleanup needed.

## Mocking

**Framework:** `monkeypatch` (pytest built-in). No `unittest.mock`, no `mocker` fixture, no `responses`/`httpretty`. Everything is hand-rolled in `tests/conftest.py`.

**The central mock — `MockHttp`** (`tests/conftest.py:MockHttp`):
- A callable that replaces `http_client.request`. Installed by the `mock_http` fixture: `monkeypatch.setattr(http_client, "request", mock)`.
- FIFO queue of `(url_substring, response_or_exception)` pairs. Each call pops the first matching entry by substring (`substr in url`). An unmatched URL raises `AssertionError("Unexpected HTTP call: ...")` — so a missing mock surfaces loudly.
- Records every call in `mock.calls` as `{"method", "url", "headers", "data"}`. Inspect with `mock.calls_to("/negotiations")`.
- To queue an exception (network down): `mock_http.add("/negotiations", http_client.NetworkError("conn refused"))`.

**Response builder — `make_resp(status, body=None, headers=None)`** (`tests/conftest.py:make_resp`):
- Wraps `http_client.HttpResponse`. Accepts a `dict`/`list` (JSON-encoded) or raw bytes.
- Use for every HTTP response in tests: `make_resp(200, {"items": [...]})`, `make_resp(201, b"")`, `make_resp(403, {"errors": [...]})`.

**Fixtures** (all in `tests/conftest.py`):
- `home` — sets `HH_PIPELINE_HOME=<tmp_path>`, `DRY_RUN=1`, `HH_RESUME_ID=resume-42`, `APPLY_LIMIT=0`, clears `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `OLLAMA_API_KEY`. **Almost every test depends on `home`** — it is the isolation boundary.
- `mock_http` — installs `MockHttp` as `http_client.request`. Returns the mock instance.
- `no_sleep` — patches `src.apply.time.sleep` to record into a list; returns the list so tests assert `any(s >= 7 for s in no_sleep)`. Only needed for `apply` tests.
- `tg_capture` — patches `src.telegram._send` to capture text without sending; returns the list of sent messages. Assert `any("auth failure" in t for t in tg_capture)`.
- `tokens_file` — writes the `TOKENS` dict (`tests/conftest.py:TOKENS`) to `<home>/data/hh_tokens.json` and returns the path. Depends on `home`. Required for any test that exercises `auth.load_tokens`.

**Fixture builders** (module-level helpers in `tests/conftest.py`, imported into test files):
- `search_item(vid="100", name="AI Product Manager", **kw)` — builds an HH `/vacancies` search result item.
- `vacancy_details(vid="100", **kw)` — builds an HH `/vacancies/{id}` detail response (with `archived=False` default).
- `TOKENS` — the canonical token dict `{"access_token": "AT1", "refresh_token": "RT1", "expires_in": 1209600, "obtained_at": "..."}`.

**Per-file helpers** (private, prefixed `_`): each test file declares its own minimal builders — `_rec(vid, letter)` in `tests/test_apply.py`, `_vac(n)` and `_rec` in `tests/test_sheets_telegram.py` / `tests/test_store.py`, `_add_search_responses` / `_mock_full_run` in fetch/pipeline tests. Reuse `tests/conftest.py` builders first; add a local `_helper` only when the test file needs something narrower.

**What to mock:**
- All HTTP calls — via `mock_http`. There is no live network in tests by design.
- `time.sleep` in `apply` — via `no_sleep` (so backoff tests don't actually wait).
- `telegram._send` — via `tg_capture` (so alert/report tests don't hit Telegram).
- `config.LEGACY_SEEN_PATH` — via `monkeypatch.setattr(config, "LEGACY_SEEN_PATH", "/nonexistent/...")` to skip migration in non-migration tests.

**What NOT to mock:**
- `store.load` / `store.save` / `store.validate_record` — these run against the real `data/` dir (redirected to `tmp_path` by `home`). Tests verify real file I/O.
- `config.dry_run()` / `config.apply_limit()` — read from the real env set by `home`. Override with `monkeypatch.setenv(...)` if a test needs a different value.
- The pipeline itself (`pipeline.run()`) in E2E tests — exercise it end-to-end with mocked HTTP only.

## Fixtures and Factories

**Test data:**
```python
# Token fixture data (tests/conftest.py)
TOKENS = {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 1209600,
          "obtained_at": "2026-07-01T00:00:00+00:00"}

# HH search item (tests/conftest.py:search_item)
search_item("100", "AI Product Manager", company="Acme AI", area="Москва",
            salary={"from": 300000, "currency": "RUR"},
            requirement="Опыт запуска AI продуктов")

# HH vacancy details (tests/conftest.py:vacancy_details)
vacancy_details("100", name="AI Product Manager", archived=True,
                description="<p>Ищем <b>AI Product Manager</b>...</p>")

# Apply test record (tests/test_apply.py:_rec)
def _rec(vid="100", letter="Здравствуйте!\n\nПисьмо.\n\nБуду рад созвону."):
    r = store.new_record(vid, f"https://hh.ru/vacancy/{vid}", f"AI Lead {vid}")
    r["cover_letter"] = letter
    return r
```

**Location:** shared builders live in `tests/conftest.py`; file-local `_rec`/`_vac`/`_add_search_responses` helpers live in the test file that uses them. No `tests/fixtures/` directory, no JSON fixture files, no `factory_boy`.

**Factory conventions:**
- Defaults are realistic HH-shaped data (Moscow, RUR, full-time, remote).
- `**kw` overrides — every builder accepts keyword overrides for the fields that vary between tests (`archived=`, `name=`, `company=`, `salary=`).
- IDs are string ints (`"100"`, `"1"`, `"2"`) — `vacancy_id` is always a string in the store.

## Coverage

**Requirements:** None enforced. No `pytest-cov`, no coverage gate in CI, no threshold in `CLAUDE.md` or `SKILL.md`. A stale `.coverage` file exists at repo root but there is no `coverage` config and no documented coverage command.

**View Coverage:** not configured. If needed:
```bash
python3 -m pytest --cov=src --cov-report=term-missing
```
(but `pytest-cov` is not listed as installed — would need to be added.)

**Implicit coverage target:** `CLAUDE.md` says "Tests are 53 pytest cases across `tests/`" — the bar is "every stage module has a test file with happy + error paths", not a percentage. The E2E test (`tests/test_pipeline_e2e.py:test_e2e_dry_run_exit_0`) is the integration backstop.

## Test Types

**Unit tests:** per-module, one `test_<module>.py` per `src/` module. Each unit test exercises one function with mocked HTTP and isolated `data/`. State assertions (`rec["status"]`, `rec["status_reason"]`) + HTTP shape assertions (`mock_http.calls_to(...)`). Examples: `test_apply_success_message_is_cover_letter`, `test_enrich_fills_structured_fields`, `test_refresh_success_saves_new_pair`.

**Integration tests:** `tests/test_pipeline_e2e.py` — calls `pipeline.run()` against a fully-mocked HTTP surface, then asserts on the real `data/vacancies.json` + `data/last_run_report.json`. Covers: happy path (exit 0), idempotency (second run = 0 new), migration (`seen.json` pulled in on first run), missing-tokens fatal (exit 2 + alert), and the `evals/check_metrics.py` goal check (`check_metrics.check()` returns `(metrics, 0)`).

**E2E / system tests:** Not used. There is no live-network test and no test that writes to a real Google Sheet / Telegram / HH. The `no-back-read` invariant (`tests/test_sheets_telegram.py:test_no_module_reads_sheets`) is a static-analysis test that greps `src/*.py` for `sheets.googleapis` to prove only `sheets_export.py` touches Sheets.

**Eval tests:** `evals/check_metrics.py:check()` is invoked from `tests/test_pipeline_e2e.py:test_check_metrics_goal_reached` — the deterministic goal checker is itself covered by a unit test. `evals/rate_cover_letters.py` (LLM rubric) is NOT tested — it requires a live Ollama key.

## Common Patterns

**Async / threading:** no `asyncio` in tests. The pipeline's `ThreadPoolExecutor` (cover letters) is exercised in `test_generate_all_covers_100pct` without any special async harness — `generate_all` runs synchronously via `as_completed` and the test just awaits the return.

**Exception testing:**
```python
def test_limit_exceeded_stops_batch(home, mock_http, no_sleep):
    rec = _rec()
    mock_http.add("/negotiations", neg_403("limit_exceeded"))
    with pytest.raises(apply_mod.BatchStop):
        apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_NOT_SENT
    assert rec["status_reason"] == "limit_exceeded"
```
Use `pytest.raises(DomainException)` and then assert on the post-exception state (status/reason set before raise). For network-down: `pytest.raises(http_client.NetworkError)` is queued via `mock_http.add(url, http_client.NetworkError("..."))`.

**Status / reason assertion pattern:**
```python
assert rec["status"] in config.VALID_STATUSES          # status enum check
assert rec["status_reason"] == "limit_exceeded"        # exact reason
assert all(v["status"] in config.VALID_STATUSES for v in vac.values())  # 100% with status
```
The `evals/check_metrics.py` criteria (status_100pct, duplicates_zero, enrichment_ge_95, covers_100pct, sheets_eq_json, telegram_delivered) are mirrored as test assertions in the E2E file.

**Idempotency pattern:**
```python
# first run
assert pipeline.run() == 0
# second run with same search responses
assert pipeline.run() == 0
report = json.load(open(config.run_report_path()))
assert report["new"] == 0 and report["duplicates"] == 0
```
(`tests/test_pipeline_e2e.py:test_e2e_second_run_idempotent`.)

**DRY_RUN assertion:** dry-run paths must make zero HTTP calls to the side-effecting endpoint:
```python
m, _ = apply_mod.apply_batch(vac, ["1"], "resume-42", dict(TOKENS), dry_run=True)
assert mock_http.calls == []
assert vac["1"]["status_reason"] == "dry_run"
```

**Env override:** `monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")` / `monkeypatch.setattr(config, "LEGACY_SEEN_PATH", "...")`. Always go through `monkeypatch`, never `os.environ[...] = ...` directly (it leaks across tests).

**Stdout/stderr capture:** `capsys.readouterr().out` for the Hermes `deliver: origin` channel (the pipeline prints `DRY_RUN=...` and the report to stderr; `telegram._send` prints the report to stdout). Assert `"DRY_RUN" in out`.

**Importing the SUT:** tests import as `from src import apply as apply_mod` (alias to avoid shadowing the `apply` builtin) and `from src import config, http_client, store`. Helpers come from `from tests.conftest import TOKENS, make_resp, search_item, vacancy_details`.

---

*Testing analysis: 2026-07-22*