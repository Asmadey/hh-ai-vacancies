# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Autonomous cron pipeline that searches AI/PM vacancies on the HeadHunter API, filters and enriches them, generates cover letters via Ollama Cloud, auto-applies through the HH `/negotiations` endpoint, exports to Google Sheets, and reports to Telegram. Private project; runs on a Hermes Agent cron host (Linux, Python 3.10), every 2 days at 09:00 MSK via `python3 -m src.pipeline`.

The legacy monolith (`scripts/hh_ai_vacancies.py`) and its helper scripts have been removed. The `src/` package is the only code path. It uses the HH **user OAuth token** (`data/hh_tokens.json`), because `/negotiations` requires a user token (app token → `403 oauth/user_auth_expected`). `SKILL.md` documents the umbrella skill, recipes, and incident history — read it before touching filtering, Sheets columns, or Telegram formatting.

## Commands

```bash
# Run the new pipeline (DRY_RUN defaults to 1 = safe, no applies sent)
DRY_RUN=1 python3 -m src.pipeline

# Live apply run — only after explicit go-ahead; cap applies on first run
DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline

# Goal check after a run (exit 0 = goal reached)
python3 evals/check_metrics.py

# LLM rubric on cover letters (independent Ollama call, threshold ≥7/10)
python3 -m evals.rate_cover_letters --sample 5

# HH.ru OAuth2 token manager (PKCE auth, refresh, check, env↔store bridge)
python3 scripts/hh_oauth_manager.py link              # сгенерить URL авторизации
python3 scripts/hh_oauth_manager.py exchange <code>   # обменять code на access+refresh
python3 scripts/hh_oauth_manager.py refresh           # авто-refresh (cron)
python3 scripts/hh_oauth_manager.py check             # проверить токен
python3 scripts/hh_oauth_manager.py bridge            # переложить HH_OAUTH_* → data/hh_tokens.json

# Tests — stdlib only, no requirements.txt; needs pytest installed
python3 -m pytest
python3 -m pytest tests/test_apply.py::test_name     # single test
python3 -m pytest tests/test_apply.py                # single file
```

The new pipeline uses **stdlib only** (`urllib`, `json`, `re`, `concurrent.futures`) — do not add `requests` or other third-party deps. Tests are 53 pytest cases across `tests/`.

## Architecture: the `src/` pipeline

`src/pipeline.py:run()` is the orchestrator. Stages, in order:

1. **auth** (`auth.py`) — load user OAuth tokens from `data/hh_tokens.json`; auto-refresh on `403 oauth/token_expired|bad_authorization` (one refresh + one retry; second 403 → fatal + Telegram alert). Tokens are saved atomically (temp + rename) because `refresh_token` is single-use — losing the pair means re-running OAuth.
2. **fetch** (`fetch.py`) — `GET /vacancies` across the 13 keywords in `config.KEYWORDS`; apply `JUNK_RE` / `ARCHIVE_RE` / `RESUME_RE` / relevance filters. `parse_level` and `match_reason` classify each hit.
3. **merge/dedup** (`store.py`) — `data/vacancies.json` is the **single source of truth**, keyed by `vacancy_id`. `merge()` adds only new IDs; `duplicates()` reports dups.
4. **enrich** (`enrich.py`) — `GET /vacancies/{id}` for full details (company, description text, work format, skills, apply_url). Runs only on new IDs.
5. **cover** (`cover.py`) — generate cover letters via Ollama Cloud (DeepSeek, reasoning disabled), parallelized by `COVER_LETTER_WORKERS`. Deterministic template fallback if Ollama fails. Resume is hardcoded in the module.
6. **apply** (`apply.py`) — `POST /negotiations` for selected candidates. Statuses: `отправлено` / `не отправлено` / `тест`. `limit_exceeded`, `resume_not_found`, `captcha_required`, and 5xx/network raise `BatchStop` (halt batch, defer to next run). 429 → backoff (`Retry-After` or 5→10→20s, max 3). `APPLY_PAUSE_SEC` between posts; `APPLY_LIMIT` caps per run (0 = uncapped).
7. **sheets_export** (`sheets_export.py`) — **full rewrite** of the `HH_AI` tab each run from `vacancies.json`. Sheets is visualization-only; no module ever reads cell data back.
8. **telegram** (`telegram.py`) — `send_report` + `send_alert`. `parse_mode=HTML`, always.

