#!/usr/bin/env python3
"""
HeadHunter → Telegram: native API scraper for AI-related vacancies.
Searches by keywords, dedups via seen.json, writes to Google Sheets HH_AI tab, sends Telegram report.
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
# Load Hermes .env into environment for cron runs
# ---------------------------------------------------------------------------
def _load_hermes_env():
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            # Remove surrounding quotes if present
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val

_load_hermes_env()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STATE_FILE = "/home/hermes/.hermes/hh_ai_seen.json"
SEEN_EXPIRE_DAYS = 30

HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"
HH_APP_TOKEN = os.environ.get("HH_APP_TOKEN", "")

# Set to True when HH returns token-revoked. Stops further API calls and prints a clear user message.
HH_TOKEN_REVOKED = False
HH_TOKEN_REVOKED_MESSAGE = (
    "⚠️ HH\\.ru application token отозван. "
    "Обнови токен вручную: https://dev\\.hh\\.ru/admin → настройки приложения → сгенерировать новый. "
    "Затем обнови HH\\_APP\\_TOKEN в ~/.hermes/.env или в скрипте."
)

SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"
SHEET_NAME = "HH_AI"
SHEET_GID = 1464494667
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_GID}"

RESUME_PATH = os.path.expanduser("~/.hermes/skills/hh-cover-letters/references/resume-short.md")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-v4-flash")
COVER_LETTER_LIMIT = int(os.environ.get("COVER_LETTER_LIMIT", "0"))  # 0 = all new vacancies
COVER_LETTER_MAX_TOKENS = int(os.environ.get("COVER_LETTER_MAX_TOKENS", "900"))
COVER_LETTER_TEMP = float(os.environ.get("COVER_LETTER_TEMP", "0.4"))
COVER_LETTER_WORKERS = int(os.environ.get("COVER_LETTER_WORKERS", "10"))

KEYWORDS = [
    "Product AI",
    "AI Lead",
    "AI Transformation Lead",
    "AI Product Manager",
    "Владелец AI продукта",
    "Руководитель по внедрению AI",
    "AI-First",
    "Специалист по внедрению ИИ",
    "директор по продукту",
    "Product Director",
    "Chief Product Officer",
    "CPO",
    "Head of Product",
]

JUNK_RE = re.compile(
    r"\b(data entry|virtual assistant|customer support|chat support|moderator|"
    r"content writer|translator|telemarketing|cold calling|sales representative|"
    r"social media manager|курьер|водитель|охранник|уборщица|кассир|продавец|"
    r"sales manager|smm|designer|developer|analyst|engineer|дизайнер|разработчик|"
    r"аналитик|инженер)\b",
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

REPORT_COLUMNS = ["date", "title", "company", "salary", "location", "level", "url", "match", "cover-letter", "respond"]

# ---------------------------------------------------------------------------
# Resume context
# ---------------------------------------------------------------------------
RESUME = """
AI Lead в PROSHINSKY AI (Июль 2025 — Июнь 2026)
Цель: Внедрение genAI-инструментов и автоматизация бизнес-процессов на базе no-code/low-code стека с ответственностью за рост бизнес метрик.
Обязанности:
- Проводил аудиты бизнес-процессов (продажи, маркетинг, операционка)
- Собирал и согласовывал требования с руководителями
- Проводил расчеты экономии и роста эффективности от внедрений (юнит, PnL)
- Приоритизация и защита эффектов перед заказчиком (в основном основатели)
- Проектирование ИИ пайплайнов (input/output, reasoning steps, tools, mcp)
- Prompt engineering (CoVe, Role-based, Structured Thinking)
- Запуск и отладка агентов (трейсинг, мониторинг, evals)
- Обучение сотрудников работе с AI-инструментами
Кейсы:
- отдел контроля качества звонков на базе ИИ
- автоматическая отчетность ЛПР (сводка из систем + анализ + отправка)
- мониторинг цен (SKU price monitoring) на базе n8n с Tavily, Firecrawl
- RAG чатботы (Pinecone, Qdrant)
- голосовой ИИ агент для обзвона и приёма входящих звонков на базе Retell
- AI SEO pipeline, генератор изображений с UI, 3PL админка
- мониторинг проектов на ProductHunt, анализ входящих писем, парсинг вакансий
+15 автоматизаций с доказанным эффектом
Навыки: SGR, RAG, PydanticAI, MCP, tool-call, computer-use, browser-use, Voice agents (Retell, Hume)
Инструменты: LangChain, Langraph, n8n, CrewAI, Langfuse + evals, OpenClaw, Claude Cowork, Paperclip

