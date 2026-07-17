# Telegram bot patterns for vacancy alerts

Date: 2026-07-10
Applies to: cron-driven vacancy trackers that deliver reports through a Telegram bot.

## Open subscription model

The user explicitly prefers an **open-subscription** model: anyone who messages the bot should receive notifications. Do not rely on a hardcoded allow-list.

Implementation:

1. Keep a registry file (e.g. `~/.hermes/sales-event-bot-chats.json`).
2. Before each send, call `https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset=0`.
3. Extract `chat.id` and `from.id` from every `message`, `edited_message`, `channel_post`, `edited_channel_post`, and `callback_query`.
4. Merge collected IDs with the registry (union, sorted).
5. Write the merged list back to the registry.
6. Send the report to every ID in the registry.

```python
def collect_chat_ids():
    if not BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset=0"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"[Telegram] collect_chat_ids failed: {e}", file=sys.stderr)
        return []

    collected = set()
    for upd in data.get("result", []):
        for key in ("message", "edited_message", "channel_post", "edited_channel_post", "callback_query"):
            obj = upd.get(key)
            if not obj:
                continue
            if key == "callback_query":
                user = obj.get("from")
                if user:
                    collected.add(user.get("id"))
            else:
                chat = obj.get("chat")
                if chat:
                    collected.add(chat.get("id"))
                user = obj.get("from")
                if user:
                    collected.add(user.get("id"))

    existing = []
    if os.path.exists(CHAT_IDS_FILE):
        try:
            with open(CHAT_IDS_FILE, encoding="utf-8") as fh:
                existing = json.load(fh)
        except Exception:
            existing = []

    merged = sorted(set(existing) | collected)
    if merged != existing:
        try:
            os.makedirs(os.path.dirname(CHAT_IDS_FILE), exist_ok=True)
            with open(CHAT_IDS_FILE, "w", encoding="utf-8") as fh:
                json.dump(merged, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Telegram] Failed to write chat ids: {e}", file=sys.stderr)
    return merged
```

## Automatic removal of blocked users

When a recipient blocks the bot, Telegram returns:

```json
{"ok":false,"error_code":403,"description":"Forbidden: bot was blocked by the user"}
```

Remove that `chat_id` from the registry automatically so future sends skip it and do not fail repeatedly.

```python
def send_telegram(report):
    chats = collect_chat_ids()
    if not BOT_TOKEN or not chats:
        return set()

    removed = set()
    remaining = []
    for chat_id in chats:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": chat_id,
            "text": report,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.load(resp)
            if not result.get("ok"):
                print(f"[Telegram] Failed to {chat_id}: {result.get('description')}", file=sys.stderr)
            remaining.append(chat_id)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()[:500]
            print(f"[Telegram] HTTP Error {e.code} to {chat_id}: {err_body}", file=sys.stderr)
            if e.code == 403 and "bot was blocked by the user" in err_body:
                print(f"[Telegram] Removing blocked chat_id {chat_id}", file=sys.stderr)
                removed.add(chat_id)
            else:
                remaining.append(chat_id)
        except Exception as e:
            print(f"[Telegram] Error to {chat_id}: {e}", file=sys.stderr)
            remaining.append(chat_id)

    if removed:
        try:
            with open(CHAT_IDS_FILE, "w", encoding="utf-8") as fh:
                json.dump(remaining, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Telegram] Failed to update chat ids: {e}", file=sys.stderr)
    return removed
```

## Alert on access / scrape failures

The user explicitly expects notification when a scraper cannot fetch data or hits an access error ("We agreed that if you can't scrape or there's an access error, you notify me.").

Rules:

1. Do not silently print the error only to stdout. Send a Telegram alert with the same bot/token.
2. Distinguish error types:
   - **HH.ru application token revoked** → alert with exact next step: regenerate token at https://dev.hh.ru/admin, then update `HH_APP_TOKEN` in `~/.hermes/.env`.
   - **Generic API/network error** → alert with the error reason and a reminder to check token / User-Agent.
3. Keep the alert concise and actionable.

Example:

```python
if api_error and not new_vacancies:
    today_str = datetime.now().strftime("%d.%m.%Y")
    if HH_TOKEN_REVOKED:
        alert = (
            f"<b>Sales & Event: {today_str}</b>\n\n"
            "⚠️ HH.ru application token отозван.<br>"
            "Обнови токен вручную: https://dev.hh.ru/admin → настройки приложения → сгенерировать новый.<br>"
            "Затем обнови HH_APP_TOKEN в ~/.hermes/.env."
        )
    else:
        alert = (
            f"<b>Sales & Event: {today_str}</b>\n\n"
            f"⚠️ Не удалось получить данные с HH.ru<br>"
            f"Причина: {api_error}<br><br>"
            "Проверь токен / User-Agent."
        )
    print(alert)
    send_telegram(alert)
    return
```

## Token diagnostics quick reference

- `401 Unauthorized` — wrong or revoked token; get a new one from @BotFather.
- `404 Not Found` — bot was deleted in Telegram; recreate it in @BotFather.
- `403 Forbidden: bot was blocked by the user` — remove chat_id from registry.
- `400 Bad Request: can't parse entities` — switch from MarkdownV2 to HTML; see `telegram-html-vs-markdownv2.md`.
