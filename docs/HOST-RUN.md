# HOST-RUN — копируй-и-выполняй на Hermes-хосте

Минимальный runbook live e2e. Подробности — в `docs/DEPLOY.md`.
Перед стартом: `cd` в репо и `git pull` (чтобы подтянуть `hh_oauth_manager.py`).

## 0. Подтянуть код + обновить токен

```bash
cd ~/hh-ai-vacancies          # путь к репо на хосте
git pull origin main
python3 scripts/hh_oauth_manager.py refresh     # авто-refresh access_token
python3 scripts/hh_oauth_manager.py check       # убедиться, что токен жив
```

Если `refresh` упал с `invalid_grant` → refresh_token истёк:
`python3 scripts/hh_oauth_manager.py link` → авторизоваться → `exchange <code>`.

## 1. Проверить секреты в env-файле (~/.hermes/.env)

Нужны: `HH_CLIENT_ID`, `HH_CLIENT_SECRET`, `HH_REDIRECT_URI`,
`HH_RESUME_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_API_KEY`.
Токены лежат в `data/hh_tokens.json` (после шага 0).

## 2. Контрольный DRY_RUN (отклики НЕ уходят)

```bash
DRY_RUN=1 python3 -m src.pipeline && python3 evals/check_metrics.py
```
Ожидание: `exit 0`, `goal_reached: true`.

## 3. Live на 2 отклика (ТОЛЬКО после явного ОК)

```bash
DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline && python3 evals/check_metrics.py
python3 -m evals.rate_cover_letters --sample 5
```
Проверить: `data/vacancies.json` — 2 записи со статусом «отправлено»,
письма в откликах на hh.ru, строка в Telegram + таб `HH_AI` в Sheets.

## 4. Перевести крон на новый пайплайн

```bash
# убрать legacy монолит-крон
cronjob pause 99a55e0f5ac4
cronjob remove 99a55e0f5ac4
# поставить новый (config/cron.yaml: DRY_RUN=0, APPLY_LIMIT=0)
cronjob create -f config/cron.yaml
# отдельный крон авто-refresh токена (раз в сутки)
# → scripts/hh_token_refresh.sh
```

## Гарантии
- `data/vacancies.json` — source of truth, атомарная запись с `.bak`.
- `limit_exceeded`/API down → батч стоп, статус «не отправлено», перенос на след. прогон.
- refresh-token фатал / resume_not_found / captcha → Telegram-алерт.
- Secrets не печатаются — `[REDACTED]` в логах.