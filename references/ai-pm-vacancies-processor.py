#!/usr/bin/env python3
"""AI/PM vacancy processor: deterministic filter → Google Sheets → Telegram report.

Reads raw web_search results from stdin as JSON array, filters new vacancies
against ~/.hermes/vacancies/seen.json, writes to Google Sheets tab 'AI',
updates seen.json, and sends an HTML-formatted Telegram report.

If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not set, the report is printed
to stdout so the cron dispatcher can still deliver it (formatting depends on
the dispatcher).
"""
import html as html_mod
import json
import os
import re
import sys
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date

SEEN_PATH = os.path.expanduser("~/.hermes/vacancies/seen.json")
CREDS_PATH = os.path.expanduser("~/.config/gws/credentials.json")
SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"
SHEET_NAME = "AI"  # VERIFY this tab exists in the spreadsheet
COLS = ["date", "title", "company", "salary", "location", "level", "source", "url", "hash", "priority", "match"]

# Load Telegram credentials from env (preferred) or ~/.hermes/.env
def _load_env():
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") and key not in os.environ:
                    os.environ[key] = value.strip().strip('"').strip("'")

_load_env()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

JUNK_RE = re.compile(
    r"\b(data entry|virtual assistant|customer support|chat support|moderator|"
    r"content writer|translator|telemarketing|cold calling|sales representative|"
    r"social media manager)\b",
    re.I,
)

# Signals that the vacancy is archived/closed/suspended/expired/no longer active.
ARCHIVE_RE = re.compile(
    r"\b(в архиве|архивная|архив|удалена|закрыта|приостановлена|неактивна|не активна|"
    r"вакансия закрыта|вакансия не актуальна|вакансия в архиве|не принимаем|"
    r"архиве с \d{1,2}[\s\.][а-яa-z]+\s+\d{4}|"
    r"archived?|archived?\s+(?:since|from|on|at)|in archive|expired|closed|"
    r"no longer accepting|position (?:closed|filled)|vacancy closed|"
    r"not currently hiring|paused|suspended|on hold)\b",
    re.I,
)


def h(text: str) -> str:
    """Escape HTML special chars."""
    return html_mod.escape(str(text)) if text else ""


def send_telegram(text: str) -> dict:
    """Send an HTML-formatted message via Telegram Bot API (stdlib only)."""
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set; skipping Telegram send.", file=sys.stderr)
        return {"error": "missing token"}
    if not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID not set; skipping Telegram send.", file=sys.stderr)
        return {"error": "missing chat_id"}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR sending Telegram message: HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        print(f"ERROR sending Telegram message: {e}", file=sys.stderr)
        return {"error": str(e)}


def get_access_token():
    with open(CREDS_PATH) as f:
        creds = json.load(f)
    data = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())["access_token"]


def sheets_api(token, method, endpoint, body=None):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        req.get_method = lambda: method
    else:
        req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Sheets HTTP {e.code}: {e.read().decode()[:500]}")


def get_row_count(token):
    enc = urllib.parse.quote(f"{SHEET_NAME}!A:K", safe="")
    return len(sheets_api(token, "GET", f"values/{enc}").get("values", []))


def append_rows(token, next_row, rows):
    enc = urllib.parse.quote(f"{SHEET_NAME}!A{next_row}", safe="")
    body = {
        "range": f"{SHEET_NAME}!A{next_row}",
        "majorDimension": "ROWS",
        "values": rows,
    }
    return sheets_api(token, "PUT", f"values/{enc}?valueInputOption=RAW", body)


def url_hash(url: str) -> str:
    return hashlib.md5(url.split("?")[0].lower().encode()).hexdigest()[:8]


def is_active(title: str, description: str = "") -> bool:
    """Return False if the vacancy is archived, closed, suspended, or expired."""
    return not ARCHIVE_RE.search(f"{title} {description}".lower())


def is_management_or_senior(title: str) -> bool:
    t = title.lower()
    mgmt = re.search(r"\b(manager|lead|head|director|vp|chief|principal|staff)\b", t)
    senior = re.search(r"\b(senior|lead|staff|principal|expert)\b", t)
    junior = re.search(r"\b(junior|entry|intern|trainee)\b", t)
    if junior and not senior:
        return False
    if "developer" in t or "engineer" in t:
        return bool(senior)
    return bool(mgmt or senior)


def budget_ok(salary: str) -> bool:
    if not salary:
        return True
    s = salary.lower().replace(" ", "").replace("\u202f", "").replace(",", "")
    m = re.search(r"(\d[\d.k]*)\$?\s*(k?)(?:/(?:year|yr|hour|hr)|year)\b", s)
    if m:
        val = m.group(1).replace("k", "")
        mult = 1000 if "k" in m.group(2) else 1
        return float(val) * mult >= 100_000
    m = re.search(r"(\d[\d.k]*)\$?\s*(k?)\s*/\s*(?:hr|hour|h)\b", s)
    if m:
        val = m.group(1).replace("k", "")
        mult = 1000 if "k" in m.group(2) else 1
        return float(val) * mult >= 100
    m = re.search(r"\$(\d[\d.k]*)", s)
    if m:
        val = m.group(1).replace("k", "")
        mult = 1000 if "k" in m.group(1) else 1
        num = float(val) * mult
        return num >= 100 if num < 1000 else num >= 100_000
    return True


def priority_and_match(title: str) -> tuple:
    t = title.lower()
    if "ai" in t or "agentic" in t or "llm" in t:
        return "high", "AI в заголовке"
    if re.search(r"\b(product|project|program)\b", t) and re.search(r"\b(manager|lead|head|director|vp)\b", t):
        return "medium", "PM/управленец"
    if re.search(r"\b(automation|workflow|agent)\b", t):
        return "high", "AI-автоматизация"
    return "low", "смежная роль"