`store.save(vac)` is called **before** sheets export so the source of truth is persisted even if Sheets/Telegram fail. The pipeline writes `data/last_run_report.json` for `evals/check_metrics.py`. Exit codes: `0` success, `2` auth/config fatal, `3` fetch fatal.

### Single HTTP entrypoint

Every module calls `src/http_client.request(method, url, ...)`. Tests monkeypatch `http_client.request` with the `MockHttp` fixture in `tests/conftest.py` (FIFO queue matched by URL substring) — there is no live network in tests. If you add a module that makes HTTP calls, route them through `http_client.request` or they will bypass the test harness.

### Test isolation

`tests/conftest.py` provides:
- `home` fixture — sets `HH_PIPELINE_HOME=<tmp_path>` so all `data/` files land in a temp dir; sets `DRY_RUN=1`, clears Telegram/Ollama env, sets `HH_RESUME_ID`.
- `mock_http`, `no_sleep` (patches `time.sleep` in `apply`), `tg_capture` (intercepts `telegram._send`), `tokens_file`.
- Helpers `make_resp`, `search_item`, `vacancy_details` build HH-shaped fixtures.

`HH_PIPELINE_HOME` is the override knob for any path under `data/` (`config.py` reads it).

## Config & secrets

- Secrets live in `~/.hermes/.env` (loaded by `src/config.py:load_env_file` — does not overwrite existing env). Hermes blocks direct edits to `.env` with `sed`/`patch`/`write_file`; use Python `re.sub` to update keys (snippet in `SKILL.md`).
- User OAuth tokens live in `data/hh_tokens.json` (one-time setup via authorization_code flow, `docs/DEPLOY.md` Step 0).
- Google Sheets OAuth refresh token: `~/.config/gws/credentials.json`.
- Key env: `DRY_RUN` (default `1`), `APPLY_LIMIT`, `APPLY_PAUSE_SEC`, `HH_RESUME_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_API_KEY`, `OLLAMA_MODEL`.
- Sheets target: spreadsheet `1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok`, tab `HH_AI` (GID `1464494667`). 9-column layout: `date | title | company | salary | location | level | url | match | cover-letter` (+ `respond`, `статус` in the new pipeline exporter). **Confirm columns before the first write** — changing shape later means clearing and rewriting the sheet.

## Non-obvious rules (from `SKILL.md` pitfalls — these have all caused real incidents)

- **Telegram reports use HTML, not Markdown.** `[text](url)` and `**bold**` render as raw text because the dispatcher does not set `parse_mode=Markdown`. Escape dynamic content with `html.escape()`. Job titles in the report must be clickable `<a href>` links to the vacancy URL.
- **Never report archived/closed vacancies as new.** Filter raw results by `title + description` with `ARCHIVE_RE` **before** enrichment.
- **`bad_authorization` / `invalid_grant` is often a stale or typo'd token, not revocation.** For the user OAuth pair, compare byte-for-byte with what `hh_oauth_manager.py` wrote (watch `0`/`O`, `1`/`l`, `I`/`l`); if `refresh` returns `invalid_grant`, re-run `link` + `exchange`.
- **`User-Agent` is mandatory** for all HH requests or you get `400 bad_user_agent`. Use `config.HH_USER_AGENT`.
- **cronjob `update` silently does nothing** if the body matches current state. To change schedule/prompt/script: `cronjob pause` → `cronjob remove` → `cronjob create`.
- **Never print secrets** in reports, logs, diffs, or session summaries — replace with `[REDACTED]`.
- **Junk-title filter polarity:** `title_ok` returns `True` when the title does NOT match `JUNK_RE`; reversing it adds junk instead of removing it.

`references/` holds dated incident logs and design notes (token automation, cover-letter pipeline, gws batch-write pattern, archive-filter incident, etc.) — search there before debugging a known-area problem.