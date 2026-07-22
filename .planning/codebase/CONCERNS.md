# Codebase Concerns

**Analysis Date:** 2026-07-22

## Tech Debt

**Two parallel implementations of the same pipeline:**
- Issue: `scripts/hh_ai_vacancies.py` (900-line monolith) and the `src/` package (`pipeline.py` + modules) duplicate nearly every concern — keywords, filters, salary formatting, cover-letter generation, Sheets export, Telegram reporting. Constants like `KEYWORDS`, `JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE`, `SPREADSHEET_ID`, `SHEET_GID`, `HH_USER_AGENT` are copy-pasted across `scripts/hh_ai_vacancies.py:70-108` and `src/config.py:50-104`. Filters (`parse_level`, `priority_and_match`/`match_reason`, `is_active`, `is_relevant`, `format_salary`) exist in both `scripts/hh_ai_vacancies.py:537-608` and `src/fetch.py:9-66`.
- Files: `scripts/hh_ai_vacancies.py`, `src/fetch.py`, `src/config.py`, `src/cover.py`, `src/sheets_export.py`
- Impact: A fix to filtering (e.g. the 2026-06-27 archive-filter incident, `references/archive-filter-incident-2026-06-27.md`) must be applied in two places; divergence is the likely failure mode. `CLAUDE.md` explicitly warns about this cutover state.
- Fix approach: Finish the `docs/DEPLOY.md` Step 4 cutover (pause+remove old cron `99a55e0f5ac4`, switch to `python3 -m src.pipeline`), then delete `scripts/hh_ai_vacancies.py` or reduce it to a thin shim. Until then, any filter/format change MUST be ported to both files.

**Resume hardcoded in two places:**
- Issue: Candidate resume text is embedded as a string literal in both `scripts/hh_ai_vacancies.py:114-153` and `src/cover.py:11-30`, and a longer version is loaded from `references/resume-short.md` in the monolith (`scripts/hh_ai_vacancies.py:60, load_resume()`). The `src/` pipeline ignores the file and only uses the inline copy.
- Files: `src/cover.py:11-30`, `scripts/hh_ai_vacancies.py:114-153`
- Impact: Resume edits require code changes; the two copies drift. Cover-letter prompts silently use stale resume text.
- Fix approach: Move resume to a single path under `data/` or `references/` loaded by `src/cover.py`; remove inline literal.

**`update_respond_column` lives only in the monolith:**
- Issue: `scripts/hh_ai_vacancies.py:825-874` backfills the `respond` (column J) `HYPERLINK` formula by reading column G and calling `hh_api` per row with `time.sleep(0.15)`. The new pipeline does a full sheet rewrite each run (`src/sheets_export.py:56-84`) and never reads Sheets back, so this helper has no equivalent in `src/` — but it still depends on the old scraper's `hh_api`/`get_sheet_values`/`batch_update_values` helpers.
- Files: `scripts/hh_ai_vacancies.py:825-894`
- Impact: After cutover this ad-hoc repair tool is orphaned and will stop working (its `hh_api` uses the app token, not the user OAuth token the new pipeline uses).
- Fix approach: Either delete after cutover (full rewrite makes J self-healing) or port to `src/` using `auth.api_request`.

**No `requirements.txt` / dependency manifest:**
- Issue: `CLAUDE.md` says "stdlib only" for `src/`, but `scripts/hh_token_updater.py:42` imports `playwright` (third-party) and tests require `pytest`. There is no `requirements.txt`, `pyproject.toml`, or `setup.py` in the repo. `.gitignore` references `.venv/` but none is pinned.
- Files: repo root (no manifest), `scripts/hh_token_updater.py:23-42`
- Impact: Reproducible installs are impossible; `playwright` and `pytest` versions are implicit. New contributors must guess.
- Fix approach: Add a minimal `requirements.txt` (`pytest`, `playwright`) or `pyproject.toml` pinning the two non-stdlib deps.

## Known Bugs

**`priority_and_match` substring false-positives on "ai":**
- Symptoms: Vacancies with the bare token "ai" anywhere in title/snippet (e.g. "available", "email", "chain", "detail") are classified as AI roles and assigned "AI + управленческая роль" / "AI-роль".
- Files: `src/fetch.py:24-29` (`match_reason`), `scripts/hh_ai_vacancies.py:552-562` (`priority_and_match`)
- Trigger: Any vacancy whose title/snippet contains the substring "ai" but not the word "ai" — the check is `if "ai" in text`, not a word-boundary regex. (The `has_ai` relevance check in `is_relevant` *does* use `\bai\b`, so relevance is fine, but the match-classification label is wrong.)
- Workaround: None; misclassification only affects the `match` label shown in Sheets/Telegram, not apply decisions.
- Fix approach: Replace `if "ai" in text` with `re.search(r"\bai\b", text)` in `match_reason`/`priority_and_match`.