Lead Product Manager (B2B и B2C) в dellin.ru (Август 2023 — Июнь 2025)
Отвечал за PnL и CSI в digital-каналах (сайт, 2 моб. приложения: b2c, b2b) c MAU >1.5 млн.
Результаты: рост онлайн-выручки +25%/год, экономия >100 млн/год на обслуживании, сокращение сервисных операций на 12%, CSI 8.0 → 9.1.
Управлял 5 продуктовыми командами (>60 чел.), нанял 5 РО, 3 БА, Лида аналитиков, Agile коуча.

Lead Product Manager (Mobile Apps) в rutube.ru (Февраль 2022 — Июль 2023)
Ответственный за рост моб. приложения (iOS, Android), MAU 5M+.
Результаты: MAU х10 (200 тыс. → 2 млн), удержание 30d +21%, время просмотра +20%, crash-free 99.8%, CSI +22%.

CPO / Head of Product (B2C) в SOKOLOV (Май 2021 — Февраль 2022)
Ответственный за онлайн PnL в Web (MAU 2M), App (MAU 2,4M).
Результаты: CR2 +30% Web / +27% App, CR3 +25% Web / +18% App, NPS +11%, удержание +21%, Time to Market -20%.

Lead Product Manager в Интернет-магазин Ozon.ru (Февраль 2020 — Май 2021)
Продакт лид высоконагруженных систем: контент-платформа (загрузка SKU в 20 раз быстрее), модерация (скорость x4, точность +20%), платформа заданий (MVP за 2 недели), Product service (p99 latency 1.2s → 350ms, RPS +40%), Ozon Profit (SaaS для самозанятых).
"""

CASE_TEMPLATES = [
    {
        "signals": ["контроль качества", "оценка звонков", "qa", "quality", "колл-центр", "звонки"],
        "case": "Внедрил отдел контроля качества звонков на базе ИИ: аудит процессов, пайплайн оценки, трейсинг и evals. Результат — масштабируемая AI-QA система."
    },
    {
        "signals": ["отчет", "отчетность", "лидер", "лпр", "dashboard", "analytics", "dashboards", "сводка"],
        "case": "Собрал автоматическую отчетность для ЛПР: агрегация данных из систем, анализ и отправка. Экономит часы руководителей ежедневно."
    },
    {
        "signals": ["мониторинг цен", "price monitoring", "ску", "sku", "pricing", "цены"],
        "case": "Реализовал мониторинг цен SKU на базе n8n + Tavily + Firecrawl: сбор, дедупликация, алерты. Работает автономно."
    },
    {
        "signals": ["rag", "чатбот", "chatbot", "бот", "ассистент", "консультант", "knowledge base"],
        "case": "Запускал RAG-чатботов на Pinecone и Qdrant: индексация базы знаний, ретривал, генерация ответов."
    },
    {
        "signals": ["голос", "voice", "звонки", "retell", "hume", "обзвон", "входящие звонки"],
        "case": "Создал голосового ИИ-агента для обзвона и приёма входящих звонков на Retell: интеграция, тесты, мониторинг."
    },
    {
        "signals": ["seo", "контент", "content", "генерация контента", "автоматизация маркетинга"],
        "case": "Собрал AI SEO pipeline: исследование, генерация, публикация. Снижает рутину контент-команды."
    },
    {
        "signals": ["мобильное приложение", "mobile app", "ios", "android", "mau", "удержание"],
        "case": "В RuTube вырос MAU мобильного приложения с 200K до 2M, удержание 30d +21%, crash-free 99.8%."
    },
    {
        "signals": ["b2b", "saaS", "платформа", "marketplace", "экосистема"],
        "case": "В Ozon лидировал 5 высоконагруженных B2B/B2C продуктов, в том числе контент-платформу с ростом скорости загрузки SKU в 20 раз."
    },
    {
        "signals": ["ai transformation", "ai-трансформация", "внедрение ии", "внедрение ai", "автоматизация процессов", "no-code", "n8n"],
        "case": "AI Lead в PROSHINSKY AI: аудиты процессов, проектирование ИИ-пайплайнов, запуск агентов, обучение команд. +15 автоматизаций с доказанным эффектом."
    },
]

INTRO_TEMPLATE = """Здравствуйте!"""

BODY_TEMPLATE = """Я внедрял genAI-инструменты и автоматизацию бизнес-процессов на no-code/low-code стеке в роли AI Lead в PROSHINSKY AI: аудиты процессов, проектирование ИИ-пайплайнов, запуск агентов с трейсингом и evals, обучение команд. Этот опыт пересекается с задачами роли {title}.

