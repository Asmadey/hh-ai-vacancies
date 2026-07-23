# Codebase Concerns

**Analysis Date:** 2026-07-22

## Tech Debt

**Two parallel, diverging code paths (monolith vs modular pipeline):**
- Issue: `scripts/hh_ai_vacancies.py` (900-line standalone scraper) and the `src/` package implement the same pipeline twice with duplicated constants, filters, and resume text. Behavior drift is already visible (monolith uses MarkdownV2 Telegram reports; `src/` uses HTML; monolith reads `~/.hermes/skills/.../resume-short.md`, `src/cover.py` hardcodes the resume). `CLAUDE.md` documents this as intentional during a cutover, but until `docs/DEPLOY.md` Step 4 runs, both are "active" and any filter/keyword fix must be applied in two places.
- Files: `scripts/hh_ai_vacancies.py`, `src/config.py`, `src/cover.py`, `src/fetch.py`
- Impact: Bug fixes silently missed in one path; reviewers cannot know which is canonical without reading `CLAUDE.md`.
- Fix approach: Complete the `docs/DEPLOY.md` Step 4 cutover (pause+remove old cron `99a55e0f5ac4`, create from `config/cron.yaml`), then delete `scripts/hh_ai_vacancies.py` or reduce it to a thin shim. Until then, treat `src/` as canonical for new behavior and mirror filter/keyword changes into the monolith.

**Duplicated constants and regex across both paths:**
- Issue: `KEYWORDS`, `JUNK_RE`, `RESUME_RE`, `ARCHIVE_RE`, `HH_USER_AGENT`, `SPREADSHEET_ID`, `SHEET_GID`, `SHEET_NAME`, `SHEET_URL`, and the env-loader (`_load_hermes_env` vs `config.load_env_file`) are copy-pasted verbatim between `scripts/hh_ai_vacancies.py:41-100` and `src/config.py:50-104`.
- Files: `scripts/hh_ai_vacancies.py:41-100`, `src/config.py:50-104`
- Impact: A regex tuned in one file is stale in the other; archive-filter incidents (per `references/archive-filter-incident-2026-06-27.md`) can recur in the path that wasn't patched.
- Fix approach: After cutover, delete the monolith. While both live, any change to `src/config.py` regexes/keywords MUST be mirrored to the monolith and vice versa.

**Hardcoded resume text inside the module:**
- Issue: `src/cover.py:11-30` embeds the full candidate resume as a module-level string constant. The monolith loads it from `~/.hermes/skills/hh-cover-letters/references/resume-short.md` (`scripts/hh_ai_vacancies.py:60`). Editing the resume requires editing source code and redeploying.
- Files: `src/cover.py:11-30`, `scripts/hh_ai_vacancies.py:60`
- Impact: Resume content drift between the two paths; no way to update resume without a code change.
- Fix approach: Load resume from a path (e.g. `config.RESUME_PATH` env or `data/resume.md`) in `src/cover.py`, with the current string kept only as a fallback default.

**Module-level side effects on import:**
- Issue: `src/config.py:21` calls `load_env_file()` at import time, mutating `os.environ` for any process that imports `src.config`. This runs even in tests unless `home` fixture clears relevant vars. The env loader uses `if key not in os.environ` (no-overwrite) so real env wins, but import order matters: any module imported before `src.config` that reads an env var gets the pre-load value.
- Files: `src/config.py:5-21`, `scripts/hh_ai_vacancies.py:20-36`
- Impact: Subtle ordering bugs; tests that don't use the `home` fixture inherit the host's `~/.hermes/.env`.
- Fix approach: Acceptable for a single-process cron job, but document the import-order constraint. Consider lazy loading (read env inside accessor functions) if the package is ever used as a library.

## Known Bugs

