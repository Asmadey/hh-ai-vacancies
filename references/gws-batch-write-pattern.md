# gws CLI Batch Write Pattern for Google Sheets

## Problem

When writing 100+ rows with long text fields (cover letters, vacancy descriptions) to Google Sheets via `gws sheets spreadsheets.values update --json`, the command exceeds the OS `argv` limit:

```
[Errno 7] Argument list too long: '/home/hermes/.npm-global/bin/gws'
```

## Solution: batch with `gws sheets +append --json-values`

```python
import json, os, subprocess, time

GWS_BIN = os.path.expanduser("~/.npm-global/bin/gws")
SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"
BATCH_SIZE = 20

def write_rows(vacancies):
    for batch_start in range(0, len(vacancies), BATCH_SIZE):
        batch = vacancies[batch_start:batch_start + BATCH_SIZE]
        rows = []
        for v in batch:
            row = [
                v.get("date", ""),
                v.get("title", ""),
                v.get("company", ""),
                v.get("salary", "не указана"),
                v.get("location", ""),
                v.get("level", "middle"),
                v.get("url", ""),
                v.get("match", "⭐ Релевантный"),
                v.get("cover_letter_tag", ""),
                v.get("respond", ""),
            ]
            rows.append(row)
        
        json_values = json.dumps(rows, ensure_ascii=False)
        cmd = [GWS_BIN, "sheets", "+append",
               "--spreadsheet", SPREADSHEET_ID,
               "--json-values", json_values]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            # Retry with individual rows
            for row in rows:
                single = json.dumps([row], ensure_ascii=False)
                cmd_single = [GWS_BIN, "sheets", "+append",
                              "--spreadsheet", SPREADSHEET_ID,
                              "--json-values", single]
                subprocess.run(cmd_single, capture_output=True, text=True, timeout=30)
                time.sleep(0.3)
        time.sleep(1)
```

## Key points

- `+append` finds the end of the sheet automatically — no need to calculate start row.
- `--json-values` accepts a JSON array of arrays: `[[row1col1, row1col2, ...], ...]`
- 20 rows per batch is safe. 135 rows in 7 batches completed without error.
- `ensure_ascii=False` preserves Cyrillic text.
- 1-second delay between batches avoids rate limiting.
- gws CLI is at `~/.npm-global/bin/gws`, not on system PATH.
- The `+append` helper does NOT require a range parameter — just `--spreadsheet` and `--json-values`.

## Alternative: `spreadsheets.values update` with explicit range

If you need to overwrite existing rows (not append), use `spreadsheets.values update`:

```bash
gws sheets spreadsheets values update \
  --params '{"spreadsheetId":"ID","range":"HH_AI!A388:J522","valueInputOption":"RAW"}' \
  --json '{"range":"HH_AI!A388:J522","majorDimension":"ROWS","values":[...]}' \
  --format json
```

This also has the argv limit — use it only for small updates (<20 rows).

## Session reference

2026-07-15: Writing 135 HH.ru vacancies with cover letters to the HH_AI tab. First attempt with `spreadsheets.values update` hit `Argument list too long`. Switched to `+append --json-values` in batches of 20, all 135 rows written successfully in 7 batches.