{selected_cases}

Готов обсудить, какой конкретно эффект могу принести в {company} в первые 30/60/90 дней."""

CLOSE_TEMPLATE = """Буду рад созвону, чтобы уточнить ожидания и поделиться релевантными кейсами."""

# ---------------------------------------------------------------------------
# Cover letter generation
# ---------------------------------------------------------------------------
def select_cases(title, company):
    text = f"{title} {company}".lower()
    matched = []
    for ct in CASE_TEMPLATES:
        score = sum(1 for sig in ct["signals"] if sig in text)
        if score:
            matched.append((score, ct["case"]))
    if not matched:
        matched.append((1, "AI Lead в PROSHINSKY AI: аудиты процессов, проектирование ИИ-пайплайнов, запуск агентов, обучение команд. +15 автоматизаций с доказанным эффектом."))
    matched.sort(key=lambda x: -x[0])
    cases = [c for _, c in matched[:3]]
    return "\n\n".join(f"• {c}" for c in cases)


def generate_cover_letter(title, company, salary, location, match, url, resume_text):
    # Try to fetch full vacancy details from HH API
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
2. Ровно 2 абзаца, разделённые пустой строкой. НЕ в одном абзаце.
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

{vacancy_details}

Напиши готовое сопроводительное письмо.
"""
    raw = call_ollama_chat(system_prompt, user_prompt)
    if raw:
        print(f"[Cover Letter RAW for {title}] {len(raw.split())} words", file=sys.stderr)
        if int(os.environ.get("COVER_LETTER_DEBUG", "0")):
            print(f"[Cover Letter RAW TEXT] {raw!r}", file=sys.stderr)
    cleaned = clean_cover_letter(raw) if raw else ""
    if int(os.environ.get("COVER_LETTER_DEBUG", "0")):
        print(f"[Cover Letter CLEANED] {cleaned!r}", file=sys.stderr)
    # Ensure deterministic closing
    closing = "Буду рад короткому созвону, чтобы обсудить детали."
    cleaned = re.sub(r"\n+Буду рад[^.!?]*$", "", cleaned, flags=re.S).strip()
    if closing not in cleaned:
        cleaned = cleaned + "\n\n" + closing
    return cleaned


def get_vacancy_id_from_url(url):
    m = re.search(r"/vacancy/(\d+)", url)
    return m.group(1) if m else None


def get_vacancy_details(vacancy_id):
    url = f"https://api.hh.ru/vacancies/{vacancy_id}"
    data = hh_api(url)
    parts = []
    name = data.get("name", "").strip()
    if name:
        parts.append(f"Название: {name}")
    description = data.get("description", "") or ""
    # Strip HTML tags crudely
    description = re.sub(r"<[^>]+>", " ", description)
    description = re.sub(r"\s+", " ", description).strip()
    # Truncate to keep prompt within token budget
    if len(description) > 2500:
        description = description[:2500].rsplit(".", 1)[0] + "."
    if description:
        parts.append(f"Описание: {description}")
    key_skills = ", ".join(s.get("name", "") for s in data.get("key_skills", []))
    if key_skills:
        parts.append(f"Ключевые навыки: {key_skills}")
    return "\n".join(parts)


