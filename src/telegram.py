"""Telegram Bot API, parse_mode=HTML (не Markdown — см. references/telegram-html-vs-markdownv2.md)."""
import html
import json

from . import config, http_client


def esc(text):
    return html.escape(str(text), quote=False)


def _send(text):
    """sendMessage. Returns True on HTTP 200. Также печатает в stdout (Hermes deliver: origin)."""
    print(text)
    token, chat_id = config.telegram_bot_token(), config.telegram_chat_id()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    try:
        resp = http_client.request("POST", url, headers={"Content-Type": "application/json"}, data=payload)
        return resp.status == 200
    except http_client.NetworkError:
        return False


def send_alert(text):
    return _send(text)


def format_report(m):
    """m: dict с агрегатами прогона. 5 чисел отчёта == агрегаты JSON (TC-14)."""
    lines = [
        f"<b>HH.ru AI автоотклики: {esc(m['date'])}</b>",
        "",
        f"🔍 Найдено: <b>{m['found']}</b>",
        f"🆕 Новых: <b>{m['new']}</b>",
        f"✉️ Cover letters: <b>{m['covers']}</b>",
        f"🚀 Отправлено: <b>{m['sent']}</b>",
        f"📝 С тестами: <b>{m['tests']}</b>",
        "",
        f'🔗 <a href="{config.SHEET_URL}">Открыть таблицу</a>',
    ]
    if m.get("dry_run"):
        lines.insert(1, "<i>DRY_RUN — реальные отклики не отправлялись</i>")
    if m.get("not_sent"):
        lines.append(f"⚠️ Не отправлено: {m['not_sent']} (перенос на следующий прогон)")
    return "\n".join(lines)


def send_report(metrics):
    return _send(format_report(metrics))
