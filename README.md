# HH.ru AI Vacancies

Автономный cron-пайплайн: ищет AI/PM вакансии на HeadHunter, фильтрует и обогащает их,
генерирует сопроводительные письма через Ollama Cloud, авто-откликается через
`/negotiations`, экспортирует в Google Sheets и сообщает в Telegram.

## Pipeline

```
auth (user OAuth, data/hh_tokens.json — авто-refresh на 403)
  → fetch  (GET /vacancies по 13 ключевым словам, фильтры junk/archive/resume/relevance)
  → merge/dedup (data/vacancies.json — source of truth, ключ vacancy_id)
  → enrich (GET /vacancies/{id} — полные детали, описание, skills, apply_url)
  → cover  (Ollama Cloud, DeepSeek V4 Flash, параллельно; deterministic fallback)
  → apply  (POST /negotiations — отправлено / не отправлено / тест; BatchStop на фаталах)
  → store.save (атомарно, с .bak)
  → sheets_export (полная перезапись табы HH_AI)
  → telegram (send_report + send_alert, parse_mode=HTML)
```

## Cron

| Параметр | Значение |
|----------|----------|
| Schedule | `0 9 */2 * *` (каждые 2 дня, 09:00 MSK) |
| Deliver | Telegram (origin) |
| Script | `python3 -m src.pipeline` |
| `no_agent` | `true` (чистый скрипт, без LLM-инференса) |
| Config | `config/cron.yaml` |

## Структура репозитория

```
hh-ai-vacancies/
├── README.md                          — этот файл
├── CLAUDE.md                          — инструкция для Claude Code
├── SKILL.md                           — umbrella skill для Hermes Agent
├── .gitignore
│
├── src/                               — модульный пайплайн (apply-enabled)
│   ├── pipeline.py                    — оркестратор 8 стадий, exit 0/2/3
│   ├── config.py                      — env, пути, ключевые слова, regex, статусы
│   ├── http_client.py                 — single HTTP seam (urllib), HttpResponse/NetworkError
│   ├── auth.py                        — user OAuth load/save (атомарно), refresh-on-403-once
│   ├── fetch.py                       — GET /vacancies, фильтры, parse_level, match_reason
│   ├── store.py                       — data/vacancies.json, SCHEMA, validate, merge, .bak
│   ├── enrich.py                      — GET /vacancies/{id}, strip HTML, truncate 4000
│   ├── cover.py                       — Ollama Cloud cover-письма (ThreadPool), fallback
│   ├── apply.py                       — POST /negotiations, status machine, BatchStop, 429 backoff
│   ├── sheets_export.py               — полная перезапись HH_AI, батч 200 строк
│   └── telegram.py                    — send_report/send_alert, parse_mode=HTML, esc()
│
├── scripts/
│   └── hh_oauth_manager.py            — HH.ru OAuth2-менеджер (link/exchange/refresh/check/bridge)
│
├── tests/                             — 53 pytest-кейса, MockHttp (offline, monkeypatch http_client)
├── evals/
│   ├── check_metrics.py               — детерминированный goal-check (exit 0 = цель достигнута)
│   └── rate_cover_letters.py          — LLM-рубрика писем (≥7/10)
│
├── config/
│   └── cron.yaml                      — Hermes cron job definition
│
├── docs/
│   ├── DEPLOY.md                      — деплой на хост + live e2e
│   └── api-contract.md                — контракт HH API (token types, /negotiations)
│
├── references/                        — инцидент-логи и дизайн-ноты (см. CLAUDE.md)
└── templates/                         — шаблоны для новых vacancy-трекеров
```

## Команды

```bash
# DRY_RUN (по умолчанию 1 — безопасно, отклики НЕ отправляются)
DRY_RUN=1 python3 -m src.pipeline

# Live apply — только после явного ОК; первый прогон ограничен
DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline

# Goal-check после прогона (exit 0 = цель достигнута)
python3 evals/check_metrics.py

# LLM-рубрика писем (независимый вызов Ollama, порог ≥7/10)
python3 -m evals.rate_cover_letters --sample 5

# Тесты — stdlib only, нужен только pytest
python3 -m pytest
```

## Конфигурация

### Переменные окружения (`~/.hermes/.env` на хосте / `env.env` на Mac)

| Переменная | Назначение | Обязательно |
|------------|------------|-------------|
| `HH_CLIENT_ID`, `HH_CLIENT_SECRET`, `HH_REDIRECT_URI` | OAuth2-app параметры (для `hh_oauth_manager.py`) | Для первичной авторизации |
| `HH_RESUME_ID` | ID резюме для откликов (`GET /resumes/mine`) | Да (live mode) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Отчёт + алерты | Для Telegram (иначе stdout) |
| `OLLAMA_API_KEY` | Ключ Ollama Cloud для cover-писем | Для LLM-писем (иначе fallback) |
| `OLLAMA_BASE_URL` | URL Ollama Cloud (default: `https://ollama.com/v1`) | Нет |
| `OLLAMA_MODEL` | Модель (default: `deepseek-v4-flash`) | Нет |
| `DRY_RUN` | `1` (default, безопасно) / `0` (live) | Нет |
| `APPLY_LIMIT` | Лимит откликов за прогон (0 = без лимита) | Нет |
| `APPLY_PAUSE_SEC` | Пауза между POST /negotiations (default: 5) | Нет |
| `COVER_LETTER_WORKERS` | Параллелизм генерации (default: 10) | Нет |

### Токены HH.ru

- User OAuth-пара (access + refresh) хранится в `data/hh_tokens.json` (атомарная запись, refresh_token одноразовый).
- Первичная авторизация и авто-refresh — через `scripts/hh_oauth_manager.py` (см. `docs/DEPLOY.md`).
- `/negotiations` требует именно **user**-токен; app-токен даёт `403 oauth/user_auth_expected`.

### Google Sheets

- Spreadsheet ID: `1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok`
- Tab: `HH_AI` (GID: `1464494667`)
- Полная перезапись каждый прогон; Sheets — только визуализация, обратно не читается.
- Auth: Google OAuth refresh token (`~/.config/gws/credentials.json`)

### Source of truth

- `data/vacancies.json`, ключ — `vacancy_id`. Атомарная запись (`.tmp` + `os.replace`) с `.bak`.

## Ключевые слова

13 запросов: `Product AI`, `AI Lead`, `AI Transformation Lead`, `AI Product Manager`,
`Владелец AI продукта`, `Руководитель по внедрению AI`, `AI-First`,
`Специалист по внедрению ИИ`, `директор по продукту`, `Product Director`,
`Chief Product Officer`, `CPO`, `Head of Product`.

## Технологии

- **Python 3.10** (хост) / **3.13** (Mac) — stdlib only (`urllib`, `json`, `re`, `concurrent.futures`)
- **HeadHunter API** — `api.hh.ru` (search, vacancies, OAuth, `/negotiations`)
- **Google Sheets API v4** — OAuth2 refresh token
- **Ollama Cloud** — DeepSeek V4 Flash для cover-писем
- **Telegram Bot API** — отчёты + алерты (HTML)
- **Hermes Agent cron** — `no_agent: true`, script-only

## Связанные ресурсы

- [HH.ru API docs](https://api.hh.ru/openapi/redoc) — официальная документация
- `SKILL.md` — umbrella skill, рецепты, история инцидентов

## Лицензия

Приватный проект. Не для публичного распространения.