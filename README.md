# HH.ru AI Vacancies

Автономный cron-скрипт для сбора AI/PM вакансий с HeadHunter API → запись в Google Sheets → отчёт в Telegram.

## Pipeline

```
HH.ru API (GET /vacancies по 13 ключевым словам)
  → фильтр (junk titles, archive, relevance)
  → дедупликация по URL (seen.json, 30-дневное окно)
  → генерация cover-писем через Ollama Cloud (DeepSeek V4 Flash)
  → запись в Google Sheets (таб HH_AI)
  → отчёт в Telegram (MarkdownV2, топ-5 вакансий)
```

## Cron

| Параметр | Значение |
|----------|----------|
| Job ID | `99a55e0f5ac4` |
| Schedule | `0 9 */2 * *` (каждые 2 дня, 09:00 MSK) |
| Deliver | Telegram (origin) |
| Script | `scripts/hh_ai_vacancies.py` |
| `no_agent` | `true` (чистый скрипт, без LLM-инференса) |

## Структура репозитория

```
hh-ai-vacancies/
├── README.md                          — этот файл
├── SKILL.md                           — umbrella skill для Hermes Agent
├── .gitignore
│
├── scripts/                           — production скрипты
│   ├── hh_ai_vacancies.py             — основной скрапер (900 строк)
│   └── hh_token_updater.py            — обновление HH_APP_TOKEN через Playwright + OTP
│
├── references/                        — документация и инцидент-логи
│   ├── hh-api-notes.md                — эндпоинты, заголовки, лимиты, формат ответа
│   ├── hh-token-types-and-revocation.md — типы токенов (APPL vs OAuth), revocation handling
│   ├── hh-token-automation.md         — Playwright авто-обновление токена, OTP техника
│   ├── hh-cover-letter-generation.md  — пайплайн генерации cover-писем через Ollama
│   ├── hh-sheet-columns-correction-2026-06-28.md — эволюция колонок Google Sheets
│   ├── hh-userscript-auto-response.md — Tampermonkey скрипт для авто-откликов
│   ├── hh-api-notes.md                — API endpoints, headers, rate limits
│   ├── ai-pm-hh-api-migration.md      — миграция с web_search на native HH API
│   ├── ai-pm-vacancies-processor.py   — референсный процессор для web_search пайплайна
│   ├── archive-filter-incident-2026-06-27.md — инцидент: архивные вакансии в отчёте
│   ├── google-sheets-color-feedback-loop.md — цветовая разметка строк для ML-фильтра
│   ├── gws-batch-write-pattern.md     — батч-запись в GSheets через gws CLI
│   ├── proactive-cron-failure-handling.md — стратегия алертов при сбоях
│   ├── skill-patch-marker-2026-07-05.md — маркер обновления skill
│   ├── telegram-bot-patterns.md       — паттерны Telegram-бота для vacancy alerts
│   ├── telegram-html-vs-markdownv2.md — почему HTML, а не MarkdownV2
│   ├── upwork-title-link-correction-2026-06-25.md — кликабельные заголовки
│   └── vacancy-cron-timeout-case-2026-06.md — инцидент с таймаутом cron
│
└── templates/                         — шаблоны для новых vacancy-трекеров
    ├── hh_vacancy_scraper.py          — боilerplate для нового HH-трекера
    └── hh_auto_response.user.js       — Tampermonkey/Violentmonkey userscript
```

## Конфигурация

### Переменные окружения (`~/.hermes/.env`)

| Переменная | Назначение | Обязательно |
|------------|------------|-------------|
| `HH_APP_TOKEN` | Application token (APPL...) для HH API | Да (повышенные лимиты) |
| `HH_ADMIN_EMAIL` | Email для входа в dev.hh.ru/admin | Для token updater |
| `HH_ADMIN_PASSWORD` | Пароль для dev.hh.ru/admin | Для token updater |
| `OLLAMA_API_KEY` | Ключ Ollama Cloud для cover-писем | Для cover letters |
| `OLLAMA_BASE_URL` | URL Ollama Cloud (default: `https://ollama.com/v1`) | Нет |
| `OLLAMA_MODEL` | Модель для cover-писем (default: `deepseek-v4-flash`) | Нет |
| `COVER_LETTER_LIMIT` | Лимит писем за запуск (0 = все) | Нет |
| `COVER_LETTER_WORKERS` | Параллелизм генерации (default: 10) | Нет |

### Google Sheets

- Spreadsheet ID: `1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok`
- Tab: `HH_AI` (GID: `1464494667`)
- Колонки: `date | title | company | salary | location | level | url | match | cover-letter | respond`
- Auth: Google OAuth refresh token (`~/.config/gws/credentials.json`)

### Состояние дедупликации

- Файл: `~/.hermes/hh_ai_seen.json`
- Окно: 30 дней
- Ключ: URL вакансии

## Ключевые слова

Скрипт ищет по 13 запросам:

- `Product AI`, `AI Lead`, `AI Transformation Lead`, `AI Product Manager`
- `Владелец AI продукта`, `Руководитель по внедрению AI`, `AI-First`
- `Специалист по внедрению ИИ`, `директор по продукту`, `Product Director`
- `Chief Product Officer`, `CPO`, `Head of Product`

## Фильтрация

- **Junk titles:** data entry, virtual assistant, customer support, developer, designer, analyst, engineer, SMM, sales manager, переводчик
- **Archive filter:** вакансии с маркерами «в архиве», «закрыта», «expired», «on hold»
- **Resume filter:** вакансии со словами «резюме», «CV», «open to work»
- **Relevance:** должно быть хотя бы одно ключевое слово ИЛИ AI/ML термин в title/snippet

## Обновление токена

HH.ru application tokens не имеют API для авто-регенерации. Обновление — через Playwright:

```bash
# 1. Запустить (нужен Xvfb на headless-сервере)
xvfb-run -a python3 -u scripts/hh_token_updater.py

# 2. Когда скрипт выведет "Waiting for OTP code in /tmp/hh_otp.txt",
#    взять код из письма HH.ru и записать:
echo "123456" > /tmp/hh_otp.txt

# 3. Скрипт автоматически:
#    - войдёт в dev.hh.ru/admin
#    - найдёт приложение Piramiza
#    - покажет токен
#    - обновит HH_APP_TOKEN в ~/.hermes/.env
#    - протестирует токен через GET /vacancies
```

## Технологии

- **Python 3** (stdlib only — `urllib`, `json`, `re`, `concurrent.futures`)
- **HeadHunter API** — `api.hh.ru/vacancies`
- **Google Sheets API** — OAuth2 refresh token
- **Ollama Cloud** — DeepSeek V4 Flash для cover-писем (reasoning disabled)
- **Playwright** — авто-обновление токена через браузер
- **Hermes Agent cron** — `no_agent: true`, script-only

## Связанные ресурсы

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs) — платформа cron-джобов
- [HH.ru API docs](https://api.hh.ru/openapi/redoc) — официальная документация
- [Skill: vacancy-monitoring](https://github.com/Asmadey/hermes_vlad/tree/main/skills/research/vacancy-monitoring) — umbrella skill в основном репо

## Лицензия

Приватный проект. Не для публичного распространения.