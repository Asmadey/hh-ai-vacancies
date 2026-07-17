# HeadHunter cover letter generation

Session: 2026-06-28 — added personalized cover letters to the HH.ru AI vacancy tracker.
Updated 2026-06-29 — aligned with the deployed `hh_ai_vacancies.py` version and added HH API token-revocation handling.

## Why

The user wanted each new vacancy in the Google Sheet to include a ready-to-review cover letter tailored to the full vacancy description and the user's resume.

## Architecture

```
Search results from /vacancies
  → filter/dedup
  → for each new vacancy: GET /vacancies/{id}
      → extract description, key skills, experience, schedule, employment, employer, salary
  → LLM prompt with resume + **full** vacancy details (NOT the search snippet)
  → post-processing (strip markdown, ensure closing)
  → write to column `cover-letter`
```

## Resume source

Store the resume in a skill so future sessions can reuse and update it without touching the scraper:

- Skill: `hh-cover-letters`
- File: `~/.hermes/skills/hh-cover-letters/references/resume.md`
- Scraper reads it at runtime: `RESUME_PATH = os.path.expanduser("~/.hermes/skills/hh-cover-letters/references/resume.md")`

## LLM provider: Ollama Cloud

Chosen because the user already uses Ollama Cloud and wanted a cheap model.

- Endpoint: `{OLLAMA_BASE_URL}/chat/completions` (OpenAI-compatible)
- Default model: `deepseek-v4-flash`
- Fallback: whichever model is configured via `OLLAMA_MODEL`

### Historical benchmark (2026-06-28)

| Model | Latency | Output quality | Verdict |
|---|---|---|---|
| `ministral-3:8b` | ~5s | Good, follows structure | Used briefly |
| `gemma3:12b` | ~6s | Good, no reasoning | Fallback |
| `deepseek-v4-flash` | ~3s | Fast, follows rules once prompt is strict | Current default |
| `deepseek-v3.2` | ~20s | Empty content | Avoid |
| `deepseek-v3.1:671b` | ~? | Content OK but expensive | Avoid |

## Prompt design

The deployed system prompt is strict and deterministic. The user prompt must use the **full vacancy description** obtained via `GET /vacancies/{id}`, never the truncated `snippet` from the search response.

### System prompt

```text
Ты — профессиональный рекрутер, который пишет сопроводительные письма от лица кандидата. Отвечай ТОЛЬКО готовым текстом письма. Никаких пояснений, планов, драфтов, разборов правил.

Жёсткие правила:
1. Начинай строго со слова "Здравствуйте!" (восклицательный знак, без обращения к компании).
2. Ровно 2 абзаца, разделённые пустой строкой.
3. 1 абзац: 1 предложение, почему опыт подходит. БЕЗ фраз "откликаюсь потому что", "откликнулся на вакансию", "вакансия интересна", "именно", "как раз".
4. 2 абзац: 1-2 конкретных кейса из резюме. Только факты и инструменты, которые есть в резюме. НЕ выдумывай цифры, проценты, технологии. НЕ пиши, что ты работал в компании из вакансии.
5. НЕ пиши подпись. НЕ пиши "Влад", "Влад.", "С уважением, Влад", "Best" и т.п.
6. Длина: 60-100 слов. Короткие предложения.
7. Без markdown (**), жирного, курсива, списков, длинного тире "—".
8. Стиль: разговорный, уважительный. Как письмо знакомому коллеге.

Резюме:
{resume_short}
```

### User prompt

```text
Вакансия: {title}
Компания: {company}
Формат: {match}

Требования и задачи:
{vacancy_full_description}

Ключевые навыки: {key_skills}

Напиши готовое сопроводительное письмо.
```

`{vacancy_full_description}` must be fetched via:

1. Search: `GET https://api.hh.ru/vacancies?text=...&per_page=...&page=...`
2. Details: `GET https://api.hh.ru/vacancies/{vacancy_id}`

**Do NOT use the search `snippet`** — it is truncated to ~200–300 characters.

## Parallelization

153 sequential LLM calls at ~5s each would exceed cron's 600s limit. Use `concurrent.futures.ThreadPoolExecutor` with 10 workers. Measured runtime: ~2m 15s for 153 letters.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=10) as exe:
    futures = {exe.submit(_gen, (i, v)): i for i, v in enumerate(new_vacancies)}
    for fut in as_completed(futures):
        i, letter = fut.result()
        new_vacancies[i]["cover-letter"] = letter
```

## Post-processing

```python
def clean_cover_letter(text):
    text = re.sub(r"\*\*|\*|__|`", "", text)       # strip markdown
    text = re.sub(r"[—–]", "-", text)              # no long dashes
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    closing = "Буду рад короткому созвону, чтобы обсудить детали."
    if closing not in text:
        text = text + "\n\n" + closing
    return text
```

## Google Sheets column layout with cover letters

Final 9-column layout:

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| date | title | company | salary | location | level | url | match | cover-letter |

The `cover-letter` column was added by the user manually; the script reads/writes the 9-column `REPORT_COLUMNS` list.

## Environment variables

```bash
OLLAMA_BASE_URL=https://ollama.com/v1
OLLAMA_API_KEY=...
OLLAMA_MODEL=deepseek-v4-flash   # optional
COVER_LETTER_LIMIT=0               # 0 = all new; set N to generate only first N
COVER_LETTER_MAX_TOKENS=600        # current default
COVER_LETTER_TEMP=0.4              # optional
COVER_LETTER_WORKERS=10            # optional
```

The script loads `~/.hermes/.env` at startup so these are available in cron runs.

## Quality control

Generated letters are a **draft**. Always review before sending:
- LLM sometimes hallucinates small numbers or tool names.
- Some models drift into reasoning or meta-commentary; the prompt rules and post-processing handle this.
- The closing sentence is deterministic, not generated.

## HH API token can be revoked

Real-world failure from 2026-06-29: a previously working `HH_APP_TOKEN` began returning HTTP 403 with `{"oauth_error":"token-revoked"}`.

**Impact:** the scraper cannot call `/vacancies` at all, even with a valid `User-Agent`.

**Fix options, in order of preference:**

1. **Generate a new app token** at https://dev.hh.ru/admin under the application settings. Update `HH_APP_TOKEN` in the scraper (and `.env` if it is stored there). This is the fastest fix.
2. **Switch to OAuth** if the user wants a more stable long-lived credential. Requires a one-time authorization-code flow and storing a `refresh_token`.
3. **Fallback to web scraping** via Firecrawl if the API is unavailable. Slower and consumes Firecrawl credits, but does not depend on HH API tokens.

**Diagnostic sign:**

```
HH API HTTP 403: {"description":"Unrecognized authorization","oauth_error":"token-revoked","errors":[{"value":"token_revoked","type":"oauth"}]}
```

When this appears, do not keep retrying. Notify the user and ask for a new token (option 1) or permission to scrape (option 3).