**No pagination — fetch silently caps at 50 results per keyword:**
- Symptoms: `src/fetch.py:94` hardcodes `"per_page": 50, "page": 0` and never advances the page cursor. The monolith does the same (`scripts/hh_ai_vacancies.py:725`). `found_total` is recorded from `data["found"]` but only the first 50 items are ever inspected.
- Files: `src/fetch.py:87-121`, `scripts/hh_ai_vacancies.py:420-425, 725`
- Trigger: Any keyword with >50 matching vacancies (HH reports `found` in the thousands for broad terms like "Product Director").
- Workaround: None — vacancies beyond page 0 are invisible to the pipeline. Mitigated only by the 13-keyword spread, but each keyword still caps at 50.
- Fix approach: Loop `page` from 0 while `len(items) == per_page` (and `page * per_page < found`, with a sane ceiling like 5 pages). Add a test in `tests/test_fetch_enrich.py` asserting multi-page fetch.

**`telegram._send` prints the full report text to stdout on every call:**
- Symptoms: `src/telegram.py:14` does `print(text)` unconditionally before the HTTP POST. The cron job is configured `deliver: origin` (`config/cron.yaml:5`), so stdout is itself a delivery channel — this is intentional, but it means every alert and the full run report (including any embedded vacancy content) lands in Hermes logs.
- Files: `src/telegram.py:12-27`, `config/cron.yaml:5`
- Trigger: Every pipeline run.
- Workaround: Acceptable for this project; flagged because stdout now carries report content that is also sent to Telegram.
- Fix approach: Leave as-is (intentional per `config/cron.yaml`), but ensure `telegram.esc()` is always applied to dynamic content before printing (currently alerts pass raw `str(e)` through `telegram.esc`, which is correct).

**`sheets_export.export` clear-then-write leaves an empty-sheet window:**
- Symptoms: `src/sheets_export.py:67-83` issues `:clear` on `A:K`, then writes in 200-row batches. If a write batch fails after the clear, the sheet is left empty (data lost from the visualization layer only — `vacancies.json` is the source of truth and is safe).
- Files: `src/sheets_export.py:66-84`
- Trigger: Sheets API 5xx or network blip between the clear and a write batch.
- Workaround: Re-run the pipeline; `vacancies.json` is unaffected so the next run rebuilds the sheet.
- Fix approach: Write to a scratch range (e.g. `HH_AI_staging`) then swap, or use `batchUpdate` with `updateCells` in a single call. Low priority since Sheets is visualization-only by design.

## Security Considerations

**OTP delivered via world-readable `/tmp` file:**
- Risk: `scripts/hh_token_updater.py:84-96` polls `/tmp/hh_otp.txt` for the HH login OTP. `/tmp` is world-readable on most Unix hosts; any local user can read (or race to delete) the OTP. The file is deleted after read (`otp_file.unlink()`), but the window exists.
- Files: `scripts/hh_token_updater.py:82-96`
- Current mitigation: 5-minute deadline; file deleted on success.
- Recommendations: Use `~/.hermes/.hh_otp` with `0600` perms, or pipe OTP via stdin / an env var set by the operator.

**Playwright automation logs credentials to stdout:**
- Risk: `scripts/hh_token_updater.py` reads `HH_ADMIN_PASSWORD` from env and types it into the page (`email_input.fill(email)`, password fill). Playwright `fill()` does not log values, but the script's own `print(...)` calls and Hermes stdout capture could leak if a future debug line is added. The token is written back to `~/.hermes/.env` in plaintext (`update_env_token`).
- Files: `scripts/hh_token_updater.py:65-79, 99-150`
- Current mitigation: `CLAUDE.md` rule "Never print secrets"; password is never printed today.
- Recommendations: Keep the no-print discipline; consider writing the new token via `re.sub` on the env file (per `CLAUDE.md` Hermes note) rather than full rewrite, to avoid clobbering other keys.

**Google OAuth refresh token stored as plaintext JSON:**
- Risk: `src/sheets_export.py:14-26` reads `~/.config/gws/credentials.json` containing `client_id`, `client_secret`, and `refresh_token`, and POSTs them to `oauth2.googleapis.com/token` over HTTPS. The file has no documented permission requirement.
- Files: `src/sheets_export.py:14-26`, `src/config.py:61`
- Current mitigation: Host is a private Hermes cron box.
- Recommendations: Ensure `~/.config/gws/credentials.json` is `0600`; document the expected perms in `docs/DEPLOY.md`.