def call_ollama_chat(system_prompt, user_prompt):
    if not OLLAMA_API_KEY:
        print("[Cover Letter] OLLAMA_API_KEY not set, skip LLM", file=sys.stderr)
        return ""
    url = f"{OLLAMA_BASE_URL}/chat/completions"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": COVER_LETTER_TEMP,
        "max_tokens": COVER_LETTER_MAX_TOKENS,
    }
    # Disable reasoning for DeepSeek V4 models through Ollama Cloud
    if "deepseek" in OLLAMA_MODEL.lower():
        payload["reasoning_effort"] = "none"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {OLLAMA_API_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.load(resp)
        msg = data.get("choices", [{}])[0].get("message", {})
        content = msg.get("content", "").strip()
        if not content:
            # Some models put text in reasoning field
            content = msg.get("reasoning", "").strip()
        return content
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:500]
        print(f"[Cover Letter] Ollama HTTP {e.code}: {err}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"[Cover Letter] Ollama error: {e}", file=sys.stderr)
        return ""


def clean_cover_letter(text):
    if not text:
        return ""
    # Remove markdown formatting
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"\*", "", text)
    text = re.sub(r"__", "", text)
    text = re.sub(r"`", "", text)
    # Remove long dashes
    text = re.sub(r"[—–]", "-", text)
    # Ensure proper greeting paragraph break (only spaces/tabs after greeting)
    text = re.sub(r"^(Здравствуйте!)[ \t]*", r"\1\n\n", text, count=1)
    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Strip any signature-like trailing noise
    text = re.sub(r"\n*(?:Влад\.?|С уважением,?.*?|Best,.*)?\s*$", "", text, flags=re.S).strip()
    # Split into paragraphs
    if "\n\n" in text:
        parts = text.split("\n\n")
        clean_parts = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            clean_parts.append(p)
        # Drop incomplete trailing paragraphs (no ending punctuation)
        while clean_parts and not clean_parts[-1].endswith((".", "!", "?")):
            clean_parts = clean_parts[:-1]
        text = "\n\n".join(clean_parts)
    # Append deterministic closing paragraph unless already present as the final paragraph
    closing = "Буду рад короткому созвону, чтобы обсудить детали."
    if not text.endswith(closing):
        # Remove any partial closing fragment that may be dangling
        text = re.sub(r"\n+Буду рад[^.!?]*$", "", text, flags=re.S).strip()
        text = text + "\n\n" + closing
    return text


def fallback_cover_letter(title, company, salary, location, match, resume_text):
    cases = select_cases(title, company)
    body = BODY_TEMPLATE.format(title=title, company=company, selected_cases=cases)
    letter = f"{INTRO_TEMPLATE}\n\n{body}\n\n{CLOSE_TEMPLATE}"
    letter = re.sub(r"\n{3,}", "\n\n", letter).strip()
    return letter


def load_resume():
    if os.path.exists(RESUME_PATH):
        with open(RESUME_PATH, encoding="utf-8") as fh:
            return fh.read()
    return RESUME


# ---------------------------------------------------------------------------
# HH API helpers
# ---------------------------------------------------------------------------
def hh_api(url, timeout=20):
    global HH_TOKEN_REVOKED
    if HH_TOKEN_REVOKED:
        raise RuntimeError(HH_TOKEN_REVOKED_MESSAGE)
    headers = {
        "User-Agent": HH_USER_AGENT,
        "Accept": "application/json",
    }
    if HH_APP_TOKEN:
        headers["Authorization"] = f"Bearer {HH_APP_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:500]
        body_lower = err.lower()
        if e.code == 403 and ("token-revoked" in body_lower or "unrecognized authorization" in body_lower):
            HH_TOKEN_REVOKED = True
            raise RuntimeError(HH_TOKEN_REVOKED_MESSAGE)
        raise RuntimeError(f"HH API HTTP {e.code}: {err}")


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


# ---------------------------------------------------------------------------
# Google Sheets helpers
# ---------------------------------------------------------------------------
def get_access_token():
    creds_path = os.path.expanduser("~/.config/gws/credentials.json")
    if not os.path.exists(creds_path):
        return None
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
        props = sheet["properties"]
        if props["sheetId"] == gid:
            return props["title"]
    return None


def get_row_count(access_token, sheet_name):
    enc = urllib.parse.quote(f"{sheet_name}!A:J", safe="")
    req = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}"
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    return len(data.get("values", []))


