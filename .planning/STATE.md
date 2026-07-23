---
gsd_state_version: '1.0'
status: planning
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-22)

**Core value:** Reliably surface relevant AI/PM vacancies on hh.ru and auto-apply to them with generated cover letters every run — without manual token babysitting.
**Current focus:** Phase 1 — Cleanup & repo consolidation

## Current Position

Phase: 1 of 3 (Cleanup & repo consolidation)
Plan: 0 of 0 in current phase (not yet planned)
Status: Ready to plan
Last activity: 2026-07-22 — Roadmap created

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Milestone: Single canonical repo = `Asmadey/hh-ai-vacancies`; DEMO wrapper local-only
- Milestone: Delete all old/non-project scripts; only `src/` remains
- Milestone: Proactive cron token refresh before parser (from blueprint file)
- Milestone: Live e2e on this Mac with user-provided secrets; real applies capped APPLY_LIMIT=2

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 3: Live apply is irreversible / outward-facing — APPLY_LIMIT=2 is a hard guardrail
- Phase 3: `.env` is deny-protected from the agent on Hermes; user provides secrets to the Mac
- Phase 3: Legacy cron `99a55e0f5ac4` removal is the user's action on the host (handoff only)
- Phase 2: Must bridge `~/.hermes/.env` (`HH_OAUTH_*`) ↔ `data/hh_tokens.json` (what `src/auth.py` reads)
- Phase 2: Code must run on both Python 3.10 (host) and 3.13 (Mac)

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Hardening | HARD-01..04 (CI, pagination, retention, OTP) | v2 | 2026-07-22 |

## Session Continuity

Last session: 2026-07-22
Stopped at: Roadmap created — 3 phases, 20/20 requirements mapped
Resume file: None