**`telegram.send_alert` failures are silent:**
- Symptoms: `_send` returns `False` on `NetworkError` or missing token/chat_id, but every caller (`src/pipeline.py:27,42,55,65,82`, `src/apply.py:88,95`, `src/auth.py:86,94`) ignores the return value. If Telegram is down during an auth fatal, the operator sees no alert at all.
- Files: `src/telegram.py:12-27`, callers in `src/pipeline.py`, `src/apply.py`, `src/auth.py`
- Trigger: Network outage coinciding with an auth/apply failure.
- Workaround: Check `last_run_report.json` / stderr logs manually.
- Fix approach: Log alert-send failures to stderr at minimum; consider a retry or secondary channel.

**`format_salary` uses `,` thousands separator with no locale:**
- Symptoms: `f"от {salary['from']:,}"` produces `от 250,000` under most locales but `от 250 000` is the Russian convention; Sheets displays the comma verbatim.
- Files: `src/fetch.py:57-58`, `scripts/hh_ai_vacancies.py:525-526`
- Trigger: Any salary with a value ≥ 1000.
- Workaround: Cosmetic only.
- Fix approach: Use `f"{value:,}".replace(",", " ")` or a explicit `format(value, "d")` with manual grouping.

## Security Considerations

**Hardcoded PII and resource IDs in source:**
- Risk: Owner email (`sagestaf@gmail.com`) is baked into `HH_USER_AGENT` in `src/config.py:50` and `scripts/hh_ai_vacancies.py:44`. The Google Sheets `SPREADSHEET_ID` (`1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok`) and `SHEET_GID` (`1464494667`) are hardcoded in `src/config.py:57-58` and `scripts/hh_ai_vacancies.py:55-57`.
- Files: `src/config.py:50-60`, `scripts/hh_ai_vacancies.py:44-58`
- Current mitigation: Repo is private (per `CLAUDE.md`). `.gitignore` does not cover these literals.
- Recommendations: Move identifiers to env vars (`HH_USER_AGENT`, `HH_SPREADSHEET_ID`, `HH_SHEET_GID`) loaded from `~/.hermes/.env`. At minimum, do not commit the email in a public mirror.

**Env file loaded with weak parsing:**
- Risk: `config.load_env_file` (`src/config.py:5-19`) and `_load_hermes_env` (`scripts/hh_ai_vacancies.py:20-34`) parse `KEY=VALUE` lines with a naive `split("=", 1)` and a quote-strip that only handles matching outer quotes. Values containing `#` inline are not truncated (good), but multi-line values, escapes (`\n`, `\"`), and `export KEY=...` prefixes are mishandled.
- Files: `src/config.py:5-19`, `scripts/hh_ai_vacancies.py:20-34`
- Current mitigation: None — secrets silently malformed if quoted incorrectly.
- Recommendations: Use `python-dotenv` (would break stdlib-only rule) or document the exact supported format; at least reject malformed lines loudly instead of skipping.

**`http_client.request` does not validate TLS or redirect behavior:**
- Risk: `urllib.request.urlopen` follows redirects by default and accepts any cert. A compromised HH/Ollama endpoint could redirect to an attacker host; tokens (`Authorization: Bearer ...`) would follow.
- Files: `src/http_client.py:31-40`
- Current mitigation: All targets are hardcoded HTTPS URLs in `config.py`.
- Recommendations: Disable redirects (`urllib.request.HTTPRedirectHandler` no-op) or at least assert the final scheme is HTTPS.

**Cover-letter content sent to third-party LLM without redaction:**
- Risk: `src/cover.py:build_prompts` sends the full resume and vacancy description (up to 2500 chars) to `OLLAMA_BASE_URL`. If `OLLAMA_BASE_URL` is misconfigured to a hosted endpoint, PII (employer names, candidate work history) leaves the host.
- Files: `src/cover.py:37-63`, `src/http_client.py`
- Current mitigation: Default `OLLAMA_BASE_URL` is `https://ollama.com/v1` (`src/config.py:71`).
- Recommendations: Document the data-flow boundary; consider redacting employer names before sending.

## Performance Bottlenecks

**Sequential enrichment across all new vacancies:**
- Problem: `enrich.enrich_new` (`src/enrich.py:62-69`) loops new IDs one at a time, each issuing a `GET /vacancies/{id}` with no concurrency. Cover-letter generation is parallelized (`src/cover.py:146-155`, `ThreadPoolExecutor`) but enrichment is not.
- Files: `src/enrich.py:62-69`
- Cause: Single-threaded loop; each call has network latency + `APPLY_PAUSE_SEC`-style gaps are not applied here but round-trips dominate.
- Improvement path: Use `ThreadPoolExecutor` (same pattern as `cover.generate_all`), capped at a small worker count to respect HH rate limits.