def ensure_header(access_token, sheet_name):
    enc = urllib.parse.quote(f"{sheet_name}!A1:J1", safe="")
    req = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}"
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    values = data.get("values", [])
    if not values or values[0] != REPORT_COLUMNS:
        body = json.dumps({
            "range": f"{sheet_name}!A1:J1",
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
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}?valueInputOption=USER_ENTERED"
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
    from_ = salary.get("from")
    to_ = salary.get("to")
    currency = salary.get("currency", "")
    gross = salary.get("gross")
    parts = []
    if from_:
        parts.append(f"от {from_:,}")
    if to_:
        parts.append(f"до {to_:,}")
    out = " ".join(parts)
    if currency:
        out += f" {currency}"
    if gross is not None:
        out += " gross" if gross else " net"
    return out or "не указана"


def parse_level(title):
    t = title.lower()
    if "head" in t or "директор" in t or "director" in t or "руководитель направления" in t:
        return "head"
    if "lead" in t or "руководитель" in t or "ведущий" in t:
        return "lead"
    if "senior" in t or "старший" in t:
        return "senior"
    if "principal" in t or "staff" in t:
        return "principal"
    if "junior" in t or "младший" in t or "intern" in t or "стажер" in t:
        return "junior"
    return "middle"


def priority_and_match(title, snippet=""):
    text = f"{title} {snippet}".lower()
    if "ai" in text or "ии" in text or "artificial intelligence" in text or "machine learning" in text:
        if re.search(r"\b(lead|head|директор|director|руководитель|manager|менеджер|владелец|owner)\b", text):
            return "high", "AI + управленческая роль"
        return "medium", "AI-роль"
    if re.search(r"\b(transformation|трансформация|implementation|внедрение)\b", text):
        return "high", "AI-трансформация / внедрение"
    if re.search(r"\b(product|продукт)\b", text) and re.search(r"\b(manager|менеджер|lead|owner|владелец)\b", text):
        return "medium", "Product-роль"
    return "low", "Смежная роль"


def enrich(item):
    title = item.get("name", "").strip()
    url = item.get("alternate_url", "").strip()
    if not title or not url:
        return None

    company = item.get("employer", {}).get("name", "")
    area = item.get("area", {}).get("name", "")
    salary = format_salary(item.get("salary"))
    level = parse_level(title)
    snippet = item.get("snippet", {}).get("requirement", "") or ""
    priority, match = priority_and_match(title, snippet)

    apply_url = item.get("apply_alternate_url", "") or url

    return {
        "date": datetime.now().strftime("%d.%m.%Y"),
        "title": title,
        "company": company,
        "salary": salary,
        "location": area or "Remote / unspecified",
        "level": level,
        "url": url,
        "match": match,
        "respond": f'=HYPERLINK("{apply_url}";"🚀 Откликнуться")',
    }


def is_active(title, snippet=""):
    return not ARCHIVE_RE.search(f"{title} {snippet}")


def is_relevant(title, snippet=""):
    text = f"{title} {snippet}".lower()
    # Must contain at least one target keyword OR explicit AI/ML terms
    has_target_kw = any(kw.lower() in text for kw in KEYWORDS)
    has_ai_term = re.search(r"\b(ai|artificial intelligence|machine learning|ml|llm|агент|agent)\b", text)
    if not has_target_kw and not has_ai_term:
        return False
    if JUNK_RE.search(title):
        return False
    if RESUME_RE.search(title):
        return False
    return True


# ---------------------------------------------------------------------------
# State / dedup
# ---------------------------------------------------------------------------
def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to load seen state: {e}", file=sys.stderr)
    return {}


def save_seen(seen):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, ensure_ascii=False, indent=2)


def dedup(vacancies, seen):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=SEEN_EXPIRE_DAYS)

    cleaned = {}
    for vid, ts in seen.items():
        try:
            dt = datetime.fromisoformat(ts)
            if dt > cutoff:
                cleaned[vid] = ts
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
# Telegram report
# ---------------------------------------------------------------------------
def escape_md_v2(text):
    return re.sub(r"([_\[\]\(\)~`>#+\-=|{}\.!])", r"\\\1", text)


