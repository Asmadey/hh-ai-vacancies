#!/usr/bin/env python3
"""
Template: HeadHunter vacancy scraper → Google Sheets → Telegram report.
Copy this, adjust KEYWORDS, SHEET_NAME/SHEET_GID and report format.
Default column layout: 9 columns (date, title, company, salary, location, level, url, match, cover-letter).
Dedup is URL-based. Cover letters are generated from resume + full vacancy description via Ollama Cloud.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STATE_FILE = "/home/hermes/.hermes/{PROJECT}_seen.json"
SEEN_EXPIRE_DAYS = 30

HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"
HH_APP_TOKEN = os.environ.get("HH_APP_TOKEN", "")

SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"
SHEET_NAME = "HH_AI"
SHEET_GID = 0  # replace with real gid
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_GID}"

RESUME_PATH = os.path.expanduser("~/.hermes/skills/hh-cover-letters/references/resume.md")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ministral-3:8b")
COVER_LETTER_LIMIT = int(os.environ.get("COVER_LETTER_LIMIT", "0"))  # 0 = all
COVER_LETTER_MAX_TOKENS = int(os.environ.get("COVER_LETTER_MAX_TOKENS", "600"))
COVER_LETTER_TEMP = float(os.environ.get("COVER_LETTER_TEMP", "0.4"))
COVER_LETTER_WORKERS = int(os.environ.get("COVER_LETTER_WORKERS", "10"))

KEYWORDS = [
    "KEYWORD 1",
    "KEYWORD 2",
]

JUNK_RE = re.compile(
    r"\b(data entry|virtual assistant|customer support|chat support|moderator|"
    r"content writer|translator|telemarketing|cold calling|sales representative|"
    r"social media manager)\b",
    re.I,
)

RESUME_RE = re.compile(
    r"\b(резюме|resume|cv|curriculum vitae|ищу работу|open to work|available for hire|"
    r"looking for (?:a )?(?:job|position|role|opportunity))\b",
    re.I,
)

ARCHIVE_RE = re.compile(
    r"\b(в архиве|архивная|архив|удалена|закрыта|приостановлена|неактивна|не активна|"
    r"вакансия закрыта|вакансия не актуальна|вакансия в архиве|"
    r"archived?|in archive|expired|closed|no longer accepting|position closed|"
    r"vacancy closed|not currently hiring|paused|suspended|on hold)\b",
    re.I,
)

REPORT_COLUMNS = ["date", "title", "company", "salary", "location", "level", "url", "match", "cover-letter"]

# ---------------------------------------------------------------------------
# HH API
# ---------------------------------------------------------------------------
def hh_api(url, timeout=20):
    headers = {"User-Agent": HH_USER_AGENT, "Accept": "application/json"}
    if HH_APP_TOKEN:
        headers["Authorization"] = f"Bearer {HH_APP_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def search_vacancies(text, per_page=50, page=0):
    params = {
        "text": text,
        "search_field": "name",
        "per_page": per_page,
        "page": page,
        "order_by": "publication_time",
    }
    url = "https://api.hh.ru/vacancies?" + urllib.parse.urlencode(params)
    return hh_api(url)


def get_vacancy_details(vacancy_id):
    data = hh_api(f"https://api.hh.ru/vacancies/{vacancy_id}")
    parts = []
    name = data.get("name", "").strip()
    if name:
        parts.append(f"Название: {name}")
    description = re.sub(r"<[^>]+>", " ", data.get("description", "") or "").strip()
    description = re.sub(r"\s+", " ", description)
    if description:
        parts.append(f"Описание: {description}")
    experience = data.get("experience", {}).get("name", "")
    if experience:
        parts.append(f"Опыт: {experience}")
    employment = data.get("employment", {}).get("name", "")
    schedule = data.get("schedule", {}).get("name", "")
    if employment or schedule:
        parts.append(f"Занятость: {employment} {schedule}".strip())
    key_skills = ", ".join(s.get("name", "") for s in data.get("key_skills", []))
    if key_skills:
        parts.append(f"Ключевые навыки: {key_skills}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Cover letter generation
# ---------------------------------------------------------------------------
def load_resume():
    if os.path.exists(RESUME_PATH):
        with open(RESUME_PATH, encoding="utf-8") as fh:
            return fh.read()
    return ""


def call_ollama_chat(system_prompt, user_prompt):
    if not OLLAMA_API_KEY:
        return ""
    url = f"{OLLAMA_BASE_URL}/chat/completions"
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": COVER_LETTER_TEMP,
        "max_tokens": COVER_LETTER_MAX_TOKENS,
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {OLLAMA_API_KEY}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.load(resp)
        msg = data.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "").strip()
        if not content:
            content = msg.get("reasoning", "").strip()
        return content
    except Exception as e:
        print(f"[Cover Letter] Ollama error: {e}", file=sys.stderr)
        return ""


def clean_cover_letter(text):
    text = re.sub(r"\*\*|\*|__|`", "", text)
    text = re.sub(r"[—–]", "-", text)
    # Force greeting on its own line
    text = re.sub(r"^(Здравствуйте!)[ \t]*", r"\1\n\n", text, count=1)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Strip signature noise and incomplete trailing paragraphs
    text = re.sub(r"\n*(?:Влад\.?|С уважением,?.*?|Best,.*)?\s*$", "", text, flags=re.S).strip()
    if "\n\n" in text:
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        while parts and not parts[-1].endswith((".", "!", "?")):
            parts.pop()
        text = "\n\n".join(parts)
    # Deterministic closing
    closing = "Буду рад короткому созвону, чтобы обсудить детали."
    text = re.sub(r"\n+Буду рад[^.!?]*$", "", text, flags=re.S).strip()
    if closing not in text:
        text = text + "\n\n" + closing
    return text


def generate_cover_letter(title, company, salary, location, match, url, resume_text):
    vacancy_id = None
    m = re.search(r"/vacancy/(\d+)", url)
    if m:
        vacancy_id = m.group(1)
    vacancy_details = ""
    if vacancy_id:
        try:
            vacancy_details = get_vacancy_details(vacancy_id)
        except Exception as e:
            print(f"[Cover Letter] Failed to fetch details for {url}: {e}", file=sys.stderr)

    system_prompt = f"""Ты — профессиональный рекрутер, который пишет сопроводительные письма от лица кандидата. Отвечай ТОЛЬКО готовым текстом письма. Никаких пояснений, планов, драфтов, разборов правил.