**Fetch only reads page 0 (50 results) per keyword:**
- Problem: `fetch.fetch_all` (`src/fetch.py:92-97`) requests `per_page=50, page=0` for each of 13 keywords and never paginates. `found_total` is reported but the extra results are silently dropped.
- Files: `src/fetch.py:87-121`
- Cause: No pagination loop.
- Improvement path: Iterate pages until `pages` count from the API response is exhausted, or cap at a configurable max. Document the 50/keyword ceiling.

**Sheets full-rewrite on every run:**
- Problem: `sheets_export.export` clears `A:K` and rewrites all rows in batches of 200 (`src/sheets_export.py:66-84`). With a growing `vacancies.json`, this is O(N) API calls every cron tick.
- Files: `src/sheets_export.py:56-84`
- Cause: Design choice (Sheets is visualization-only; JSON is SoT).
- Improvement path: Acceptable while N is small; add a row-count guard (skip rewrite if unchanged) or switch to append-only with a `last_exported_first_seen` cursor.

## Fragile Areas

**OAuth refresh-token single-use semantics:**
- Files: `src/auth.py:25-65`, `src/store.py:95-104`
- Why fragile: `refresh_token` is single-use; `auth.save_tokens` writes atomically (temp + `os.replace`). If the process is killed between `os.replace` and the caller persisting the new tokens elsewhere, or if two runs overlap, the pair is lost and a manual OAuth re-auth is required (`docs/api-contract.md §3`). `CLAUDE.md` flags this explicitly.
- Safe modification: Never run two pipeline instances concurrently against the same `data/hh_tokens.json`. Keep `save_tokens` atomic.
- Test coverage: `tests/test_auth.py` exercises refresh; concurrency is not tested.

**Cover-letter cleaning regex chain:**
- Files: `src/cover.py:96-111`, `scripts/hh_ai_vacancies.py:341-376`
- Why fragile: Six sequential `re.sub` calls strip markdown, dashes, greetings, signatures, trailing incomplete paragraphs, then re-append a fixed closing. Edge cases (no greeting, greeting in Cyrillic, signature without newline, closing already present with trailing punctuation) are handled by heuristics that can produce empty strings or duplicate closings. `letter_ok` (`src/cover.py:125-133`) is the only gate before fallback.
- Safe modification: Add a regression test for every new regex; run `evals/rate_cover_letters.py --sample 5` after any change.
- Test coverage: `tests/test_cover.py` (50 lines) covers basic cases only.

**`ARCHIVE_RE` and `JUNK_RE` regexes are the sole quality gate:**
- Files: `src/config.py:89-104`, `src/fetch.py:37-49`, incident log `references/archive-filter-incident-2026-06-27.md`
- Why fragile: A single missed archive keyword lets closed vacancies into the report (real incident on 2026-06-27). The regex is duplicated between `src/config.py` and `scripts/hh_ai_vacancies.py:86-107` and they have already diverged (the incident-ref version has extra clauses not present in `config.py`).
- Safe modification: Port any new keyword to BOTH files; add a fixture-based test asserting archived titles are rejected.
- Test coverage: `tests/test_fetch_enrich.py` (78 lines) partially covers filtering.

**Pipeline exit-code contract:**
- Files: `src/pipeline.py:19-105`
- Why fragile: Exit codes (0 success, 2 auth/config fatal, 3 fetch fatal) are an implicit contract with the Hermes cron host and `evals/check_metrics.py`. `sheets_rows = -1` on Sheets failure (`pipeline.py:83`) is a sentinel that `check_metrics.check` happens to compare against `total` — any other negative value breaks the goal check.
- Safe modification: Keep exit codes documented in `CLAUDE.md` and `src/pipeline.py` docstring; do not introduce new sentinel values.
- Test coverage: `tests/test_pipeline_e2e.py` (91 lines) covers the happy path and one auth failure.

## Scaling Limits

**`vacancies.json` loaded fully into memory:**
- Current capacity: `store.load()` (`src/store.py:84-92`) reads the entire JSON dict; `store.save` rewrites it whole (`src/store.py:95-104`). Fine for hundreds-to-low-thousands of records.
- Limit: Single-process memory + atomic rewrite cost grow linearly. `sheets_export` clear+rewrite is the first thing to degrade.
- Scaling path: Shard by month, or move to SQLite (`data/vacancies.db`) with the same SoT contract.

**`COVER_LETTER_WORKERS=10` default:**
- Current capacity: 10 concurrent Ollama calls.
- Limit: Ollama Cloud rate limits / concurrency caps are not enforced client-side; 429s from Ollama are not retried (cover.py just returns "").
- Scaling path: Add 429 backoff in `call_ollama` mirroring `apply.py`'s retry pattern; make workers configurable per-run.