def format_telegram(new_vacancies, total_rows, max_jobs=5):
    today_str = datetime.now().strftime("%d.%m.%Y")
    sheet_link_text = f"[Открыть таблицу]({SHEET_URL})"
    sheet_link_escaped = sheet_link_text.replace(".", "\\.")

    if not new_vacancies:
        return (
            f"*HH\\.ru AI: {today_str}*\n\n"
            f"Новых вакансий: 0 \\| Всего в таблице: {total_rows}\n\n"
            f"🔗 {sheet_link_escaped}"
        )

    lines = [
        f"*HH\\.ru AI: {today_str}*",
        "",
        f"Новых вакансий: {len(new_vacancies)} \\| Всего в таблице: {total_rows}",
        "",
        f"🔗 {sheet_link_escaped}",
        "",
        "====",
        "",
        f"🔥 *ТОП\\-{min(len(new_vacancies), max_jobs)} находки сегодня*",
    ]
    # Sort: high → medium → low, then by level
    level_rank = {"head": 0, "lead": 1, "senior": 2, "principal": 3, "middle": 4, "junior": 5}
    for idx, v in enumerate(new_vacancies):
        v["_sort_idx"] = idx
    new_vacancies.sort(key=lambda v: (
        0 if "AI + управленческая роль" in v.get("match", "") else
        1 if "AI-трансформация" in v.get("match", "") else
        2 if "AI-роль" in v.get("match", "") else
        3 if "Product-роль" in v.get("match", "") else 4,
        level_rank.get(v["level"], 9),
        v.get("_sort_idx", 0)
    ))

    for i, v in enumerate(new_vacancies[:max_jobs], 1):
        title = v["title"].replace("]", " ").replace("[", " ").strip()
        safe_title = escape_md_v2(title)
        safe_url = v["url"].replace(")", "%29")
        salary = escape_md_v2(v["salary"])
        company = escape_md_v2(v["company"] or "—")
        location = escape_md_v2(v["location"])
        lines.append(
            f"{i}\\. [{safe_title}]({safe_url})\n"
            f"🏢 {company}  \\|  💰 {salary}  \\|  📍 {location}"
        )
        if v.get("match"):
            lines.append(f"🎯 {escape_md_v2(v['match'])}")

    report = "\n".join(lines)
    if len(report) > 4000:
        report = report[:3990] + "\n\n…"
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("[HH AI Scraper] Starting...", file=sys.stderr)

    all_vacancies = []
    api_error = None

    for kw in KEYWORDS:
        try:
            data = search_vacancies(kw, per_page=50, page=0)
            items = data.get("items", [])
            print(f"[HH AI Scraper] '{kw}': found={data.get('found', 0)}, returned={len(items)}", file=sys.stderr)
            for it in items:
                v = enrich(it)
                if not v:
                    continue
                snippet = it.get("snippet", {}).get("requirement", "") or ""
                if not is_active(v["title"], snippet):
                    continue
                if not is_relevant(v["title"], snippet):
                    continue
                all_vacancies.append(v)
        except Exception as e:
            print(f"[HH AI Scraper] ERROR for '{kw}': {e}", file=sys.stderr)
            api_error = str(e)

    # Within-run dedup by URL
    seen_urls = set()
    unique = []
    for v in all_vacancies:
        if v["url"] not in seen_urls:
            seen_urls.add(v["url"])
            unique.append(v)
    print(f"[HH AI Scraper] After within-run dedup: {len(unique)}", file=sys.stderr)

    # Cross-run dedup
    seen = load_seen()
    new_vacancies, updated_seen = dedup(unique, seen)
    print(f"[HH AI Scraper] New vacancies: {len(new_vacancies)}", file=sys.stderr)

    # Generate cover letters for new vacancies in parallel
    resume_text = load_resume()
    limit = COVER_LETTER_LIMIT or len(new_vacancies)

    if limit > 0:
        def _gen(idx_v):
            i, v = idx_v
            if i >= limit:
                return i, ""
            letter = generate_cover_letter(
                v["title"], v["company"], v["salary"], v["location"], v["match"], v["url"], resume_text
            )
            return i, letter

        workers = max(1, min(COVER_LETTER_WORKERS, limit))
        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = {exe.submit(_gen, (i, v)): i for i, v in enumerate(new_vacancies)}
            for fut in as_completed(futures):
                i, letter = fut.result()
                new_vacancies[i]["cover-letter"] = letter
    else:
        for v in new_vacancies:
            v["cover-letter"] = ""

    save_seen(updated_seen)

    # Google Sheets
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
                try:
                    result = append_rows(token, sheet_name, next_row, rows)
                    written = result.get("updatedRows", 0)
                    total_rows = max(total_rows, total_rows + written)
                    print(f"[Sheets] Written {written} rows to '{sheet_name}'", file=sys.stderr)
                except Exception as e:
                    print(f"[Sheets ERROR] {e}", file=sys.stderr)
                    api_error = api_error or str(e)
        else:
            print(f"[Sheets ERROR] Sheet '{SHEET_NAME}' not found", file=sys.stderr)
    else:
        print("[Sheets WARN] No Google credentials, skip sheet write", file=sys.stderr)

    if api_error and not new_vacancies:
        today_str = datetime.now().strftime("%d.%m.%Y")
        if HH_TOKEN_REVOKED:
            print(
                f"*HH\\.ru AI: {today_str}*\n\n"
                f"{HH_TOKEN_REVOKED_MESSAGE}"
            )
        else:
            print(
                f"*HH\\.ru AI: {today_str}*\n\n"
                f"⚠️ Не удалось получить данные с HH\\.ru\n"
                f"Причина: `{escape_md_v2(api_error)}`\n\n"
                f"Проверь токен / User\\-Agent."
            )
        return

    print(format_telegram(new_vacancies, total_rows))


