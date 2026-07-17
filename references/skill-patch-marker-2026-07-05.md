# Skill patch note: 2026-07-05

The umbrella `vacancy-monitoring/SKILL.md` should be updated to reflect that `~/.hermes/scripts/ai_pm_vacancies.py` is now a HeadHunter-API tracker, not a multi-source stdin processor.

Specific text to insert in section "3. Deterministic processor script template":

After the sentence "The template now includes cover-letter generation (see `references/hh-cover-letter-generation.md`)." add:

**Multi-source trackers** (LinkedIn, RemoteOK, WeWorkRemotely, etc.) should keep the stdin/JSON pattern described below. **HeadHunter-only trackers** should call the HH API directly, like `ai_pm_vacancies.py` does after 2026-07-05. See `references/ai-pm-hh-api-migration.md` for the migration rationale and exact API call pattern.

And change responsibility step 1 from:

1. Read raw results from stdin (JSON array).

to:

1. **HeadHunter-only variant:** query `https://api.hh.ru/vacancies` with `User-Agent` and `Authorization: Bearer <token>`, then fetch `GET /vacancies/{id}` for full descriptions before scoring.
2. **Multi-source variant:** read raw results from stdin (JSON array).

Also add to References list:
- `references/ai-pm-hh-api-migration.md`

This note is a patch marker because the live SKILL.md edit failed in the review-protected environment; apply it on the next maintenance pass.
