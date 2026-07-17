Session: 2026-06-28.

## What happened

While setting up the HeadHunter AI vacancy tracker, the user deleted columns `id`, `source`, and `priority` from the target Google Sheet after the first write.

The script had already written 156 rows in an 11-column layout (`date`, `title`, `company`, `salary`, `location`, `level`, `source`, `url`, `id`, `priority`, `match`). Aligning with the slimmed sheet required:

1. Updating `REPORT_COLUMNS` to the 8-column layout.
2. Switching dedup from vacancy `id` to vacancy `url`.
3. Removing unused `source` enrichment.
4. Clearing the sheet and rewriting all rows.

## Lesson

Always confirm the exact Google Sheets column set **before** the first append. Changing column shape after data exists forces a destructive rewrite.

## Final column layout

| A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|
| date | title | company | salary | location | level | url | match |

- `date`: `DD.MM.YYYY`
- `level`: `head` / `lead` / `senior` / `middle` / `junior`
- `match`: short reason why the role is relevant
