# HH.ru application token automation

## Problem

HH.ru application tokens (`APPL...`) can be revoked at any time. The official public API (`api.hh.ru`) has **no endpoint to generate or regenerate an application token**. Generation is only available through the web admin panel at `https://dev.hh.ru/admin`.

This creates a manual toil step every time a cron job reports `token-revoked` / `bad_authorization`.

## Verified facts

- **Application token vs OAuth token:** see `references/hh-token-types-and-revocation.md`.
- **Public API `/token` endpoint:** only supports `authorization_code` and `refresh_token` grants for user-level OAuth. It does **not** support `client_credentials` for application tokens.
- **Admin panel UI:** the application token is shown under the app card (e.g. `Piramiza`) as "Токен приложения". It is masked by default; clicking the "[secret hidden]" button reveals it.
- **No visible regenerate button** in the current admin UI (as of 2026-07-03). The only interactive elements next to the app name are edit (pencil) and delete (trash). The edit dialog contains only app name and redirect URI.
- **DOM redaction:** the token value is visible on the rendered page but hidden from DOM queries by `data-abs-rule="secrets-redact"`. It cannot be extracted via in-browser JS.
- **HttpOnly cookies:** the admin session cookies are HttpOnly, so an external script cannot replay the session without browser automation.

## Solution: interactive Playwright updater

The practical automation is a **browser script** that:

1. Opens `https://dev.hh.ru/admin` in Chromium.
2. Logs in with `HH_ADMIN_EMAIL` + `HH_ADMIN_PASSWORD` from `~/.hermes/.env`.
3. Waits for an OTP from the operator (sent to the admin email).
4. Submits the OTP.
5. Opens the target app card and reveals the token.
6. Takes a screenshot of the token block.
7. Updates `HH_APP_TOKEN` in `~/.hermes/.env`.
8. Tests the token against `GET https://api.hh.ru/vacancies`.

Script: `scripts/hh_token_updater.py`

## Usage

```bash
# 1. Ensure credentials are in ~/.hermes/.env
#    HH_ADMIN_EMAIL=your@email.com
#    HH_ADMIN_PASSWORD=*** #    HH_APP_TOKEN=*** # optional; will be overwritten

# 2. Run (headless servers need Xvfb)
xvfb-run -a python3 -u ~/.hermes/scripts/hh_token_updater.py

# 3. When the script prints "Waiting for OTP code in /tmp/hh_otp.txt ...",
#    send the OTP from HH.ru email to the operator, who writes it to /tmp/hh_otp.txt.
```

## OTP input technique (2026-07-06)

HH.ru OTP screen uses a **single visual input field** with four dot placeholders. It does **not** reliably accept `otp_input.fill(code)` from Playwright — the typed digits do not appear in the UI and `Enter` does not submit the form.

The working technique is:

1. Click the input to focus it.
2. Type each digit using `page.keyboard.press(f"Digit{digit}")` with ~150 ms pause.
3. Press `Enter` with the global keyboard.

```python
otp_input.click()
page.wait_for_timeout(300)
for digit in otp:
    page.keyboard.press(f"Digit{digit}")
    page.wait_for_timeout(150)
page.wait_for_timeout(500)
page.keyboard.press("Enter")
```

Before typing, dismiss any overlay that can steal focus:
- Region confirmation popup: button `Да, верно` (text "Ваш регион — Москва?").
- Cookie banner at the bottom: button `Понятно`.

Failure to dismiss the region popup is a common cause of "OTP entered but nothing happens".

## Limitations

- **Semi-automated only.** The OTP must be provided interactively; there is no fully unattended flow unless you build an email-OTP reader.
- **No token regeneration via API.** The script only reads the currently displayed token. If the token is revoked, you must manually click any regenerate option in the admin UI (none was found in the current UI) or delete and recreate the application.
- **Headless detection.** HH.ru login can behave differently in headless Chromium. Running under `xvfb-run` with `headless=False` is more reliable than `--headless`.
- **OTP expiry.** The script waits 5 minutes for the OTP file. If the operator is slow, re-run the script.
- **Rate limiting on repeated OTP requests.** After many failed/timeout login attempts HH.ru may stop sending OTP emails. If the email does not arrive within 1–2 minutes, pause for 30–60 minutes before retrying.