def update_respond_column():
    """Update only column J with apply_alternate_url links, preserving seen state and other data."""
    token = get_access_token()
    if not token:
        print("[Update Respond] No Google credentials", file=sys.stderr)
        return 1
    sheet_name = get_sheet_name(token)
    if not sheet_name:
        print(f"[Update Respond] Sheet '{SHEET_NAME}' not found", file=sys.stderr)
        return 1

    values = get_sheet_values(token, f"{sheet_name}!G2:G2000")
    print(f"[Update Respond] Loaded {len(values)} rows from column G", file=sys.stderr)

    updates = []
    failures = []
    for idx, row in enumerate(values, start=2):
        url = row[0] if row else ""
        if not url:
            continue
        m = re.search(r"/vacancy/(\d+)", url)
        if not m:
            failures.append((idx, url, "no vacancy id"))
            continue
        vid = m.group(1)
        try:
            data = hh_api(f"https://api.hh.ru/vacancies/{vid}")
            apply_url = data.get("apply_alternate_url") or url
        except Exception as e:
            failures.append((idx, url, str(e)))
            apply_url = url
        formula = f'=HYPERLINK("{apply_url}";"🚀 Откликнуться")'
        updates.append({"range": f"{sheet_name}!J{idx}", "values": [[formula]]})
        if len(updates) % 50 == 0:
            print(f"[Update Respond] Processed {len(updates)} rows...", file=sys.stderr)
        time.sleep(0.15)

    if updates:
        try:
            result = batch_update_values(token, updates)
            total = result.get("totalUpdatedCells", 0)
            print(f"[Update Respond] Updated {total} cells", file=sys.stderr)
        except Exception as e:
            print(f"[Update Respond] batchUpdate error: {e}", file=sys.stderr)
            return 1
    if failures:
        print(f"[Update Respond] Failures: {len(failures)}", file=sys.stderr)
        for f in failures[:10]:
            print(f"  {f}", file=sys.stderr)
    return 0


def get_sheet_values(access_token, range_spec):
    enc = urllib.parse.quote(range_spec, safe="")
    req = urllib.request.Request(f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{enc}")
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp).get("values", [])


def batch_update_values(access_token, data):
    body = json.dumps({"valueInputOption": "USER_ENTERED", "data": data}).encode()
    req = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values:batchUpdate",
        data=body, method="POST"
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


if __name__ == "__main__":
    if os.environ.get("HH_UPDATE_RESPOND_ONLY") == "1":
        sys.exit(update_respond_column())
    main()
