# Деплой автономных откликов

Пайплайн `src/` запускается на Hermes-хосте (Linux, Python 3.10) по крону.
Ниже — одноразовый setup + контрольный и live-прогоны.

## Шаг 0 — одноразовый setup (единственный шаг с участием человека)

### 0.1. User OAuth (app-токен НЕ подходит для `/negotiations`)

Используется `scripts/hh_oauth_manager.py` (PKCE, authorization_code flow). Все HTTP —
через single seam `src/http_client.request`, поэтому менеджер работает офлайн в тестах.

В env-файле (`~/.hermes/.env` на хосте / `env.env` на Mac) уже должны лежать:
`HH_CLIENT_ID`, `HH_CLIENT_SECRET`, `HH_REDIRECT_URI`.

```bash
# 1) Сгенерить URL авторизации (сохранит verifier+state в env-файл)
python3 scripts/hh_oauth_manager.py link
# → перейти по напечатанной ссылке, авторизоваться на hh.ru

# 2) Из редиректа ...?code=XXXXX&state=... скопировать параметр code и обменять:
python3 scripts/hh_oauth_manager.py exchange <code>
# → пишет пару в env-файл (HH_OAUTH_*) И в data/hh_tokens.json (формат src/auth.py)

# 3) Проверить, что токен работает:
python3 scripts/hh_oauth_manager.py check
```

Дальше refresh автоматический: пайплайн сам рефрешит на `403 oauth` (`src/auth.py`),
а cron-обёртка `scripts/hh_token_refresh.sh` (Шаг 3) обновляет токен по расписанию.
Участие человека нужно только при истечении refresh_token — менеджер тогда напечатает
инструкцию пере-авторизации (`link` + `exchange`).

### 0.2. resume_id

С user-токеном получить список резюме и выбрать id → в env-файл: `HH_RESUME_ID=...`.
(Ubедиться, что токен жив: `python3 scripts/hh_oauth_manager.py check`, затем
`GET https://api.hh.ru/resumes/mine` тем же Bearer + `HH_USER_AGENT`.)

### 0.3. Telegram и Ollama

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_API_KEY` в env-файле
(для алертов, отчёта и cover-писем). Без Telegram — fallback в stdout, без ошибки.

## Шаг 1 — контрольный DRY_RUN на сервере

```bash
DRY_RUN=1 python3 -m src.pipeline && python3 evals/check_metrics.py
```
Ожидание: exit 0, `goal_reached: true`. Отклики НЕ отправляются (DRY_RUN=1).

## Шаг 2 — live-прогон на 2 отклика (ТОЛЬКО после явного ОК)

```bash
DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline && python3 evals/check_metrics.py
python3 -m evals.rate_cover_letters --sample 5   # LLM-рубрика ≥7/10
```
Проверить в `data/vacancies.json`: 2 записи со статусом «отправлено»,
письма в откликах на hh.ru. Это необратимое внешнее действие (реальные отклики
реальным работодателям) — поэтому первый live-прогон capped at `APPLY_LIMIT=2`.

## Шаг 3 — полный запуск по крону

1. Старый cron `99a55e0f5ac4` (legacy монолит): `cronjob pause` → `cronjob remove`.
2. `cronjob create` по `config/cron.yaml` (`DRY_RUN=0`, `APPLY_LIMIT=0`).
   Важно: `cronjob update` молча no-op на идентичном теле — менять через pause→remove→create.
3. Cron-обёртка авто-refresh токена (см. ниже).
4. Первый плановый прогон → Telegram-отчёт с числами.

### Авто-refresh токена по крону

`scripts/hh_token_refresh.sh` — обёртка над `hh_oauth_manager.py refresh`:
обновляет access_token, при фатале (`invalid_grant` / сетевая ошибка) шлёт Telegram-алерт.
Ставится отдельным cron-джобом (раз в сутки, до истечения access_token).

## Гарантии

- `data/vacancies.json` — source of truth; Sheets только пишется (tested: TC-05).
- Перезапись только с бэкапом `.bak` + atomic rename.
- `limit_exceeded`/API down → батч стоп, статус «не отправлено», перенос на следующий прогон.
- `test_required` → статус «тест», проходится вручную.
- refresh-token фатал / resume_not_found / captcha → Telegram-алерт.
- Secrets никогда не печатаются — `[REDACTED]` в логах/отчётах.