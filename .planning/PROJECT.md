# HH-AI-Vacancies

## What This Is

Autonomous cron pipeline that searches HeadHunter (hh.ru) for AI/PM vacancies across 13 keywords, filters and enriches them, generates cover letters via Ollama Cloud, auto-applies through the HH `/negotiations` endpoint, exports results to Google Sheets, and reports to Telegram. Private project; runs on a Hermes Agent cron host (Linux, Python 3.10), every 2 days at 09:00 MSK via `python3 -m src.pipeline`.

## Core Value

Reliably surface relevant AI/PM vacancies on hh.ru and auto-apply to them with generated cover letters every run — without manual token babysitting.

## Requirements

### Validated

<!-- Existing capabilities, inferred from the codebase map (2026-07-22). -->

- ✓ HH.ru vacancy search across 13 keywords with junk/archive/resume/relevance filters — existing (`src/fetch.py`)
- ✓ User OAuth token load + on-403 refresh with atomic save (single-use refresh_token) — existing (`src/auth.py`)
- ✓ Vacancy enrichment (full details, archive-flip detection) — existing (`src/enrich.py`)
- ✓ Cover-letter generation via Ollama Cloud + deterministic fallback, parallelized — existing (`src/cover.py`)
- ✓ Auto-apply via `POST /negotiations` with status machine, 429 backoff, BatchStop — existing (`src/apply.py`)
- ✓ Google Sheets full-rewrite export (visualization-only) — existing (`src/sheets_export.py`)
- ✓ Telegram HTML report + alerts — existing (`src/telegram.py`)
- ✓ `data/vacancies.json` single source of truth, atomic save with `.bak` — existing (`src/store.py`)
- ✓ 53 pytest cases, offline `MockHttp` harness — existing (`tests/`)
- ✓ Goal-check eval (schema, dups, ≥95% enrichment, 100% covers) — existing (`evals/check_metrics.py`)

### Active

<!-- The 4 workstreams from the user's 2026-07-22 directive. -->

- [ ] **DEL-01**: Remove the legacy monolith and all old/non-project scripts — delete `scripts/hh_ai_vacancies.py`, `scripts/hh_token_updater.py`, `scripts/migrate_seen.py`; clean references in README/SKILL.md/CLAUDE.md/DEPLOY.md
- [ ] **REPO-01**: Consolidate to a single repo — `Asmadey/hh-ai-vacancies` (existing GitHub repo) as the canonical root; DEMO wrapper stays local and is not pushed
- [ ] **TOK-01**: Integrate proactive auto token-refresh — extract `hh_oauth_manager.py` + `hh_token_refresh.sh` from `docs/hh_ru_token_auto_refresh.py` as real modules; cron refresh before parser; Telegram alert on refresh failure; bridge token storage to what `src/auth.py` reads
- [ ] **E2E-01**: Live end-to-end validation — run the full pipeline against real hh.ru with real cover letters sent to vacancies (capped `APPLY_LIMIT=2`), verify statuses `отправлено`, Telegram report, Sheets export, and `check_metrics.py` pass

### Out of Scope

- New vacancy sources (LinkedIn, other boards) — not requested
- Dashboard / web UI — not requested
- Replacing the stdlib-only constraint — keep `urllib`/`json`/`re`/`concurrent.futures` only; no `requests` or 3rd-party runtime deps
- Rewriting the working `src/` pipeline architecture — only remove the old path and add token-refresh

## Context

- **Brownfield.** A full codebase map exists at `.planning/codebase/` (STACK, ARCHITECTURE, STRUCTURE, CONVENTIONS, TESTING, INTEGRATIONS, CONCERNS — 1367 lines, 2026-07-22).
- **Runtime split.** The pipeline is designed to run on a Hermes Agent cron host (Linux, Python 3.10) where `~/.hermes/.env`, `data/hh_tokens.json`, and `~/.config/gws/credentials.json` live. This Mac (darwin, Python 3.13) has none of these locally.
- **Live e2e decision (2026-07-22):** the user will provide secrets/tokens to this Mac and the live run (including real applies) will execute here, despite the 3.13-vs-3.10 mismatch and `.env` being deny-protected from the agent.
- **Old cron still active.** Hermes cron job `99a55e0f5ac4` still runs the legacy monolith on the host; the DEPLOY.md Step 4 cutover has not been performed. Pausing/removing that cron is the user's responsibility on the host.
- **Two repos today.** `hh-ai-vacancies/` is its own GitHub repo (`Asmadey/hh-ai-vacancies`); the `DEMO/` parent is a local repo (no remote) that wraps it. Per the user, the single repo will be `Asmadey/hh-ai-vacancies`; the DEMO wrapper is local-only and not pushed.
- **Token-auto-refresh blueprint** at `hh-ai-vacancies/docs/hh_ru_token_auto_refresh.py` is documentation (two files concatenated with markdown separators), not a runnable module. It stores tokens in `~/.hermes/.env` (`HH_OAUTH_*`), whereas `src/auth.py` stores in `data/hh_tokens.json` — integration must bridge the two.

## Constraints

- **Tech stack**: stdlib only (`urllib`, `json`, `re`, `concurrent.futures`) — no `requests` or third-party runtime deps — Why: test harness and host simplicity
- **Single HTTP seam**: all HTTP goes through `src/http_client.request()` — Why: `MockHttp` test harness monkeypatches that one symbol
- **Telegram HTML only**: `parse_mode=HTML`, dynamic content escaped via `telegram.esc()` — Why: MarkdownV2 renders as raw text
- **User-Agent mandatory**: `config.HH_USER_AGENT` on all HH requests — Why: HH returns `400 bad_user_agent` otherwise
- **Live apply is irreversible**: real `POST /negotiations` to real vacancies — first live run capped at `APPLY_LIMIT=2` — Why: CLAUDE.md policy; outward-facing action
- **Atomic token save**: `refresh_token` is single-use; temp+rename only — Why: losing the pair forces full re-OAuth
- **Compatibility**: code must run on both Python 3.10 (host) and 3.13 (this Mac) for the live e2e

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single repo = `Asmadey/hh-ai-vacancies` (existing GitHub repo) | User choice 2026-07-22; keeps real history and remote | — Pending |
| DEMO wrapper stays local, not pushed | Avoids nested-repo confusion; user choice | — Pending |
| Delete all old/non-project scripts (monolith + token_updater + migrate_seen) | User choice 2026-07-22; only `src/` remains | — Pending |
| Auto-token: proactive cron refresh before parser | User choice 2026-07-22; from blueprint file | — Pending |
| Live e2e on this Mac with user-provided secrets | User choice 2026-07-22; despite 3.13/3.10 and deny-protected `.env` | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-22 after initialization*