## Troubleshooting

- **Email input not found on login page:** HH.ru login page defaults to the "Телефон" tab. The script must explicitly click the "Почта" text tab (or the corresponding radio button) and wait for the email input to become visible. If the page loads slowly, increase `wait_for_timeout` after clicking the tab. A screenshot of the failing page is saved to `~/.hermes/screenshots/hh_token_*.error.png`.
- **Timeout waiting for OTP input field:** the OTP screen appeared but Playwright could not match any of its selectors. The script now iterates through several selectors, takes a screenshot of the OTP screen to `/tmp/hh_otp_screen.png`, and logs which selector matched. If none matched, update `submit_otp()` with the actual input selector from the screenshot.
- **Timeout waiting for OTP code / OTP not provided within 5 minutes:** the script reached the OTP screen, but the operator did not provide a fresh code. This can also mean HH.ru never sent the email (spam folder, anti-bot delay, rate limiting, or email mismatch). Always provide the code immediately; if the email does not arrive within a minute, check spam and verify that `HH_ADMIN_EMAIL` matches the account email in `dev.hh.ru/admin`.
- **Old OTP rejected after a delay:** OTP codes are short-lived. If more than ~60 seconds passed between receiving the code and the script reading `/tmp/hh_otp.txt`, request a fresh code from HH.ru and restart the script.
- **Timeout waiting for OTP screen:** the login flow changed. Common cause: the user is already authenticated in the browser context (previous session or persistent cookies), so after password submission HH.ru redirects straight to `https://dev.hh.ru/admin` and never shows the OTP form. Fix: detect the dashboard early and skip OTP submission; or take a screenshot and proceed to reveal the token manually.
- **OTP digits do not appear after fill:** use the keyboard technique documented above. Do not rely on `fill()` for the HH.ru OTP field.
- **Region/cookie popup blocks OTP submission:** the script now dismisses "Ваш регион — Москва?" and the cookie banner before typing. If a new popup appears, add its close selector to `submit_otp()` and capture a screenshot.
- **Token extracted but API returns 403 `bad_authorization`:** the visible token is not revoked — it was likely copied incorrectly. Compare the `.env` value with the value from the admin UI/screenshot character-by-character. Typical mistakes: `0` vs `O`, `1` vs `l`, `I` vs `l`. Fix the mismatch and re-test before running the full renewal flow.
- **Token extracted but API returns 403 `token-revoked`:** the visible token is already revoked. Regenerate it manually in the admin panel, then re-run.
- **Cannot launch headed browser:** install Xvfb and use `xvfb-run -a python3 -u script.py`. The `-u` flag forces unbuffered stdout so the OTP prompt appears immediately in logs. Headless mode is less reliable with HH.ru's anti-bot checks.
- **Script failed before revealing token:** check the screenshot in `~/.hermes/screenshots/` for the exact page state. Also check `/tmp/hh_otp_screen.png` if the failure happened on the OTP screen.

## Verification after update

Always test the token immediately after writing it to `.env`:

```python
import json, urllib.request, urllib.parse

HH_APP_TOKEN=***  # value you just copied
HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"

params = urllib.parse.urlencode({"text": "AI Product Manager", "per_page": 1})
req = urllib.request.Request(
    f"https://api.hh.ru/vacancies?{params}",
    headers={"Authorization": f"Bearer {HH_APP_TOKEN}", "User-Agent": HH_USER_AGENT, "Accept": "application/json"},
)
with urllib.request.urlopen(req, timeout=20) as resp:
    print("status", resp.status)
    data = json.loads(resp.read())
    print("found", data.get("found"))
```

If this returns `200`, the token is valid and the scraper will work.

## Confidence

- High for "application token cannot be refreshed via public API" — verified against HH.ru OpenAPI spec.
- High for "DOM hides token from JS" — verified by browser console inspection.
- High for "OTP field requires keyboard digit input" — verified by screen analysis on 2026-07-06.
- Medium for "no regenerate button exists" — based on current UI; HH.ru may change this.

## References

- HH.ru API authorization docs: https://github.com/hhru/api/blob/master/docs/authorization_for_application.md
- HH.ru public OpenAPI spec: https://api.hh.ru/openapi/specification/public
- `references/hh-token-types-and-revocation.md` — token types and manual revocation handling.