**Hardcoded identity in source:**
- Risk: `src/config.py:50` and `scripts/hh_ai_vacancies.py:44` hardcode the operator email (`sagestaf@gmail.com`) in `HH_USER_AGENT`, and `SPREADSHEET_ID`/`SHEET_GID` are hardcoded constants (`src/config.py:57-58`). These are not secrets, but they couple the code to one operator and one sheet.
- Files: `src/config.py:50-60`, `scripts/hh_ai_vacancies.py:44-58`
- Current mitigation: None.
- Recommendations: Move `HH_USER_AGENT` email, `SPREADSHEET_ID`, `SHEET_GID` to env vars with the current values as defaults, so the code is operator-portable without edits.

**No TLS certificate verification override, but urllib default is used:**
- Risk: `src/http_client.py:35` calls `urllib.request.urlopen` with the default SSL context, which verifies certs. Good. However there is no `verify=` anywhere — confirm nobody is tempted to add `ssl._create_unverified_context`. (No instance found; flagging as a guard rail.)
- Files: `src/http_client.py:31-40`
- Current mitigation: Default urllib behavior verifies certs.
- Recommendations: None — keep defaults.

## Performance Bottlenecks

**Sequential fetch and enrich across 13 keywords / N new vacancies:**
- Problem: `src/fetch.py:fetch_all` loops 13 keywords with serial HTTP calls (`auth.api_request` one at a time). `src/enrich.py:enrich_new` then does one `GET /vacancies/{id}` per new ID serially. A run with many new IDs is latency-bound by HH API RTT.
- Files: `src/fetch.py:92-121`, `src/enrich.py:62-69`
- Cause: No concurrency in fetch/enrich (only `cover.generate_all` uses `ThreadPoolExecutor`).
- Improvement path: Use `ThreadPoolExecutor` for the 13 keyword fetches (respect HH rate limits) and for `enrich_new` with a bounded worker count (e.g. 4-6). Add rate-limit handling on 429 for these read endpoints (currently only `apply.py` handles 429).

**Unbounded `vacancies.json` growth:**
- Problem: `src/store.py:load` reads the entire JSON into memory and `store.save` rewrites it whole each run. `apply.select_candidates` iterates the full store every run. There is no pruning — `vacancies.json` grows monotonically as new IDs accumulate over months/years.
- Files: `src/store.py:84-104`, `src/apply.py:146-161`
- Cause: No GC / archival policy; records are never removed, only added and status-updated.
- Improvement path: Add an archival pass (e.g. move records with `first_seen` older than 90 days and `status == STATUS_SENT` to `data/vacancies_archive.json`). Cap `vacancies.json` to recently-active records.

**Full-sheet rewrite every run:**
- Problem: `src/sheets_export.py:export` clears `A:K` and rewrites every row each run, even when only a handful of new vacancies arrived. For a sheet with thousands of rows this is many 200-row batch API calls.
- Files: `src/sheets_export.py:56-84`
- Cause: Design choice ("Sheets is visualization-only; full rewrite keeps it == vacancies.json").
- Improvement path: Acceptable while the sheet is small. If row count grows, switch to diff-based updates (append new rows, update changed cells) or split active vs archive tabs.

## Fragile Areas

**Single-use refresh token — partial-failure data loss:**
- Files: `src/auth.py:25-65`
- Why fragile: `auth.refresh` POSTs the refresh_token, then `save_tokens` writes the new pair atomically (temp + `os.replace`). If the process is killed between the HH response and the `save_tokens` call, the old refresh_token is already consumed (single-use) and the new pair is lost — forcing a full re-OAuth. `auth.save_tokens` does NOT keep a `.bak` of the old token file (unlike `store.save` which does).
- Safe modification: Add a `shutil.copy2(path, path + ".bak")` before writing in `auth.save_tokens`, mirroring `store.save`. Never call `refresh` without immediately saving.
- Test coverage: `tests/test_auth.py` covers refresh success/failure but not the kill-window.

