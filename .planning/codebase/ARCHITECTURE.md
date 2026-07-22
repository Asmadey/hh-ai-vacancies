<!-- refreshed: 2026-07-22 -->
# Architecture

**Analysis Date:** 2026-07-22

## System Overview

Autonomous cron pipeline that scrapes AI/PM vacancies from the HeadHunter API, persists them in a JSON store, generates cover letters via Ollama Cloud, auto-responds to selected vacancies via HH `/negotiations`, mirrors state to a Google Sheet, and reports to Telegram. Runs on a Hermes Agent cron host. Two coexisting code paths: an old monolith scraper (`scripts/hh_ai_vacancies.py`) and the new modular `src/` pipeline invoked as `python3 -m src.pipeline`.

```text
┌─────────────────────────────────────────────────────────────┐
│                   Hermes Cron Host (trigger)                │
│   `config/cron.yaml` → `python3 -m src.pipeline`            │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator  `src/pipeline.py:run()`                       │
│  (8 sequential stages, exit 0/2/3, writes last_run_report)   │
└──┬───────┬───────┬───────┬───────┬───────┬───────┬──────────┘
   │ 1     │ 2     │ 3     │ 4     │ 5     │ 6     │ 7/8
   ▼       ▼       ▼       ▼       ▼       ▼       ▼
┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────────┐
│ auth   ││ fetch  ││ store  ││ enrich ││ cover  ││ apply  ││ sheets_exp. │
│`auth.py`││`fetch.py`││`store.py`││`enrich.py`││`cover.py`││`apply.py`││`telegram.py`│
└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└─────┬──────┘
    │        │          │          │          │         │           │
    └────────┴──────────┴──────────┴──────────┴─────────┘           │
                  all HH/HTTP via single entrypoint                   │
                     `src/http_client.py:request()`                   │
                                                                      │
                                                                      ▼
                  ┌────────────────────────────────────────────────────────┐
   External      │ HH API (api.hh.ru) │ Ollama Cloud │ Google Sheets API    │
                  │ Telegram Bot API  │ Google OAuth2 (token refresh)      │
                  └────────────────────────────────────────────────────────┘
                             │
                             ▼
                  ┌────────────────────────────────────────────────────────┐
   State          │ `data/vacancies.json` (source of truth, keyed by id)     │
   (local files)  │ `data/hh_tokens.json` (user OAuth, atomic save)           │
                  │ `data/last_run_report.json` (evals input)                 │
                  │ `~/.hermes/.env`, `~/.config/gws/credentials.json`       │
                  └────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Orchestrator | Run 8 stages in order, write metrics, return exit code | `src/pipeline.py` |
| Auth | Load/refresh HH user OAuth tokens, one retry on 403 oauth | `src/auth.py` |
| Config | Env loading, path resolution (`HH_PIPELINE_HOME`), constants (keywords, regexes, statuses) | `src/config.py` |
| HTTP entrypoint | Single `urllib` wrapper returning `HttpResponse` for any status; raises `NetworkError` on connection failure | `src/http_client.py` |
| Fetch | `GET /vacancies` across `KEYWORDS`, apply junk/archive/relevance filters, classify level/match | `src/fetch.py` |
| Store | Source-of-truth `vacancies.json`: schema validation, atomic save with `.bak`, merge/dedup, legacy migration | `src/store.py` |
| Enrich | `GET /vacancies/{id}` full details on new IDs only | `src/enrich.py` |
| Cover | Ollama Cloud cover letters (parallelized), deterministic fallback, validation | `src/cover.py` |
| Apply | `POST /negotiations` with status mapping, rate-limit backoff, batch stop conditions | `src/apply.py` |
| Sheets export | Full clear+rewrite of `HH_AI` tab from `vacancies.json` (visualization only) | `src/sheets_export.py` |
| Telegram | `send_report`/`send_alert` with `parse_mode=HTML`; `_send` also prints to stdout (Hermes deliver: origin) | `src/telegram.py` |
| Eval — metrics | Deterministic goal check from `vacancies.json` + `last_run_report.json` | `evals/check_metrics.py` |
| Eval — rubric | Independent Ollama judge scoring cover letters (threshold ≥7/10) | `evals/rate_cover_letters.py` |
| Migration | One-shot legacy `seen.json` → `vacancies.json` | `scripts/migrate_seen.py` |
| Old monolith | Reference scraper (search → Sheets → Telegram only); uses app token | `scripts/hh_ai_vacancies.py` |
| Token updater | Playwright-based HH OAuth refresh for the old app-token scraper | `scripts/hh_token_updater.py` |

## Pattern Overview

**Overall:** Sequential single-process pipeline with functional stage modules; module-level shared state limited to in-memory `store` dict passed by reference through `run()`.

**Key Characteristics:**
- Stdlib-only HTTP via single `http_client.request` — no `requests`/third-party deps. Every module routes HTTP through it so tests can monkeypatch one symbol.
- Store-as-source-of-truth: `data/vacancies.json` is canonical; Sheets is write-only visualization; no module reads cell data back.
- Atomic file writes (temp + `os.replace`) for `vacancies.json` and `hh_tokens.json` because the HH `refresh_token` is single-use and losing the pair means re-running OAuth.
- Defensive fallbacks: cover letters fall back to a deterministic template if Ollama fails; Sheets/Telegram failures degrade to alerts without halting the pipeline.
- DRY_RUN defaults to `1` (safe — no real applies); live runs require explicit `DRY_RUN=0`.

## Layers

**Orchestration:**
- Purpose: Drive stage order, error handling, metrics, exit codes
- Location: `src/pipeline.py`
- Contains: `run()` orchestrator, `write_report()` helper
- Depends on: every stage module, `config`
- Used by: `python3 -m src.pipeline` (cron), `config/cron.yaml`

**Stage modules (domain logic):**
- Purpose: One self-contained concern per module (auth, fetch, enrich, cover, apply, sheets, telegram, store)
- Location: `src/<stage>.py`
- Contains: Pure functions operating on the `store` dict + `tokens` dict, returning `(result, tokens)` tuples where tokens may change via refresh
- Depends on: `config`, `http_client`, `auth.api_request` (for HH calls), `telegram.send_alert` (for fatal signals)
- Used by: `pipeline.run()`

**Infrastructure:**
- Purpose: Cross-cutting primitives (HTTP, config, paths, env loading)
- Location: `src/http_client.py`, `src/config.py`
- Contains: `request()`/`HttpResponse`/`NetworkError`; env loader, path/flag getters, constants
- Depends on: stdlib only
- Used by: all stage modules

**Evaluation / ops:**
- Purpose: Post-run goal check and LLM rubric; one-shot ops scripts
- Location: `evals/`, `scripts/`
- Contains: `check_metrics.py`, `rate_cover_letters.py`, `migrate_seen.py`, `hh_ai_vacancies.py`, `hh_token_updater.py`
- Depends on: `src.config`, `src.store`, `src.http_client`
- Used by: manual operator / Hermes cron (old monolith only)

## Data Flow

### Primary Request Path (pipeline run)

1. Hermes cron triggers `python3 -m src.pipeline` per `config/cron.yaml` (`src/pipeline.py:run()` L19).
2. `auth.load_tokens()` reads `data/hh_tokens.json` (`src/auth.py:17`); `AuthError` → Telegram alert + exit 2.
3. `store.load()` reads `data/vacancies.json`; if empty and `LEGACY_SEEN_PATH` exists, `store.migrate_seen()` runs (`src/pipeline.py:31-34`).
4. `fetch.fetch_all(tokens)` iterates `config.KEYWORDS`, calls `auth.api_request("GET", /vacancies?...)` per keyword, applies `is_active`/`is_relevant` filters, dedups within the run via `seen_ids` set (`src/fetch.py:87-121`).
5. `store.merge(vac, fetched)` adds only new IDs; existing records are field-refreshed (status/cover_letter/first_seen untouched) (`src/store.py:107-123`).
6. `enrich.enrich_new(vac, new_ids, tokens)` calls `GET /vacancies/{id}` for new IDs only, strips HTML, truncates description to 4000 chars, marks `enriched=True`; archived-between-fetch-and-enrich → status `не отправлено`/`archived` (`src/enrich.py:26-59`).
7. `cover.generate_all(vac, new_ids)` runs `ThreadPoolExecutor` (`COVER_LETTER_WORKERS`, default 10), calls Ollama `/chat/completions`, cleans output, validates `letter_ok` (400–1500 chars, no placeholders/HTML), falls back to `fallback_letter` (`src/cover.py:136-156`).
8. `apply.apply_batch(...)` for `select_candidates(vac, new_ids)` (new + retryable, cover-letter-required); `DRY_RUN=1` → status `не отправлено`/`dry_run`; live → `POST /negotiations`, status mapping per `docs/api-contract.md` §1, `BatchStop` on `limit_exceeded`/`resume_not_found`/`captcha_required`/5xx/network; 429 backoff `Retry-After` or 5→10→20s, max 3 (`src/apply.py:49-143`).
9. `store.save(vac)` is called **before** export so source of truth persists even if export fails (`src/pipeline.py:75`).
10. `sheets_export.export(vac)` clears `HH_AI!A:K`, writes header+rows in batches of 200 (Sheets API payload limit); 11 columns: `date|title|company|salary|location|level|url|match|cover-letter|respond|статус` (`src/sheets_export.py:56-84`).
11. `telegram.send_report(metrics)` + `write_report(metrics)` → `data/last_run_report.json` for `evals/check_metrics.py` (`src/pipeline.py:86-105`).
12. Exit: `0` success, `2` auth/config fatal, `3` fetch fatal.

### Token Refresh Flow

1. Any HH API call returns `403` with `errors[].type == "oauth"` → `_is_auth_error` true (`src/auth.py:68-72`).
2. `auth.api_request` calls `refresh()` once → `POST /token grant_type=refresh_token`, saves new pair atomically (`src/auth.py:35-65`).
3. Original request retried once with new access token.
4. Second `403 oauth` in a row → `AuthError` + Telegram alert, pipeline exits 2.
5. `invalid_grant / token not expired` → access still valid, reuse old tokens (no fail).

**State Management:**
- In-process only: a `store` dict (vacancy_id → record) mutated in place across stages and persisted by `store.save()`.
- `tokens` dict threaded through every HH call; replaced on refresh and returned upward.
- No long-lived in-memory state between runs — every run starts from `vacancies.json` on disk.

## Key Abstractions

**Vacancy record:**
- Purpose: Canonical unit of state; one per HH vacancy
- Examples: `src/store.py` (`SCHEMA`, `new_record`), `data/vacancies.json`
- Pattern: Dict validated against `SCHEMA` (field → (type, required)); status ∈ `config.VALID_STATUSES`; persisted keyed by `vacancy_id`

**HH API request wrapper:**
- Purpose: Bearer auth + auto-refresh-once-on-403-oauth + uniform `(resp, tokens)` return
- Examples: `src/auth.py:api_request`
- Pattern: Recursive single-retry with `_retried` flag; raises `AuthError` only when refresh fails or second 403 arrives

**HTTP client:**
- Purpose: One monkeypatchable network entrypoint for the whole test harness
- Examples: `src/http_client.py:request`
- Pattern: `urllib.request` wrapper returning `HttpResponse` for **any** HTTP status (never raises on 4xx/5xx); raises `NetworkError` only on connection failure. Tests swap `http_client.request` with `MockHttp` (FIFO URL-substring matcher) in `tests/conftest.py`.

**BatchStop signal:**
- Purpose: Halt apply batch on unrecoverable conditions, defer remainder to next run
- Examples: `src/apply.py:BatchStop`
- Pattern: Raised with `reason`; `apply_batch` catches it, marks remaining candidates `не отправлено`/`deferred_<reason>`, breaks the loop

**Status / status_reason:**
- Purpose: Idempotent retry semantics across runs
- Examples: `src/config.py` (`STATUS_SENT/NOT_SENT/TEST`, `VALID_STATUSES`), `src/apply.py:select_candidates` (`RETRYABLE` set)
- Pattern: `select_candidates` re-queues records whose `status_reason` is in `RETRYABLE` or starts with `deferred_`; `migrated`, `отправлено`, `тест` are never re-applied

## Entry Points

**New pipeline (primary):**
- Location: `src/pipeline.py:run()`; invoked as `python3 -m src.pipeline`
- Triggers: Hermes cron job defined in `config/cron.yaml` (`schedule: "0 9 */2 * *"`, `DRY_RUN: "0"`, `APPLY_LIMIT: "0"`)
- Responsibilities: Full 8-stage apply pipeline

**Old monolith (reference, still deployed as cron `99a55e0f5ac4`):**
- Location: `scripts/hh_ai_vacancies.py`
- Triggers: Hermes cron job `99a55e0f5ac4`, `no_agent: true`
- Responsibilities: Search → filter → dedup → Sheets → Telegram report only; uses `HH_APP_TOKEN`. Cutover plan in `docs/DEPLOY.md` Step 4 (pause+remove old, `cronjob create` from `config/cron.yaml`).

**Evals:**
- Location: `evals/check_metrics.py` (exit 0 = goal reached), `evals/rate_cover_letters.py` (rubric ≥7/10)
- Triggers: Manual post-run

**Migration:**
- Location: `scripts/migrate_seen.py` (`python3 -m scripts.migrate_seen`)
- Triggers: One-shot, manual

**Token updater (old scraper):**
- Location: `scripts/hh_token_updater.py` (Playwright; needs `xvfb-run -a` on headless hosts, OTP via `/tmp/hh_otp.txt`)
- Triggers: Manual, when old app token expires

## Architectural Constraints

- **Threading:** Single main thread for all stages except cover-letter generation, which uses `ThreadPoolExecutor` bounded by `COVER_LETTER_WORKERS` (default 10). No other concurrency. `time.sleep` is patched out in tests via the `no_sleep` fixture.
- **Global state:** None mutable at module import except env-loaded constants in `src/config.py` (loaded once at import via `load_env_file()`). `KEYWORDS`, `JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`, status constants are module-level.
- **Circular imports:** `auth` imports `telegram`; `telegram` imports `http_client`, `config` — no cycle. `fetch` imports `auth`, `config`, `store`; `enrich` imports `auth`, `config`, `fetch` (for `format_salary`), `store` — no cycle. `apply` imports `auth`, `config`, `http_client`, `telegram`, `store`.
- **HTTP indirection (mandatory):** Any new module that makes HTTP calls MUST route through `http_client.request`, otherwise it bypasses the `MockHttp` test harness and tests will raise `AssertionError: Unexpected HTTP call`.
- **Stdlib only (new pipeline):** No `requests` or third-party runtime deps. `pytest` is the only dev dep (no `requirements.txt`).
- **User-Agent mandatory:** All HH requests must set `config.HH_USER_AGENT` or HH returns `400 bad_user_agent`.
- **Atomic persistence required:** `vacancies.json` and `hh_tokens.json` must be written via temp+`os.replace` because the HH `refresh_token` is single-use — losing the access/refresh pair forces a full re-OAuth.
- **DRY_RUN safe default:** `DRY_RUN` defaults to `"1"`; live runs require explicit `DRY_RUN=0` and ideally `APPLY_LIMIT=2` on first run.
- **Telegram parse_mode:** Always `HTML`, never Markdown — dynamic content must be escaped with `telegram.esc` (`html.escape`); job titles must be `<a href>` links to the vacancy URL.

## Anti-Patterns

### Sheets read-back

**What happens:** Treating Google Sheets as a data source by reading cell values back into the pipeline.
**Why it's wrong:** `data/vacancies.json` is the single source of truth. Sheets is visualization-only — `sheets_export.py` does a full clear+rewrite each run, so any value read back would be stale or overwritten.
**Do this instead:** Read state only from `src/store.load()` (`data/vacancies.json`); write to Sheets via `src/sheets_export.py:export()` and never consume its output.

### Bypassing `http_client.request`

**What happens:** A new module calls `urllib.request.urlopen` (or `requests`) directly.
**Why it's wrong:** Tests monkeypatch `http_client.request` with `MockHttp`; a direct call makes a real network request, breaking isolation and raising `AssertionError` in the test harness.
**Do this instead:** Route every HTTP call through `src/http_client.request(method, url, headers, data, timeout)`, returning `HttpResponse` for any status.

### Reversing the junk-title filter polarity

**What happens:** Inverting `title_ok`/`is_relevant` so junk titles get added instead of removed.
**Why it's wrong:** `JUNK_RE` matches unwanted titles; the filter returns `True` when the title does NOT match. Reversing it admits data-entry/designer/developer roles into the report. This has caused a real incident (see `references/archive-filter-incident-2026-06-27.md`).
**Do this instead:** Keep `is_relevant` returning `False` when `JUNK_RE.search(title)` is truthy (`src/fetch.py:47`); add regression coverage in `tests/test_fetch_enrich.py`.

### Reporting archived vacancies as new

**What happens:** Skipping the `ARCHIVE_RE` filter before enrichment surfaces closed vacancies in the Telegram report.
**Why it's wrong:** The report claims "new" hits that are actually archived, wasting applies and misleading the operator.
**Do this instead:** Apply `is_active` (ARCHIVE_RE on `title + snippet`) before enrichment in `fetch.fetch_all` (`src/fetch.py:113`); re-check `data.archived` in `enrich_record` and set status `не отправлено`/`archived` (`src/enrich.py:55-58`).

### Non-atomic token writes

**What happens:** Writing `hh_tokens.json` in place without temp+rename.
**Why it's wrong:** The HH `refresh_token` is single-use. A crash between truncation and full write loses the access/refresh pair, forcing a manual re-OAuth.
**Do this instead:** Always use `auth.save_tokens` (temp + `os.replace`) (`src/auth.py:25-32`).

## Error Handling

**Strategy:** Defensive, fail-loud only for unrecoverable states (auth, config); degrade gracefully for non-critical sinks (Sheets, Telegram). Exit codes signal severity: `0` success, `2` auth/config fatal, `3` fetch fatal.

**Patterns:**
- `AuthError` raised from `auth.py` on fatal 403-oauth-after-refresh or unreachable token endpoint; caught in `pipeline.run()`, emits Telegram alert, returns exit 2.
- `BatchStop(reason)` in `apply.py` halts the apply loop; remaining candidates marked `deferred_<reason>` for next run; metrics still recorded.
- HTTP 429 handled inline with bounded exponential backoff (`Retry-After` or 5→10→20s, max 3) — no exception.
- 5xx / `NetworkError` from `http_client` → `BatchStop("api_down")` in apply; logged in fetch (`errors` counter, raises `RuntimeError` only if ALL keywords fail).
- `letter_ok` validation rejects LLM output outside 400–1500 chars or with placeholders/HTML → deterministic `fallback_letter`.
- Sheets/Telegram exceptions caught in `pipeline.run()`, alerted, and metric set to `-1`/`False` — pipeline still exits 0.

## Cross-Cutting Concerns

**Logging:** `print(..., file=sys.stderr)` with `[stage]` prefixes (e.g. `[pipeline] start`, `[fetch] 'kw' HTTP 400`, `[apply] batch stopped: reason`). `telegram._send` also prints the full message to stdout (Hermes `deliver: origin` echoes stdout to Telegram).

**Validation:** `store.validate_record` checks every record against `SCHEMA` (type + required) and `VALID_STATUSES`; `evals/check_metrics.py` enforces 100% valid records, 0 duplicates, ≥95% enrichment, 100% cover letters, `sheets_rows == len(JSON)`, `telegram_delivered`.

**Authentication:** User OAuth bearer token from `data/hh_tokens.json`, auto-refreshed once on `403 oauth`; `User-Agent` mandatory on all HH requests. Google Sheets uses OAuth2 refresh token in `~/.config/gws/credentials.json`. Telegram uses bot token from env. Secrets loaded from `~/.hermes/.env` via `config.load_env_file` (never overwrites existing env). **Never print secrets** — redact with `[REDACTED]`.

---

*Architecture analysis: 2026-07-22*