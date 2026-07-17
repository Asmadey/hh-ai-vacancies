# Incident: archived HH.ru vacancies leaked into AI/PM report

**Date:** 2026-06-27
**Skill:** research/vacancy-monitoring
**Affected job:** `6d9bd734b2ab` — Ежедневный поиск вакансий AI/PM

## Symptom

Daily report listed vacancies such as:

- "AI Product Manager (автоматизация) В архиве с 15 марта 2026"
- "AI Product Manager В архиве с 27 февраля 2026 - Москва - HH.ru"

These roles were already closed/archived but still appeared as new findings.

## Root cause

The deterministic processor `~/.hermes/scripts/ai_pm_vacancies.py` only filtered on:

- management/senior title keywords
- junk-title blocklist
- budget threshold
- URL dedup against `seen.json`

It had no check for archive/closed/suspended markers in `title` or `description`. HH.ru returns archived listings in search results with explicit archive dates in the snippet.

## Fix

Added `ARCHIVE_RE` + `is_active(title, description)` to the processor. The filter runs on raw search results *before* enrichment, so archived listings are dropped before any Google Sheets write.

Regex covers Russian and English archive/closed signals:

```python
ARCHIVE_RE = re.compile(
    r"\b(в архиве|архивная|архив|удалена|закрыта|приостановлена|неактивна|не активна|"
    r"вакансия закрыта|вакансия не актуальна|вакансия в архиве|не принимаем|"
    r"архиве с \d{1,2}[\s\.][а-яa-z]+\s+\d{4}|"
    r"archived?|archived?\s+(?:since|from|on|at)|in archive|expired|closed|"
    r"no longer accepting|position (?:closed|filled)|vacancy closed|"
    r"not currently hiring|paused|suspended|on hold)\b",
    re.I,
)
```

## Secondary fix

Converted the Telegram report from Markdown to HTML. The cron dispatcher for `deliver: origin` does not set `parse_mode=Markdown`, so `[link](url)` and `**bold**` were rendering as raw text. The processor now emits `<a>`, `<b>`, `<i>` and escapes dynamic content with `html.escape()`.

## Verification

Local test with a JSON array of 5 results (4 archived/closed, 1 active senior AI PM) left exactly 1 active vacancy. HTML report generated without Markdown artifacts.

## Reference implementation

See `references/ai-pm-vacancies-processor.py` for the full deterministic filter pipeline.