**`http_client.request` swallows JSON decode errors silently:**
- Files: `src/http_client.py:13-24`
- Why fragile: `HttpResponse.json()` returns `{}` on any decode error; `HttpResponse.text` returns `""` on decode error. Callers like `auth._is_auth_error` (`src/auth.py:68-72`) and `apply._negotiation_error` (`src/apply.py:32-38`) iterate `resp.json().get("errors", [])` — a malformed body silently looks like "no errors", masking real failures.
- Safe modification: When adding a new caller, never assume `resp.json()` reflects the real body on non-2xx; check `resp.status` first. Consider logging when `json()` falls back to `{}`.
- Test coverage: No test asserts behavior on a non-JSON 4xx/5xx body.

**`cover.clean_letter` regex-driven post-processing:**
- Files: `src/cover.py:96-111`
- Why fragile: The letter cleaning is a stack of regex substitutions with no spec; small changes to the Ollama output format can produce empty or malformed letters. `letter_ok` (`src/cover.py:125-133`) is the guard, but the fallback (`fallback_letter`) is hardcoded and generic — a regression in `clean_letter` that passes `letter_ok` but produces weird text would not be caught.
- Safe modification: Touch `clean_letter` only with a paired test in `tests/test_cover.py`. Run `python3 -m evals.rate_cover_letters --sample 5` after any change (per `CLAUDE.md`).
- Test coverage: `tests/test_cover.py` has 5 tests; coverage of the `clean_letter` edge cases is thin.

**Filter regex polarity (`JUNK_RE`, `ARCHIVE_RE`):**
- Files: `src/config.py:89-104`, `src/fetch.py:37-49`
- Why fragile: `is_active` returns `not ARCHIVE_RE.search(...)` and `is_relevant` uses `JUNK_RE.search(title)` to reject. `CLAUDE.md` explicitly flags "Junk-title filter polarity" as a past incident cause — reversing the polarity adds junk instead of removing it.
- Safe modification: Any change to these regexes must be mirrored in `scripts/hh_ai_vacancies.py` and verified with `tests/test_fetch_enrich.py` cases for both positive and negative polarity.
- Test coverage: `tests/test_fetch_enrich.py` (7 tests) covers some filter cases; add explicit tests for each regex on reject and accept samples.

## Scaling Limits

**`vacancies.json` in-memory load:**
- Current capacity: Fine for hundreds-to-low-thousands of records.
- Limit: A single `json.load` of the whole file at `src/store.py:84`; memory and parse time grow linearly. Tens of thousands of records will start to matter on a small cron host.
- Scaling path: Archive old records (see Performance section); consider `sqlite` if the store ever needs indexing beyond `vacancy_id` key lookup.

**HH API rate limits (undocumented per-endpoint):**
- Current capacity: 13 keyword fetches + N enrich + M applies per run, with `APPLY_PAUSE_SEC=5` between negotiations.
- Limit: `apply.py` handles 429 with backoff (5/10/20s, max 3 retries) and `BatchStop` on `limit_exceeded`, but fetch/enrich have no 429 handling — a rate-limited fetch keyword is counted as an "error" and only raises if ALL 13 fail (`src/fetch.py:119`).
- Scaling path: Add 429 backoff to `fetch`/`enrich` via `http_client`; reduce `COVER_LETTER_WORKERS` if Ollama rate-limits.

## Dependencies at Risk

**Ollama Cloud endpoint default looks wrong:**
- Risk: `src/config.py:71` defaults `OLLAMA_BASE_URL` to `https://ollama.com/v1` and `OLLAMA_MODEL` to `deepseek-v4-flash`. The Ollama Cloud API is OpenAI-compatible at `/chat/completions` (`src/cover.py:82`), but `ollama.com` is the marketing site, not the API host. If the env var is unset, `call_ollama` will fail silently and every letter falls back to the template.
- Impact: Silent degradation to fallback letters; no alert fires because `call_ollama` only prints to stderr on non-200.
- Migration plan: Confirm the real Ollama Cloud base URL and set it as the default in `src/config.py:71`, or make a missing `OLLAMA_BASE_URL`/`OLLAMA_API_KEY` a hard error in non-dry runs (alert via Telegram).

