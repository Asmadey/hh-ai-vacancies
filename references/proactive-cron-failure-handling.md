# Proactive cron failure handling — user expectation

Date: 2026-07-10/11
Skill: vacancy-monitoring
Source: user correction in session `20260710_143443_25b87ab6` and follow-up `20260711_220620_f6a335a9`.

## User statement

"А ты прислал мне уведомление, что ты упал и не смог получить доступ? Мы договаривались, что если что-то не получается заскрепить или какая-то ошибка доступа, то ты меня уведомляешь."

And in the HH token session the user expected the assistant to "самому написать скрипт, который будет работать с этими токенами и дергать refresh token" rather than just report the failure.

## What this means in practice

When a cron job or automated pipeline fails, the assistant must:

1. **Try to fix it autonomously first.** Update scripts, refresh credentials, adjust selectors, switch fallbacks — whatever is needed to restore the pipeline.
2. **Notify the user clearly** if the fix requires the user's input (OTP, new token, bot token, etc.) or if autonomous repair is not possible.
3. **Never silently log the error to stdout only.** Cron stdout may not be delivered; use explicit Telegram alerts or the configured `deliver` channel.

## Pattern for vacancy trackers

- If an API token is revoked, attempt renewal via the existing Playwright updater (`hh_token_updater.py`).
- If renewal needs OTP, start it in the background and ask the user for the OTP.
- If the token is an application token that cannot be auto-refreshed (no OAuth refresh flow), explain why and request the new token from the admin UI.
- If a Telegram bot token is invalid (404/401), diagnose and ask for the correct token; do not leave the bot in a broken state.
- If source selectors change, test existing local scripts first, patch them, and re-run before declaring a blocker.

## Implementation checklist

- [ ] All scraper errors surface as Telegram alerts, not just stderr logs.
- [ ] Token/credential errors trigger the renewal flow automatically when possible.
- [ ] User is only bothered when human input is actually required.
- [ ] After a fix, a test run confirms the pipeline is healthy.

## Related references

- `references/telegram-bot-patterns.md`
- `references/hh-token-types-and-revocation.md`
- `hh-ru-token-management` skill
