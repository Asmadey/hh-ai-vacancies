# Technology Stack

**Analysis Date:** 2026-07-22

## Languages

**Primary:**
- Python 3.13 — all pipeline modules in `src/`, the orchestrator (`src/pipeline.py`), evals (`evals/`), and the new autonomous apply pipeline. Stdlib only (`urllib`, `json`, `re`, `concurrent.futures`, `os`, `shutil`, `datetime`, `html`, `argparse`, `random`). No `requests`, no third-party HTTP/HTTP libraries in the pipeline.

**Secondary:**
- Python 3 (Playwright) — `scripts/hh_token_updater.py` imports `playwright.sync_api` for interactive browser-driven HH.ru token renewal. This is the ONLY third-party Python dependency in the repo.
- JavaScript (Userscript) — `templates/hh_auto_response.user.js` is a Tampermonkey/Violentmonkey userscript (reference UI automation, not part of the cron pipeline).

## Runtime

**Environment:**
- Python 3.13.0 (observed on dev host). No `.python-version` / `.nvmrc` pinning; `python3` is invoked directly by cron (`config/cron.yaml` `script: python3 -m src.pipeline`).
- Cron host: Hermes Agent (Nous Research) — `no_agent: true` script-only job, workdir `~/.hermes/hh-ai-vacancies`. Not a containerized deployment; relies on the host Python.
- Playwright + Chromium required only for `scripts/hh_token_updater.py`; on headless hosts it must be wrapped with `xvfb-run -a`.

**Package Manager:**
- None declared. No `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, `package.json`, or lockfile present.
- The new pipeline is intentionally stdlib-only (enforced by convention per `CLAUDE.md`: "do not add `requests` or other third-party deps").
- `pytest` is required to run the 53-test suite but is NOT declared as a dependency anywhere — install ad-hoc (`pip install pytest`).
- `playwright` is required only by `scripts/hh_token_updater.py` (declared in its module docstring: `pip install playwright` then `python3 -m playwright install chromium`).
- Lockfile: missing (no dependency manifest to lock).

## Frameworks

**Core:**
- None. This is a stdlib-only scheduled script, not a web framework app. No Django/Flask/FastAPI. HTTP is done via `urllib.request` through a single entrypoint (`src/http_client.py:request()`).

**Testing:**
- pytest — runner only (no `pytest` config file, no plugins observed). Config via `tests/conftest.py` fixtures (`home`, `mock_http`, `no_sleep`, `tg_capture`, `tokens_file`) and helper builders (`make_resp`, `search_item`, `vacancy_details`). 53 tests across `tests/test_*.py`.

**Build/Dev:**
- No build step. Run directly: `python3 -m src.pipeline` (DRY_RUN defaults to 1 = safe).
- No linter/formatter config (no `.eslintrc`, `.prettierrc`, `biome.json`, `ruff.toml`, `.flake8`, `pyproject.toml`). No CI config (`.github/`, `.gitlab-ci.yml` absent).

## Key Dependencies

**Critical:**
- Python stdlib `urllib.request` / `urllib.parse` / `urllib.error` — sole HTTP transport for HH API, Google Sheets API, Telegram Bot API, Ollama Cloud. All routed through `src/http_client.py:request()` (returns `HttpResponse` for any HTTP status, raises `NetworkError` only on DNS/timeout/connection failure).
- `concurrent.futures.ThreadPoolExecutor` — parallel cover-letter generation (`src/cover.py:generate_all`, `COVER_LETTER_WORKERS` workers, default 10).

**Infrastructure (external SDKs accessed over HTTP, no client libraries):**
- HeadHunter API — `api.hh.ru` (search `/vacancies`, detail `/vacancies/{id}`, apply `/negotiations`, OAuth `/token`).
- Google Sheets API v4 — `sheets.googleapis.com` and `oauth2.googleapis.com/token` (refresh-token flow, batch write 200 rows at a time).
- Telegram Bot API — `api.telegram.org/bot{token}/sendMessage` (HTML parse mode).
- Ollama Cloud — `{OLLAMA_BASE_URL}/chat/completions` (OpenAI-compatible chat completions; default model `deepseek-v4-flash`, `reasoning_effort=none` for deepseek models).
- Playwright (Chromium) — `scripts/hh_token_updater.py` only; interactive HH admin login + OTP + token reveal.

## Configuration

**Environment:**
- Secrets/config loaded from `~/.hermes/.env` by `src/config.py:load_env_file()` (does NOT overwrite already-set env vars). The same loader is duplicated in `scripts/hh_ai_vacancies.py:_load_hermes_env()`.
- `HH_PIPELINE_HOME` — override knob for all `data/` paths (used by tests to redirect to tmp dir); defaults to repo root.
- Key env vars (see `src/config.py`):
  - `DRY_RUN` (default `"1"`) — `1` = no real applies, `0` = live.
  - `APPLY_LIMIT` (default `"0"`, 0 = uncapped) — cap applies per run; first live run should set `2`.
  - `APPLY_PAUSE_SEC` (default `"5"`) — pause between `/negotiations` POSTs.
  - `HH_RESUME_ID` — required for live apply (empty → Telegram alert + exit 2).
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram delivery; empty → `_send` falls back to stdout-only.
  - `OLLAMA_API_KEY`, `OLLAMA_BASE_URL` (default `https://ollama.com/v1`), `OLLAMA_MODEL` (default `deepseek-v4-flash`).
  - `COVER_LETTER_MAX_TOKENS` (900), `COVER_LETTER_TEMP` (0.4), `COVER_LETTER_WORKERS` (10).
  - `HH_APP_TOKEN`, `HH_ADMIN_EMAIL`, `HH_ADMIN_PASSWORD` — used only by the OLD monolith / token updater.

