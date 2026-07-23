# Technology Stack

**Analysis Date:** 2026-07-22

## Languages

**Primary:**
- Python 3.10 — all application logic in `hh-ai-vacancies/src/*.py`, `hh-ai-vacancies/scripts/*.py`, `hh-ai-vacancies/evals/*.py`, `hh-ai-vacancies/tests/*.py` (pytest cache shows cpython-310 pycs).

**Secondary:**
- JavaScript — Tampermonkey userscript template `hh-ai-vacancies/templates/hh_auto_response.user.js` (browser-side auto-response helper, not part of the cron pipeline).
- YAML — cron job definition `hh-ai-vacancies/config/cron.yaml`.

## Runtime

**Environment:**
- Python 3.10 stdlib only for the new modular pipeline (`hh-ai-vacancies/src/`). No `requests`, no third-party HTTP libs. Uses `urllib.request`, `urllib.parse`, `urllib.error`, `json`, `re`, `concurrent.futures`, `datetime`, `html`, `shutil`, `os`, `sys`, `argparse`.
- Runs on a Hermes Agent cron host (Linux). Workdir `~/.hermes/hh-ai-vacancies` per `hh-ai-vacancies/config/cron.yaml`.
- `scripts/hh_token_updater.py` additionally requires Playwright + Chromium and `xvfb-run` on headless hosts (`pip install playwright; python3 -m playwright install chromium`).

**Package Manager:**
- None declared. No `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, or `poetry.lock` exist.
- Lockfile: missing — stdlib-only by design; only runtime extra is Playwright (used solely by the offline token updater script, documented inline in its header).
- pytest is expected to be preinstalled on the host for `python3 -m pytest`.

## Frameworks

**Core:**
- None (no web/CLI framework). The application is a batch pipeline invoked as `python3 -m src.pipeline` (`hh-ai-vacancies/src/pipeline.py`).

**Testing:**
- pytest 9.1.1 — 53 test cases across `hh-ai-vacancies/tests/` (per `hh-ai-vacancies/CLAUDE.md`). Cache artifacts in `hh-ai-vacancies/.pytest_cache/` and `__pycache__/test_*.cpython-310-pytest-9.1.1.pyc` confirm version.
- No coverage tool configured (`.coverage` file present at `hh-ai-vacancies/.coverage` but no `.coveragerc`/coverage config).

**Build/Dev:**
- No build step. Python runs from source.
- Cron scheduler: Hermes Agent cron (job `99a55e0f5ac4` for the old monolith; `config/cron.yaml` defines the new modular job, schedule `0 9 */2 * *`).

## Key Dependencies

**Critical:**
- Python 3.10 stdlib (`urllib`, `json`, `re`, `concurrent.futures`, `html`, `shutil`, `argparse`) — the entire HTTP surface goes through the single entrypoint `hh-ai-vacancies/src/http_client.py:request()`.
- Playwright + Chromium — only for `hh-ai-vacancies/scripts/hh_token_updater.py` (interactive HH.ru admin login to rotate the app token). Not used by the cron pipeline.

**Infrastructure:**
- Telegram Bot API — reports + alerts via `hh-ai-vacancies/src/telegram.py` (stdlib `urllib`, no SDK).
- Google Sheets API v4 — full-rewrite export via `hh-ai-vacancies/src/sheets_export.py` (OAuth refresh-token flow against `https://oauth2.googleapis.com/token`).
- Ollama Cloud — cover-letter generation + LLM-rubric eval via `hh-ai-vacancies/src/cover.py` and `hh-ai-vacancies/evals/rate_cover_letters.py` (OpenAI-compatible `/chat/completions` endpoint, default model `deepseek-v4-flash`, base URL `https://ollama.com/v1`).
- HeadHunter (hh.ru) public REST API — search, vacancy details, OAuth token refresh, and `/negotiations` apply via `hh-ai-vacancies/src/fetch.py`, `hh-ai-vacancies/src/enrich.py`, `hh-ai-vacancies/src/auth.py`, `hh-ai-vacancies/src/apply.py`.

## Configuration

**Environment:**
- Secrets and runtime config live in `~/.hermes/.env`, loaded by `hh-ai-vacancies/src/config.py:load_env_file()` (does not overwrite existing env vars). Hermes blocks `sed`/`patch`/`write_file` edits to this file; update keys with Python `re.sub` (snippet in `hh-ai-vacancies/SKILL.md`).
- Path override knob: `HH_PIPELINE_HOME` (defaults to package parent dir) — every `data/` path flows through `hh-ai-vacancies/src/config.py:data_dir()`. This is the test-isolation switch (see `hh-ai-vacancies/tests/conftest.py:home` fixture).

**Key env vars (defined in `hh-ai-vacancies/src/config.py`):**
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

**Hardcoded constants (`hh-ai-vacancies/src/config.py`):**
- `HH_API = "https://api.hh.ru"`.
- `HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"` — mandatory for all HH requests (HH returns `400 bad_user_agent` without it).
- `SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"`, `SHEET_GID = 1464494667`, `SHEET_NAME = "HH_AI"`.
- `GOOGLE_CREDS_PATH = ~/.config/gws/credentials.json`.
- `KEYWORDS` — 13 AI/PM search terms (Russian + English).
- Regex filters `JUNK_RE`, `RESUME_RE`, `ARCHIVE_RE` (compiled at import).
- Status constants `STATUS_SENT="отправлено"`, `STATUS_NOT_SENT="не отправлено"`, `STATUS_TEST="тест"`; `VALID_STATUSES` set.

**Build:**
- No build config. Cron job config: `hh-ai-vacancies/config/cron.yaml` (Hermes `cronjob create`; edits require `pause → remove → create` because `update` silently no-ops on identical bodies).
- Git ignore: `hh-ai-vacancies/.gitignore` excludes `__pycache__/`, `*.pyc`, `*.pyo`, `.venv/`, `*.log`, `.DS_Store`, model files (`*.tflite`, `*.onnx`, `*.pt`, `*.pth`, `*.safetensors`).

## Platform Requirements

**Development:**
- Python 3.10. pytest 9.1.1 for tests. No virtualenv mandated (`.venv/` ignored if used).
- For token rotation only: Playwright + Chromium + `xvfb-run -a` on headless hosts (`hh-ai-vacancies/scripts/hh_token_updater.py`).
- Tests run fully offline — `hh-ai-vacancies/tests/conftest.py:MockHttp` monkeypatches `http_client.request` with a FIFO URL-substring queue; no live network.

**Production:**
- Hermes Agent cron host (Linux). New pipeline cron: `python3 -m src.pipeline` from workdir `~/.hermes/hh-ai-vacancies`, schedule every 2 days at 09:00 MSK, `no_agent: true`, `deliver: origin` (stdout mirrored to Telegram in addition to direct Bot API).
- Legacy monolith cron job id `99a55e0f5ac4` (`no_agent: true`); cutover described in `hh-ai-vacancies/docs/DEPLOY.md` Step 4.
- Required host files: `~/.hermes/.env` (secrets), `data/hh_tokens.json` (user OAuth pair — atomic save because `refresh_token` is single-use), `~/.config/gws/credentials.json` (Google Sheets OAuth).

---

*Stack analysis: 2026-07-22*