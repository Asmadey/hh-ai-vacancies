# Деплой автономных откликов (T7–T9)

## Шаг 0 — одноразовый setup (единственный шаг с участием Влада)

1. **User OAuth** (app token НЕ подходит для /negotiations):
   - Открыть `https://hh.ru/oauth/authorize?response_type=code&client_id={CLIENT_ID}` → войти → получить `code` из redirect.
   - Обменять: `POST https://api.hh.ru/token` с `grant_type=authorization_code&client_id=...&client_secret=...&code=...`
   - Сохранить в `data/hh_tokens.json`:
     ```json
     {"access_token": "...", "refresh_token": "...", "expires_in": 1209600, "obtained_at": "<now>"}
     ```
   - Дальше refresh автоматический (src/auth.py), участие не нужно.
2. **resume_id**: `GET https://api.hh.ru/resumes/mine` (с user-токеном) → выбрать id → в `~/.hermes/.env`: `HH_RESUME_ID=...`
3. `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` в `~/.hermes/.env` (для алертов и отчёта).

## Шаг 1 — миграция состояния

```bash
python3 -m scripts.migrate_seen        # ~/.hermes/hh_ai_seen.json → data/vacancies.json
```
(также выполняется автоматически при первом прогоне, если vacancies.json пуст)

## Шаг 2 — контрольный DRY_RUN на сервере

```bash
DRY_RUN=1 python3 -m src.pipeline && python3 evals/check_metrics.py
```
Ожидание: exit 0, `goal_reached: true`.

## Шаг 3 — T7: live-прогон на 2 отклика (ТОЛЬКО после OK Влада)

```bash
DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline && python3 evals/check_metrics.py
python3 -m evals.rate_cover_letters --sample 5   # LLM-рубрика ≥7/10
```
Проверить в JSON: 2 записи со статусом «отправлено», письма в откликах на hh.ru.

## Шаг 4 — T9: полный запуск

1. Старый cron `99a55e0f5ac4`: `cronjob pause` → `cronjob remove`.
2. `cronjob create` по `config/cron.yaml` (`DRY_RUN=0`, `APPLY_LIMIT=0`).
3. Первый плановый прогон → Telegram-отчёт с числами.

## Гарантии

- `data/vacancies.json` — source of truth; Sheets только пишется (tested: TC-05).
- Перезапись только с бэкапом `.bak` + atomic rename.
- `limit_exceeded`/API down → батч стоп, статус «не отправлено», перенос на следующий прогон.
- `test_required` → статус «тест», проходится вручную.
- refresh-token фатал / resume_not_found / captcha → Telegram-алерт.