Жёсткие правила:
1. Начинай строго со слова "Здравствуйте!" (восклицательный знак, без обращения к компании).
2. Ровно 2 абзаца, разделённые пустой строкой.
3. 1 абзац: 1 предложение, почему опыт подходит. БЕЗ фраз "откликаюсь потому что", "откликнулся на вакансию", "вакансия интересна", "именно", "как раз".
4. 2 абзац: 1-2 конкретных кейса из резюме. Только факты и инструменты, которые есть в резюме. НЕ выдумывай цифры, проценты, технологии. НЕ пиши, что ты работал в компании из вакансии ({company}).
5. НЕ пиши подпись. НЕ пиши "Влад", "Влад.", "С уважением, Влад", "Best" и т.п.
6. Длина: 60-100 слов. Короткие предложения.
7. Без markdown (**), жирного, курсива, списков, длинного тире "—".
8. Стиль: разговорный, уважительный. Как письмо знакомому коллеге.

Резюме:
{resume_text}
"""

    user_prompt = f"""Вакансия: {title}
Компания: {company}
Формат: {match}

Требования и задачи:
{vacancy_details or '(описание недоступно)'}

Напиши готовое сопроводительное письмо.
"""

    letter = call_ollama_chat(system_prompt, user_prompt)
    if letter:
        return clean_cover_letter(letter)
    return ""


# Cover letter source note
# The user prompt above uses the FULL vacancy description from GET /vacancies/{id}.
# Do NOT rely on the search-result snippet — it is truncated to ~200-300 chars.


# ---------------------------------------------------------------------------
# Google Sheets helpers
# ---------------------------------------------------------------------------
def get_access_token():
    creds_path = os.path.expanduser("~/.config/gws/credentials.json")
    with open(creds_path) as fh:
        creds = json.load(fh)
    token_data = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["access_token"]


def get_sheet_name(access_token, gid=SHEET_GID):
    req = urllib.request.Request(f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}")
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req) as resp:
        info = json.load(resp)
    for sheet in info.get("sheets", []):
        if sheet["properties"]["sheetId"] == gid:
            return sheet["properties"]["title"]
    return None


def get_row_count(access_token, sheet_name):
    enc = urllib.parse.quote(f"{sheet_name}!A:I", safe="")
    req = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}"
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req) as resp:
        return len(json.load(resp).get("values", []))


def ensure_header(access_token, sheet_name):
    enc = urllib.parse.quote(f"{sheet_name}!A1:I1", safe="")
    req = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}"
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    values = data.get("values", [])
    if not values or values[0] != REPORT_COLUMNS:
        body = json.dumps({
            "range": f"{sheet_name}!A1:I1",
            "majorDimension": "ROWS",
            "values": [REPORT_COLUMNS],
        }).encode()
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}?valueInputOption=RAW"
        req2 = urllib.request.Request(url, data=body, method="PUT")
        req2.add_header("Authorization", f"Bearer {access_token}")
        req2.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req2) as resp:
            return json.load(resp)
    return None


def append_rows(access_token, sheet_name, next_row, rows):
    enc = urllib.parse.quote(f"{sheet_name}!A{next_row}", safe="")
    body = json.dumps({
        "range": f"{sheet_name}!A{next_row}",
        "majorDimension": "ROWS",
        "values": rows,
    }).encode()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}?valueInputOption=RAW"
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


# ---------------------------------------------------------------------------
# Enrichment / filtering
# ---------------------------------------------------------------------------
def format_salary(salary):
    if not salary:
        return "не указана"
    parts = []
    if salary.get("from"):
        parts.append(f"от {salary['from']:,}")
    if salary.get("to"):
        parts.append(f"до {salary['to']:,}")
    out = " ".join(parts)
    if salary.get("currency"):
        out += f" {salary['currency']}"
    if salary.get("gross") is not None:
        out += " gross" if salary["gross"] else " net"
    return out or "не указана"


def parse_level(title):
    t = title.lower()
    if any(x in t for x in ["head", "директор", "director", "руководитель направления"]):
        return "head"
    if any(x in t for x in ["lead", "руководитель", "ведущий"]):
        return "lead"
    if "senior" in t or "старший" in t:
        return "senior"
    if any(x in t for x in ["principal", "staff"]):
        return "principal"
    if any(x in t for x in ["junior", "младший", "intern", "стажер"]):
        return "junior"
    return "middle"


def priority_and_match(title, snippet=""):
    # Override per project
    return "medium", "relevant"


def enrich(item):
    title = item.get("name", "").strip()
    url = item.get("alternate_url", "").strip()
    if not title or not url:
        return None
    snippet = item.get("snippet", {}).get("requirement", "") or ""
    priority, match = priority_and_match(title, snippet)
    return {
        "date": datetime.now().strftime("%d.%m.%Y"),
        "title": title,
        "company": item.get("employer", {}).get("name", ""),
        "salary": format_salary(item.get("salary")),
        "location": item.get("area", {}).get("name", "Remote / unspecified"),
        "level": parse_level(title),
        "url": url,
        "match": match,
    }


def is_relevant(title, snippet=""):
    text = f"{title} {snippet}".lower()
    has_kw = any(kw.lower() in text for kw in KEYWORDS)
    if not has_kw:
        return False
    if JUNK_RE.search(title) or RESUME_RE.search(title):
        return False
    return True


def is_active(title, snippet=""):
    return not ARCHIVE_RE.search(f"{title} {snippet}")


# ---------------------------------------------------------------------------
# State / dedup
# ---------------------------------------------------------------------------
def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to load seen: {e}", file=sys.stderr)
    return {}


def save_seen(seen):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, ensure_ascii=False, indent=2)


def dedup(vacancies, seen):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=SEEN_EXPIRE_DAYS)
    cleaned = {}
    for url, ts in seen.items():
        try:
            if datetime.fromisoformat(ts) > cutoff:
                cleaned[url] = ts
        except Exception:
            pass
    new = []
    for v in vacancies:
        url = v["url"]
        if url not in cleaned:
            new.append(v)
            cleaned[url] = now.isoformat()
    return new, cleaned


# ---------------------------------------------------------------------------
# Telegram report (MarkdownV2)
# ---------------------------------------------------------------------------
def escape_md_v2(text):
    return re.sub(r"([_\[\]\(\)~`>#+=|{}\.!])", r"\\\1", text)


def format_telegram(new_vacancies, total_rows, max_jobs=5):
    today_str = datetime.now().strftime("%d.%m.%Y")
    sheet_link = f"[Открыть таблицу]({SHEET_URL})".replace(".", "\\.")
    if not new_vacancies:
        return f"*HH\\.ru: {today_str}*\n\nНовых: 0 \\| Всего: {total_rows}\n\n🔗 {sheet_link}"
    lines = [
        f"*HH\\.ru: {today_str}*",
        "",
        f"Новых: {len(new_vacancies)} \\| Всего: {total_rows}",
        "",
        f"🔗 {sheet_link}",
        "",
        "====",
        "",
        f"🔥 *ТОП\\-{min(len(new_vacancies), max_jobs)}*",
    ]
    for i, v in enumerate(new_vacancies[:max_jobs], 1):
        title = escape_md_v2(v["title"].replace("]", " ").replace("[", " ").strip())
        url = v["url"].replace(")", "%29")
        lines.append(
            f"{i}\\. [{title}]({url})\n"
            f"🏢 {escape_md_v2(v['company'] or '—')}  \\|  💰 {escape_md_v2(v['salary'])}  \\|  📍 {escape_md_v2(v['location'])}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_vacancies = []
    for kw in KEYWORDS:
        try:
            data = search_vacancies(kw, per_page=50, page=0)
            for it in data.get("items", []):
                v = enrich(it)
                if not v:
                    continue
                snippet = it.get("snippet", {}).get("requirement", "") or ""
                if is_active(v["title"], snippet) and is_relevant(v["title"], snippet):
                    all_vacancies.append(v)
        except Exception as e:
            print(f"[ERROR] '{kw}': {e}", file=sys.stderr)

    seen_urls = set()
    unique = [v for v in all_vacancies if not (v["url"] in seen_urls or seen_urls.add(v["url"]))]

    seen = load_seen()
    new_vacancies, updated_seen = dedup(unique, seen)
    save_seen(updated_seen)

    # Generate cover letters in parallel
    resume_text = load_resume()
    limit = COVER_LETTER_LIMIT or len(new_vacancies)

    def _gen(idx_v):
        i, v = idx_v
        if i >= limit:
            return i, ""
        letter = generate_cover_letter(
            v["title"], v["company"], v["salary"], v["location"], v["match"], v["url"], resume_text
        )
        return i, letter

    with ThreadPoolExecutor(max_workers=min(COVER_LETTER_WORKERS, limit or 1)) as exe:
        futures = {exe.submit(_gen, (i, v)): i for i, v in enumerate(new_vacancies)}
        for fut in as_completed(futures):
            i, letter = fut.result()
            new_vacancies[i]["cover-letter"] = letter

    total_rows = 0
    token = get_access_token()
    if token:
        sheet_name = get_sheet_name(token)
        if sheet_name:
            ensure_header(token, sheet_name)
            total_rows = get_row_count(token, sheet_name)
            if new_vacancies:
                next_row = total_rows + 1
                rows = [[v[c] for c in REPORT_COLUMNS] for v in new_vacancies]
                append_rows(token, sheet_name, next_row, rows)

    print(format_telegram(new_vacancies, total_rows))


if __name__ == "__main__":
    main()
