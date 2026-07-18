"""Step 5: cover letters через Ollama Cloud (DeepSeek). Fallback — детерминированный шаблон.
Использует enriched description из записи — без лишних вызовов HH API."""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, http_client
from .store import now_iso

RESUME = """
AI Lead в PROSHINSKY AI (Июль 2025 — Июнь 2026)
Внедрение genAI-инструментов и автоматизация бизнес-процессов (no-code/low-code).
Кейсы: отдел контроля качества звонков на ИИ; автоматическая отчетность ЛПР; SKU price
monitoring (n8n, Tavily, Firecrawl); RAG-чатботы (Pinecone, Qdrant); голосовой ИИ-агент
(Retell); AI SEO pipeline; +15 автоматизаций с доказанным эффектом.
Навыки: SGR, RAG, PydanticAI, MCP, tool-call, Voice agents. Инструменты: LangChain,
LangGraph, n8n, CrewAI, Langfuse + evals.

Lead Product Manager (B2B/B2C) в dellin.ru (2023—2025): PnL и CSI digital-каналов, MAU >1.5M.
Рост онлайн-выручки +25%/год, экономия >100 млн/год, CSI 8.0 → 9.1. 5 команд, >60 чел.

Lead Product Manager (Mobile) в rutube.ru (2022—2023): MAU х10 (200K → 2M), удержание 30d +21%,
время просмотра +20%, crash-free 99.8%.

CPO / Head of Product в SOKOLOV (2021—2022): CR2 +30% Web / +27% App, NPS +11%, TTM -20%.

Lead Product Manager в Ozon.ru (2020—2021): контент-платформа (SKU x20 быстрее), модерация x4,
Product service p99 1.2s → 350ms.
"""

CLOSING = "Буду рад короткому созвону, чтобы обсудить детали."

PLACEHOLDER_RE = re.compile(r"[{\[<](?:[^}\]>]{1,40})[}\]>]|\bTODO\b|\bПЛЕЙСХОЛДЕР\b|X{3,}", re.I)


def build_prompts(rec):
    system_prompt = f"""Ты — профессиональный рекрутер, который пишет сопроводительные письма от лица кандидата. Отвечай ТОЛЬКО готовым текстом письма.

Жёсткие правила:
1. Начинай строго со слова "Здравствуйте!".
2. Ровно 2 абзаца, разделённые пустой строкой.
3. 1 абзац: 1 предложение, почему опыт подходит. БЕЗ "откликаюсь потому что", "вакансия интересна".
4. 2 абзац: 1-2 конкретных кейса из резюме. Только факты из резюме. НЕ выдумывай цифры. НЕ пиши, что работал в {rec.get('company', 'этой компании')}.
5. НЕ пиши подпись.
6. Длина: 60-100 слов. Короткие предложения.
7. Без markdown, длинного тире.
8. Стиль: разговорный, уважительный.

Резюме:
{RESUME}
"""
    desc = rec.get("description", "")[:2500]
    user_prompt = f"""Вакансия: {rec['title']}
Компания: {rec.get('company', '')}
Формат: {rec.get('work_format', '')} | {rec.get('employment', '')} | Опыт: {rec.get('experience', '')}
Ключевые навыки: {', '.join(rec.get('key_skills', [])[:15])}

Описание: {desc}

Напиши готовое сопроводительное письмо.
"""
    return system_prompt, user_prompt


def call_ollama(system_prompt, user_prompt):
    if not config.ollama_api_key():
        return ""
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.COVER_LETTER_TEMP,
        "max_tokens": config.COVER_LETTER_MAX_TOKENS,
    }
    if "deepseek" in config.OLLAMA_MODEL.lower():
        payload["reasoning_effort"] = "none"
    try:
        resp = http_client.request(
            "POST", f"{config.OLLAMA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.ollama_api_key()}",
                     "Content-Type": "application/json"},
            data=json.dumps(payload).encode(), timeout=90)
    except http_client.NetworkError as e:
        print(f"[cover] ollama network error: {e}", file=sys.stderr)
        return ""
    if resp.status != 200:
        print(f"[cover] ollama HTTP {resp.status}", file=sys.stderr)
        return ""
    msg = resp.json().get("choices", [{}])[0].get("message", {})
    return (msg.get("content") or msg.get("reasoning") or "").strip()


def clean_letter(text):
    if not text:
        return ""
    text = re.sub(r"\*\*|\*|__|`", "", text)
    text = re.sub(r"[—–]", "-", text)
    text = re.sub(r"^(Здравствуйте!)[ \t]*", r"\1\n\n", text, count=1)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(r"\n*(?:Влад\.?|С уважением,?.*?|Best,.*)?\s*$", "", text, flags=re.S).strip()
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    while parts and not parts[-1].endswith((".", "!", "?")):
        parts.pop()
    text = "\n\n".join(parts)
    text = re.sub(r"\n+Буду рад[^.!?]*$", "", text, flags=re.S).strip()
    if not text.endswith(CLOSING):
        text = text + "\n\n" + CLOSING
    return text


def fallback_letter(rec):
    body = (f"Я внедрял genAI-инструменты и автоматизацию бизнес-процессов в роли AI Lead "
            f"в PROSHINSKY AI, и этот опыт пересекается с задачами роли {rec['title']}.")
    cases = ("• Отдел контроля качества звонков на базе ИИ: пайплайн оценки, трейсинг, evals.\n"
             "• RAG-чатботы (Pinecone, Qdrant) и голосовой ИИ-агент на Retell.\n"
             "• +15 автоматизаций с доказанным экономическим эффектом.\n"
             "• До этого 5 лет продуктового лидерства: dellin.ru (онлайн-выручка +25%/год), "
             "RuTube (MAU x10), SOKOLOV (CPO), Ozon.")
    return f"Здравствуйте!\n\n{body}\n\n{cases}\n\n{CLOSING}"


def letter_ok(text):
    """400–1500 симв., без плейсхолдеров и HTML-мусора (TC-09)."""
    if not text or not (400 <= len(text) <= 1500):
        return False
    if PLACEHOLDER_RE.search(text):
        return False
    if re.search(r"<[a-z/][^>]*>", text, re.I):
        return False
    return True


def generate_for_record(rec):
    sp, up = build_prompts(rec)
    letter = clean_letter(call_ollama(sp, up))
    if not letter_ok(letter):
        letter = fallback_letter(rec)
    rec["cover_letter"] = letter
    rec["updated_at"] = now_iso()
    return letter


def generate_all(store_dict, new_ids):
    """Parallel generation. Returns count with valid letters."""
    if not new_ids:
        return 0
    workers = max(1, min(config.COVER_LETTER_WORKERS, len(new_ids)))
    with ThreadPoolExecutor(max_workers=workers) as exe:
        futures = {exe.submit(generate_for_record, store_dict[vid]): vid for vid in new_ids}
        for fut in as_completed(futures):
            fut.result()
    return sum(1 for vid in new_ids if store_dict[vid].get("cover_letter"))
