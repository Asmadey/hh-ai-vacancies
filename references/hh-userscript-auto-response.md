# HeadHunter auto-response userscript

Session: 2026-06-29 — user wanted a safe, browser-only way to submit vacancy responses on hh.ru using the cover letters already stored in Google Sheets.

## Why a userscript instead of server-side automation

- hh.ru sessions are fingerprint/IP-bound; cookies saved from a Hermes/CDP browser do not restore into a fresh Playwright/Browserbase context.
- The user can log in manually in their normal browser context.
- A Tampermonkey/Violentmonkey userscript runs in that authenticated context and makes the same XHR the site itself makes.
- No server-side secrets, no cron login, no CAPTCHA solving, no headless browser maintenance.

## What the userscript does

1. Adds a fixed-position button (🚀 Автоотклик) on every `https://hh.ru/vacancy/*` page.
2. Reads `vacancy_id` from the URL path.
3. Loads the user's `resume_hash` from a constant in the script (or from `localStorage` / GM storage as fallback).
4. Fetches the cover letter from the Google Sheet via the `gviz/tq?tqx=out:csv` public CSV export.
5. Calls `GET /applicant/vacancy_response/popup?vacancyId={id}` to warm the session/form.
6. Calls `POST /applicant/vacancy_response/popup` with `FormData` containing `_xsrf`, `vacancy_id`, `resume_hash`, `letter`, `ignore_postponed=true`, `incomplete=false`, `lux=true`, `withoutTest=no`.
7. Updates the button to success/error state and logs response to the console.

## Google Sheets contract

The script expects a sheet with these columns (matching the HH AI tracker):

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| date | title | company | salary | location | level | url | match | cover-letter |

- `url` is used to find the matching row.
- `cover-letter` is sent as the response letter.
- The CSV export URL is `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&gid={SHEET_GID}`.
- The sheet must be **published / publicly readable** for CSV export to work without auth. If privacy is required, switch to the Sheets REST API with OAuth (more complex).

## Required constants

```javascript
const SPREADSHEET_ID = '1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok';
const SHEET_GID = '1464494667';          // worksheet id, not the title
const DEFAULT_RESUME_HASH = 'dde52705ff1076b2fe0039ed1f6255396b6135';
```

- `SHEET_GID` is the numeric worksheet id shown in the URL `.../edit?gid=1464494667#gid=1464494667`, not the human-readable tab title.
- `DEFAULT_RESUME_HASH` comes from the user's resume URL: `https://hh.ru/resume/{hash}`.

## Resume hash handling — hardcode, don't prompt

**Lesson from 2026-06-29:** Asking the user to paste `resume_hash` into a browser prompt is annoying and breaks the flow.

Best practice:

1. Hardcode `DEFAULT_RESUME_HASH` as a constant in the userscript.
2. Fall back to `localStorage.getItem('LastOpenedResume')` and GM storage only if the constant is empty.
3. Never show a `prompt()` for the hash during normal use.

```javascript
function getResumeHash() {
    let hash = localStorage.getItem('LastOpenedResume');
    if (!hash) hash = GM_getValue('hh_resume_hash', null);
    if (!hash && DEFAULT_RESUME_HASH) {
        hash = DEFAULT_RESUME_HASH;
        GM_setValue('hh_resume_hash', hash);
    }
    return hash;
}
```

## XSRF handling

The script reads the `_xsrf` cookie set by hh.ru and sends it as both a cookie and the `X-XSRFToken` header / `_xsrf` form field.

## Installation

1. Install Tampermonkey or Violentmonkey in the browser where you are logged into hh.ru.
2. Create a new script.
3. Copy the contents of `templates/hh_auto_response.user.js`.
4. Replace `SPREADSHEET_ID`, `SHEET_GID`, and `DEFAULT_RESUME_HASH` with your values.
5. Open a vacancy page on hh.ru and click 🚀.

## Security notes

- The script only runs on `https://hh.ru/vacancy/*`.
- It uses `credentials: 'same-origin'` so the browser attaches your authenticated hh.ru cookies automatically.
- No credentials leave the browser context except to Google Sheets CSV export (read-only public URL).

## Troubleshooting

- **"Письмо не найдено"** — the vacancy URL in the sheet does not match the current page. Use `location.href.split('?')[0]` for matching; query parameters are stripped.
- **"Ошибка 400"** — `_xsrf` cookie missing or expired. Refresh the page.
- **"Ошибка 401/403"** — session expired. Log in to hh.ru again in the same browser profile.
- **Prompt for resume_hash keeps appearing** — set a non-empty `DEFAULT_RESUME_HASH` or open your resume page once so `localStorage.LastOpenedResume` is populated.
- **CSV export returns empty** — make sure the sheet is publicly readable, or switch to authenticated Sheets API.

## Template location

- `templates/hh_auto_response.user.js` — ready-to-install userscript with `DEFAULT_RESUME_HASH` placeholder.