**No third-party deps, but stdlib-only constraint is load-bearing:**
- Risk: The "stdlib only, no `requests`" rule (`CLAUDE.md`) means every HTTP feature must be hand-rolled on `urllib`. Adding retry, connection pooling, or HTTP/2 would require re-implementing them. The constraint is intentional for the cron host but limits future features.
- Impact: Any contributor reaching for `requests`/`httpx` breaks the deployment model.
- Migration plan: Keep stdlib-only; document the rationale in `CONVENTIONS.md` so new contributors don't import deps.

## Missing Critical Features

**No structured logging:**
- Problem: All diagnostics are `print(..., file=sys.stderr)` with ad-hoc prefixes (`[pipeline]`, `[fetch]`, `[apply]`, `[cover]`). There is no log level, no timestamp, no structured fields. Hermes captures stdout/stderr but grepping is the only way to diagnose.
- Blocks: Fast incident triage; the `references/` incident logs are essentially hand-transcribed from stderr.
- Fix approach: Adopt `logging` with a named logger per module and a JSON formatter; keep stderr as the handler. Low effort, high payoff.

**No test coverage for the monolith or the token updater:**
- Problem: `tests/` covers only `src/`. `scripts/hh_ai_vacancies.py` (900 lines) and `scripts/hh_token_updater.py` (384 lines, Playwright-driven) have zero tests. The monolith is still the live cron job until cutover.
- Blocks: Safe refactoring or deletion of the monolith; confidence in the token renewal flow.
- Fix approach: Post-cutover, delete the monolith. For the token updater, add a smoke test that mocks Playwright (`page` fixture) for `log_in` and asserts `update_env_token` writes correctly.

**No CI pipeline:**
- Problem: No `.github/`, no `Makefile` test target, no CI config detected. Tests run only manually (`python3 -m pytest`). `pytest` is not even installed in the default venv (`No module named pytest` when run here).
- Blocks: Regression prevention; PR validation.
- Fix approach: Add a minimal GitHub Actions (or Hermes-equivalent) workflow running `python3 -m pytest` and `python3 evals/check_metrics.py` on push. Pin `pytest` in a `requirements-dev.txt`.

## Test Coverage Gaps

**`src/http_client.py` non-JSON / non-UTF8 bodies:**
- What's not tested: `HttpResponse.json()` returning `{}` and `.text` returning `""` on malformed bodies; callers that rely on `.json()["errors"]` then see an empty list.
- Files: `src/http_client.py:13-24`, `src/auth.py:68-72`, `src/apply.py:32-38`
- Risk: A 500 with an HTML error page is treated as "no errors found" by `_negotiation_error`, falling through to `_set_status(..., f"http_{resp.status}")` — which is the right outcome by accident, not by design.
- Priority: Medium.

**Kill-window between token refresh and save:**
- What's not tested: Process interruption between `auth.refresh` receiving the new pair and `auth.save_tokens` completing.
- Files: `src/auth.py:35-65`
- Risk: Single-use refresh_token lost; full re-OAuth required. No `.bak` of the old token file.
- Priority: High (operational impact is severe and silent).

**Fetch pagination (the bug above):**
- What's not tested: Any keyword returning >50 results.
- Files: `src/fetch.py:92-121`
- Risk: Vacancies beyond page 0 are silently dropped every run.
- Priority: High.

**`scripts/hh_ai_vacancies.py` and `scripts/hh_token_updater.py`:**
- What's not tested: The entire monolith and the token renewal flow.
- Files: `scripts/hh_ai_vacancies.py`, `scripts/hh_token_updater.py`
- Risk: The still-active cron job is untested; the token renewal that the pipeline depends on is untested.
- Priority: High for the monolith until cutover; Medium for the token updater (manual, low frequency).

**Committed coverage artifacts:**
- What's not tested/gated: `.coverage` and `.coverage.claude.pid6.XUHQFoex.H4TbcHdcaO3h` (53 KB each) are committed to the repo root and are NOT in `.gitignore`.
- Files: `.coverage`, `.coverage.claude.pid6.XUHQFoex.H4TbcHdcaO3h`, `.gitignore`
- Risk: Repo bloat; potential PII leak via coverage data; confusing diffs.
- Priority: Low. Fix: add `.coverage*` to `.gitignore` and `git rm` the committed files.

---

*Concerns audit: 2026-07-22*