**Build:**
- No build config. Cron config: `config/cron.yaml` (Hermes cronjob, schedule `0 9 */2 * *`, `deliver: origin`, `no_agent: true`).

**Hardcoded constants (`src/config.py`):**
- `HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"` — mandatory for all HH requests (else `400 bad_user_agent`).
- `HH_API = "https://api.hh.ru"`.
- `SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"`, `SHEET_GID = 1464494667`, `SHEET_NAME = "HH_AI"`.
- `GOOGLE_CREDS_PATH = ~/.config/gws/credentials.json`.
- `KEYWORDS` — 13 AI/PM search terms (en/ru).
- `JUNK_RE`, `ARCHIVE_RE`, `RESUME_RE` — compiled regex filters.
- Status constants: `STATUS_SENT="отправлено"`, `STATUS_NOT_SENT="не отправлено"`, `STATUS_TEST="тест"`, `VALID_STATUSES`.

## Platform Requirements

**Development:**
- Python 3.13 (any 3.10+ likely works; uses `from __future__ import annotations` only in the token updater, otherwise stdlib typing).
- `pytest` installed locally to run `python3 -m pytest`.
- Optional: `playwright` + Chromium for token renewal.

**Production:**
- Hermes Agent cron host. Job `99a55e0f5ac4` (old monolith, `scripts/hh_ai_vacancies.py`) to be replaced by `config/cron.yaml` (`python3 -m src.pipeline`) per `docs/DEPLOY.md` Step 4.
- Files on host: `~/.hermes/.env`, `~/.hermes/hh_ai_seen.json` (legacy dedup), `~/.config/gws/credentials.json` (Google OAuth), `~/.hermes/hh-ai-vacancies/data/hh_tokens.json` (HH user OAuth tokens), `~/.hermes/hh-ai-vacancies/data/vacancies.json` (source of truth).
- For token updater on headless host: `xvfb-run -a` wrapper + ability to write `/tmp/hh_otp.txt` manually.
- No containerization, no Docker, no process manager beyond Hermes cron.

---

*Stack analysis: 2026-07-22*