# Requirements: HH-AI-Vacancies

**Defined:** 2026-07-22
**Core Value:** Reliably surface relevant AI/PM vacancies on hh.ru and auto-apply to them with generated cover letters every run — without manual token babysitting.

## v1 Requirements

Requirements for this milestone (brownfield cleanup + token automation + live e2e). Each maps to roadmap phases.

### Cleanup

- [ ] **DEL-01**: Delete `scripts/hh_ai_vacancies.py` (legacy ~900-line monolith)
- [ ] **DEL-02**: Delete `scripts/hh_token_updater.py` (Playwright app-token renewal for the old path)
- [ ] **DEL-03**: Delete `scripts/migrate_seen.py` (one-shot, already executed)
- [ ] **DEL-04**: Remove monolith references from README.md, SKILL.md, CLAUDE.md, DEPLOY.md (the "two code paths" sections, legacy cron cutover steps, old command examples)
- [ ] **DEL-05**: Remove the now-empty `scripts/__init__.py` and the `scripts/` directory if empty after deletions

### Repo

- [ ] **REPO-01**: All code changes committed and pushed to `Asmadey/hh-ai-vacancies` (the single canonical repo)
- [ ] **REPO-02**: DEMO wrapper stays local-only (not pushed); `.planning/` tracked only in the local DEMO repo

### Token auto-refresh

- [ ] **TOK-01**: Extract a runnable `hh_oauth_manager.py` (modes auth/link/refresh/check, PKCE) from `docs/hh_ru_token_auto_refresh.py` into the repo
- [ ] **TOK-02**: Extract `hh_token_refresh.sh` cron wrapper (refresh + Telegram alert on failure)
- [ ] **TOK-03**: Bridge token storage — refresh updates `~/.hermes/.env` (`HH_OAUTH_*`) AND writes the token pair to `data/hh_tokens.json` in the format `src/auth.py` reads (or modify `auth.py` to read from `.env`)
- [ ] **TOK-04**: `hh_token_refresh.sh` runs refresh before the parser (cron 5 min before the pipeline)
- [ ] **TOK-05**: On refresh failure (refresh_token expired) send a Telegram alert with re-authorization instructions
- [ ] **TOK-06**: Add offline tests for the refresh/bridge logic (via MockHttp or monkeypatch)
- [ ] **TOK-07**: Runs on both Python 3.10 (host) and 3.13 (Mac)

### E2E validation

- [ ] **E2E-01**: User provides live secrets/tokens to the Mac (HH OAuth pair or runs the auth flow, `HH_RESUME_ID`, `OLLAMA_API_KEY`, Google creds, optional Telegram)
- [ ] **E2E-02**: Run `DRY_RUN=1` end-to-end (fetch → enrich → cover → sheets → telegram, no applies) to validate the full chain on Python 3.13
- [ ] **E2E-03**: Verify auto token-refresh works (`hh_oauth_manager.py refresh`/`check` succeeds before the run)
- [ ] **E2E-04**: Live run `DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline` — real cover letters sent to 2 vacancies
- [ ] **E2E-05**: Verify results: `data/vacancies.json` shows status `отправлено` for applied vacancies, Telegram report delivered, Google Sheets `HH_AI` tab updated, `check_metrics.py` exits 0
- [ ] **E2E-06**: Hand off legacy cron `99a55e0f5ac4` removal on the Hermes host to the user (documented)

## v2 Requirements

Deferred to a future milestone. Tracked but not in the current roadmap.

### Hardening

- **HARD-01**: Add CI (run pytest on push) — currently none
- **HARD-02**: Fix the silent 50-result pagination cap in `src/fetch.py` (real pagination across pages)
- **HARD-03**: Bound `data/vacancies.json` growth (retention/pruning policy)
- **HARD-04**: OTP handling in token renewal not via world-readable `/tmp/hh_otp.txt`

## Out of Scope

| Feature | Reason |
|---------|--------|
| New vacancy sources (LinkedIn, other boards) | Not requested; current scope is cleanup + token automation + e2e |
| Dashboard / web UI | Not requested |
| Replacing the stdlib-only constraint | Keep `urllib`/`json`/`re`/`concurrent.futures`; no `requests` or 3rd-party runtime deps |
| Rewriting the working `src/` pipeline | Only remove the old path and add token-refresh; architecture stays |
| OAuth initial authorization automation from this Mac | One-time interactive flow; user runs `auth`/`link` mode manually |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEL-01 | Phase 1 | Pending |
| DEL-02 | Phase 1 | Pending |
| DEL-03 | Phase 1 | Pending |
| DEL-04 | Phase 1 | Pending |
| DEL-05 | Phase 1 | Pending |
| REPO-01 | Phase 1 | Pending |
| REPO-02 | Phase 1 | Pending |
| TOK-01 | Phase 2 | Pending |
| TOK-02 | Phase 2 | Pending |
| TOK-03 | Phase 2 | Pending |
| TOK-04 | Phase 2 | Pending |
| TOK-05 | Phase 2 | Pending |
| TOK-06 | Phase 2 | Pending |
| TOK-07 | Phase 2 | Pending |
| E2E-01 | Phase 3 | Pending |
| E2E-02 | Phase 3 | Pending |
| E2E-03 | Phase 3 | Pending |
| E2E-04 | Phase 3 | Pending |
| E2E-05 | Phase 3 | Pending |
| E2E-06 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-07-22*
*Last updated: 2026-07-22 after roadmap creation*