def parse_source(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    known = ["hh.ru", "superjob.ru", "career.habr.com", "geekjob.ru",
             "talent-move.ru", "hirify.me", "linkedin.com", "weworkremotely.com",
             "wellfound.com", "remoteok.com", "remotive.com", "arc.dev"]
    for d in known:
        if d in host:
            return d
    return host.replace("www.", "")


def enrich_result(item: dict) -> dict:
    url = item.get("url", "").strip()
    title = item.get("title", "").strip()
    desc = item.get("description", "").strip()
    if not url or not title:
        return None
    source = parse_source(url)
    company = ""
    if "@" in title:
        m = re.search(r"@\s*([^\s\-\(\[]+)", title)
        if m:
            company = m.group(1).strip(" -")
    if not company and " — " in title:
        company = title.split("—")[-1].strip()
    if not company:
        company = source
    salary = ""
    sal_re = re.compile(r"(\$[\d\s,\.\-]+[kK]?\s*(?:\/\s*(?:year|yr|hour|hr))?|\d+\s*000\s*₽|[\d\s]+\$)")
    m = sal_re.search(title) or sal_re.search(desc)
    if m:
        salary = m.group(1).strip()
    location = ""
    text = f"{title} {desc}".lower()
    for marker in ["remote", "worldwide", "usa", "us only", "europe", "uk", "canada", "moscow", "москва"]:
        if marker in text:
            location = marker.capitalize()
            break
    tlow = title.lower()
    level = (
        "head" if "head" in tlow else
        "director" if "director" in tlow else
        "principal" if "principal" in tlow else
        "staff" if "staff" in tlow else
        "senior" if "senior" in tlow else
        "lead" if "lead" in tlow else
        "junior" if any(w in tlow for w in ["junior", "intern"]) else
        "middle"
    )
    priority, match = priority_and_match(title)
    return {
        "date": datetime.now().strftime("%d.%m.%Y"),
        "title": title,
        "company": company,
        "salary": salary or "не указана",
        "location": location or "Remote / unspecified",
        "level": level,
        "source": source,
        "url": url,
        "hash": url_hash(url),
        "priority": priority,
        "match": match,
    }


def title_ok(title: str) -> bool:
    return not JUNK_RE.search(title)


def filter_new(results, seen):
    out = []
    for r in results:
        if not is_active(r.get("title", ""), r.get("description", "")):
            continue
        enriched = enrich_result(r)
        if not enriched:
            continue
        url = enriched["url"]
        if url in seen:
            continue
        if not title_ok(enriched["title"]):
            continue
        if not is_management_or_senior(enriched["title"]):
            continue
        if not budget_ok(enriched["salary"]):
            continue
        out.append(enriched)
    return out


def build_rows(vacancies):
    return [[v[c] for c in COLS] for v in vacancies]


def build_report(start_row, end_row, new, seen_total):
    today = datetime.now().strftime("%d.%m.%Y")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"

    if not new:
        return (
            f"<b>Вакансии AI/PM: {h(today)}</b>\n\n"
            f"Статус:\n✅ Выполнено\n"
            f"Новых вакансий нет. Всего в базе: {seen_total}."
        )

    lines = [
        f'<a href="{h(sheet_url)}">📊 Общая таблица</a>',
        "",
        f"<b>Вакансии AI/PM: {h(today)}</b>",
        "",
        "Статус:",
        "✅ Выполнено",
        f"Google Sheets обновлён: строки {start_row}–{end_row} на листе «{h(SHEET_NAME)}».",
        "",
        f"Новых вакансий: <b>{len(new)}</b> | Всего в базе: {seen_total}",
        "",
        "<b>🔥 ТОП-3 находки сегодня</b>",
    ]

    for v in new[:3]:
        lines.append(
            f'1. <a href="{h(v["url"])}">{h(v["title"])}</a> — {h(v["salary"])}'
        )
        lines.append(f"{h(v['company'])} // {h(v['location'])}")

    by_source = {}
    for v in new:
        by_source.setdefault(v["source"], []).append(v)

    lines.append("")
    for source, vs in sorted(by_source.items()):
        lines.append(f"<b>{h(source)}</b> ({len(vs)}):")
        for v in vs:
            lines.append(
                f'• <a href="{h(v["url"])}">{h(v["title"])}</a> — '
                f'{h(v["company"])}, {h(v["salary"])}, {h(v["location"])}'
            )

    return "\n".join(lines)


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return {}
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def main():
    stdin_data = sys.stdin.read().strip()
    if stdin_data:
        try:
            raw = json.loads(stdin_data)
            if not isinstance(raw, list):
                raw = [raw]
        except json.JSONDecodeError:
            raw = []
    else:
        raw = []

    seen = load_seen()
    new = filter_new(raw, seen)

    if new:
        token = get_access_token()
        row_count = get_row_count(token)
        next_row = row_count + 1
        append_rows(token, next_row, build_rows(new))
        end_row = next_row + len(new) - 1

        for v in new:
            seen[v["url"]] = {
                "title": v["title"], "company": v["company"], "salary": v["salary"],
                "location": v["location"], "level": v["level"], "source": v["source"],
                "url": v["url"], "first_seen": v["date"], "priority": v["priority"],
                "match": v["match"],
            }
        save_seen(seen)

        daily_path = os.path.expanduser(f"~/.hermes/vacancies/{date.today().isoformat()}.json")
        with open(daily_path, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=2)
    else:
        next_row = end_row = 0

    report = build_report(next_row, end_row, new, len(seen))
    send_result = send_telegram(report)

    # If Telegram is not configured, fall back to stdout so cron can still deliver
    if not send_result.get("ok"):
        print(report)


if __name__ == "__main__":
    main()
