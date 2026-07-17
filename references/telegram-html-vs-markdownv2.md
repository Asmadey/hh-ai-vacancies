# Telegram reports: HTML vs MarkdownV2

Date: 2026-06-29
Applies to: all vacancy-monitoring cron scripts that send reports to Telegram.

## Rule

Use `parse_mode="HTML"` for all cron-generated vacancy reports. Do not use MarkdownV2.

## Why

MarkdownV2 requires escaping reserved characters (`_`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`). When the message body is serialized with `json.dumps()` in Python, backslashes are doubled, so Telegram receives the unescaped character and returns:

```json
{"ok":false,"error_code":400,"description":"Bad Request: can't parse entities: Character '.' is reserved and must be escaped with the preceding '\\\\'"}
```

HTML mode avoids this entirely: only `<` and `>` need escaping (replace with spaces for titles), and URLs in `<a href="...">` just work.

## Example

```python
report = (
    f"<b>Sales & Event: {today}</b>\n\n"
    f"Новых вакансий: {count} | Всего в базе: {total}\n\n"
    f'🔗 <a href="{SHEET_URL}">Открыть таблицу</a>'
)

for chat_id in chat_ids:
    data = json.dumps({
        "chat_id": chat_id,
        "text": report,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=20)
```

## Handling blocked users

Telegram may return:

```json
{"ok":false,"error_code":403,"description":"Forbidden: bot was blocked by the user"}
```

Remove that `chat_id` from the registry automatically so future sends skip it and do not fail repeatedly. The user prefers an open-subscription bot; blocked users should be silently pruned, not left in a hardcoded allow-list. See `references/telegram-bot-patterns.md` for the implementation.

## Token diagnostics

- `401 Unauthorized` — wrong or revoked token; get a new one from @BotFather.
- `404 Not Found` — bot was deleted in Telegram; recreate it in @BotFather.
