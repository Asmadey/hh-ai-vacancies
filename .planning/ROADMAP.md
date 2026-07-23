# Roadmap: HH-AI-Vacancies

## Overview

A bounded brownfield milestone on the existing HH.ru vacancy-apply pipeline: remove the legacy monolith and old scripts to leave a single clean `src/` path, integrate proactive OAuth token auto-refresh so the pipeline no longer needs manual token babysitting, then validate the whole chain live against real hh.ru — first dry, then with exactly 2 real applications — before handing off legacy cron removal. Three phases, each an end-to-end verifiable capability, ordered by hard dependency: cleanup → token automation → live validation.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Cleanup & repo consolidation** - Remove the legacy monolith + old scripts, clean doc references, push to the single canonical repo
- [ ] **Phase 2: Token auto-refresh integration** - Extract runnable OAuth manager + cron wrapper, bridge .env ↔ data/hh_tokens.json, Telegram alert, offline tests on py3.10 + py3.13
- [ ] **Phase 3: Live e2e validation** - DRY_RUN=1 full-chain check then live DRY_RUN=0 APPLY_LIMIT=2 real applies, verify statuses + Telegram + Sheets + check_metrics, hand off legacy cron removal

## Phase Details

### Phase 1: Cleanup & repo consolidation
**Goal**: Only the modular `src/` pipeline remains in the repo; legacy monolith and old scripts are gone, docs are clean, and all changes are pushed to the single canonical repo `Asmadey/hh-ai-vacancies`.
**Mode**: mvp
**Depends on**: Nothing (first phase)
**Requirements**: DEL-01, DEL-02, DEL-03, DEL-04, DEL-05, REPO-01, REPO-02
**Success Criteria** (what must be TRUE):
  1. `scripts/hh_ai_vacancies.py`, `scripts/hh_token_updater.py`, and `scripts/migrate_seen.py` no longer exist on disk; `scripts/` directory and its `__init__.py` are removed if empty
  2. README.md, SKILL.md, CLAUDE.md, and DEPLOY.md contain no references to the monolith, the old token updater, `migrate_seen`, legacy cron cutover steps, or old command examples — only the `src/` path is documented
  3. `git push` to `Asmadey/hh-ai-vacancies` succeeds with the cleanup commit; the DEMO wrapper and its `.planning/` directory remain local-only and are not pushed
  4. `python3 -m pytest` still passes after the deletions (no regressions from removing the old code path)
**Plans**: TBD

Plans:
- [ ] 01-01: TBD

### Phase 2: Token auto-refresh integration
**Goal**: Proactive HH OAuth token refresh runs before the parser, bridged to the format `src/auth.py` reads, with Telegram alerts on failure and offline tests passing on both Python 3.10 and 3.13 — so the pipeline no longer requires manual token babysitting.
**Mode**: mvp
**Depends on**: Phase 1
**Requirements**: TOK-01, TOK-02, TOK-03, TOK-04, TOK-05, TOK-06, TOK-07
**Success Criteria** (what must be TRUE):
  1. `python3 -m hh_oauth_manager refresh` obtains and atomically persists a fresh token pair; `python3 -m hh_oauth_manager check` reports token validity without a full pipeline run
  2. After a refresh, `data/hh_tokens.json` contains the new token pair in the format `src/auth.py` reads, so the pipeline consumes it with no manual editing of `.env` or the JSON file
  3. On expired `refresh_token`, a Telegram alert with re-authorization instructions is delivered (HTML, dynamic content escaped via `telegram.esc()`)
  4. Offline tests for the refresh and bridge logic pass via `MockHttp`/monkeypatch on both Python 3.10 (host) and 3.13 (Mac)
  5. `hh_token_refresh.sh` is invocable as a cron job scheduled 5 minutes before the pipeline run, performing refresh + Telegram alert on failure
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

### Phase 3: Live e2e validation
**Goal**: The full pipeline is verified end-to-end against real hh.ru — first dry, then live with exactly 2 real applications — with statuses, Telegram report, Google Sheets export, and `check_metrics.py` all confirmed, and legacy cron removal handed off to the user.
**Mode**: mvp
**Depends on**: Phase 2
**Requirements**: E2E-01, E2E-02, E2E-03, E2E-04, E2E-05, E2E-06
**Success Criteria** (what must be TRUE):
  1. Live secrets/tokens are provisioned on the Mac and `DRY_RUN=1 python3 -m src.pipeline` completes the full chain (fetch → enrich → cover → sheets → telegram, no applies) on Python 3.13
  2. `python3 -m hh_oauth_manager refresh` and `check` succeed immediately before the live run, confirming auto-refresh works in real conditions
  3. `DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline` sends real cover letters to exactly 2 vacancies (no more), and `data/vacancies.json` records status `отправлено` for those vacancies
  4. A Telegram report is delivered, the Google Sheets `HH_AI` tab is updated, and `python3 evals/check_metrics.py` exits 0
  5. Legacy cron `99a55e0f5ac4` removal on the Hermes host is documented and handed off to the user (the actual pause/remove is the user's action on the host)
**Plans**: TBD

**Caution:** This phase sends REAL job applications via `POST /negotiations` to REAL hh.ru vacancies. This is irreversible and outward-facing. The `APPLY_LIMIT=2` cap is a hard guardrail — do not raise it without explicit user approval. The first live run must be `DRY_RUN=1`, then `DRY_RUN=0 APPLY_LIMIT=2` only after the dry run passes and the user confirms.

Plans:
- [ ] 03-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Cleanup & repo consolidation | 0/0 | Not started | - |
| 2. Token auto-refresh integration | 0/0 | Not started | - |
| 3. Live e2e validation | 0/0 | Not started | - |