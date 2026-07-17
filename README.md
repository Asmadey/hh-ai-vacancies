# HH.ru AI Vacancies

Cron-скрипт для сбора AI/PM вакансий с HeadHunter API → Google Sheets → Telegram.

## Структура

```
scripts/          — production скрипты (hh_ai_vacancies.py, hh_token_updater.py)
references/       — документация и incident-логи
templates/        — шаблоны для новых vacancy-трекеров
SKILL.md          — umbrella skill для Hermes Agent
```

## Cron

Job ID: `99a55e0f5ac4`  
Schedule: `0 9 */2 * *` (каждые 2 дня в 09:00 MSK)  
Deliver: Telegram

## Токен

`HH_APP_TOKEN` в `~/.hermes/.env`. Обновление через `scripts/hh_token_updater.py` (Playwright + OTP).