## Dependencies at Risk

**`playwright` (used only by `scripts/hh_token_updater.py`):**
- Risk: Heavy third-party dep, only for interactive token renewal. Not pinned. Browser binary install is a separate step (`python3 -m playwright install chromium`).
- Impact: Token renewal breaks if playwright API changes; the new `src/` pipeline's OAuth flow does not need it (uses refresh_token, not the admin UI).
- Migration plan: Once the new pipeline's refresh_token loop is proven stable, retire `hh_token_updater.py` entirely. The monolith's app-token flow is the only consumer.

**`OLLAMA_MODEL = "deepseek-v4-flash"` default:**
- Risk: Hardcoded model id in `src/config.py:72` and `scripts/hh_ai_vacancies.py:64`. Model availability on Ollama Cloud is not guaranteed; `cover.call_ollama` logs HTTP status and returns "" (fallback letter) rather than failing loud.
- Impact: Silent degradation to template fallback letters; `evals/rate_cover_letters.py` may flag quality drop.
- Migration plan: Make model an env var (already is, but the default is stale); add a startup probe that fails fast if the model 404s.

## Missing Critical Features

**No retry / backoff on enrichment 429:**
- Problem: `enrich.enrich_record` (`src/enrich.py:26-59`) treats any non-200 as failure and moves on; HH rate limits during a large new-ID batch silently skip enrichment for those records. They stay `enriched=False` and are never retried unless re-fetched.
- Blocks: `evals/check_metrics.py` `enrichment_ge_95` goal can silently fail.

**No idempotency key on `/negotiations` POST:**
- Problem: `apply._post_negotiation` (`src/apply.py:21-29`) has no idempotency guard. A retry after a network timeout mid-POST could double-apply (HH dedups by vacancy+resume, so impact is low, but the `applied_at`/status bookkeeping can drift).
- Blocks: Safe retry semantics for `BatchStop("api_down")` re-queues.

**No structured logging:**
- Problem: All diagnostics are `print(..., file=sys.stderr)` with ad-hoc `[module]` prefixes (`src/pipeline.py:21`, `src/fetch.py:103`, `src/apply.py:129`, etc.). No log levels, no JSON output, no correlation id.
- Blocks: Operational observability on the Hermes cron host; debugging distributed failures.

## Test Coverage Gaps

**No concurrency / race tests:**
- What's not tested: Two pipeline runs overlapping on `data/hh_tokens.json` or `data/vacancies.json`. `auth.save_tokens` atomicity and `store.save` `.bak`+`os.replace` are untested under crash.
- Files: `tests/test_auth.py`, `tests/test_store.py`
- Risk: Token pair loss (requires manual OAuth re-auth) or store corruption.
- Priority: High — the refresh_token single-use semantics make this a real operational hazard.

**`sheets_export` not tested against real Sheets API:**
- What's not tested: `sheets_export.export` clear+batch-write logic; tests mock `http_client.request` so the actual Sheets URL construction, range encoding, and batch boundaries are exercised only against mocked responses.
- Files: `tests/test_sheets_telegram.py` (69 lines)
- Risk: A Sheets API schema change or a range-encoding bug (`urllib.parse.quote(..., safe="")`) goes unnoticed until a live run.
- Priority: Medium — Sheets is visualization-only, but a bad export corrupts the report surface.

**`evals/check_metrics.py` not run in CI:**
- What's not tested: The goal-check itself. There is no CI config in the repo (no `.github/`, no `Makefile`). `check_metrics` is invoked manually after a run.
- Files: `evals/check_metrics.py`
- Risk: Goal regression (e.g. enrichment <95%, duplicates >0) is only caught when someone remembers to run it.
- Priority: Medium.

**`scripts/hh_ai_vacancies.py` has no direct tests:**
- What's not tested: The 900-line monolith's `main()`, `update_respond_column`, `get_vacancy_details`, `clean_cover_letter`. Tests target the `src/` package only.
- Files: `tests/` (no `test_hh_ai_vacancies.py`)
- Risk: The old cron job (still the live deployment per `CLAUDE.md`) is unverified.
- Priority: High until cutover completes; Low after `scripts/hh_ai_vacancies.py` is deleted.

**Cover-letter quality eval is manual:**
- What's not tested: `evals/rate_cover_letters.py` is a standalone LLM rubric run by hand (`python3 -m evals.rate_cover_letters --sample 5`). It is not wired into the pipeline or any gate.
- Files: `evals/rate_cover_letters.py`
- Risk: Cover-letter drift (resume edits, prompt tweaks, model swap) ships without a quality check.
- Priority: Medium.

---

*Concerns audit: 2026-07-22*