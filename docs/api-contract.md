# API Contract: автономные отклики HH.ru (T1)

Верифицировано по официальным докам `github.com/hhru/api` (docs/negotiations.md, docs/errors.md, docs/authorization_for_user.md) и OpenAPI (`api.hh.ru/openapi/redoc`), 2026-07-18.

## 1. POST /negotiations — отклик на вакансию

```
POST https://api.hh.ru/negotiations
Authorization: Bearer {user_access_token}     # ТОЛЬКО user token, app token → 403 oauth/user_auth_expected
User-Agent: Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)
Content-Type: multipart/form-data

vacancy_id={id}&resume_id={resume_id}&message={cover_letter}
```

- Успех: **201 Created**, заголовок `Location: /negotiations/{nid}`. Тело может быть пустым.
- Формат ошибок: `{"errors": [{"type": "...", "value": "..."}]}`.

### Ошибки negotiations (маппинг на статусы пайплайна)

| HTTP | type | value | Статус записи | Действие |
|------|------|-------|----------|----------|
| 201 | — | — | `отправлено` | пауза → следующая |
| 403 | negotiations | `test_required` | `тест` | отклик через API недоступен; вручную |
| 400/403 | negotiations | `limit_exceeded` | `не отправлено` (reason=limit_exceeded) | **stop батча**, перенос на след. прогон |
| 403 | negotiations | `already_applied` | `отправлено` (reason=already_applied) | дубль связки resume+vacancy, не ошибка |
| 403 | negotiations | `invalid_vacancy` / `archived` | `не отправлено` (reason=invalid_vacancy) | вакансия скрыта/в архиве, не ретраить |
| 400/403 | negotiations | `resume_not_found` | `не отправлено` (reason=resume_not_found) | **stop батча** + Telegram-алерт (resume_id битый) |
| 403 | negotiations | `application_denied` | `не отправлено` (reason=denied) | не ретраить |
| 429 | — | — | retry | backoff: `Retry-After` или экспонента (5→10→20с), макс 3 попытки, затем `не отправлено` (reason=rate_limited) |
| 5xx / network | — | — | `не отправлено` (reason=api_down) | **stop батча** (API down), перенос |
| 403 | captcha_required | — | `не отправлено` (reason=captcha) | stop + алерт |

### Rate limits
- Официальных числовых лимитов HH не публикует; сигнал — **429 + `Retry-After`**.
- Продуктовый лимит соискателя: **~200 откликов / сутки** → приходит как `limit_exceeded`.
- Пайплайн: пауза `APPLY_PAUSE_SEC` (default 5 c) между POST, уважение `Retry-After`, `APPLY_LIMIT` за прогон.

## 2. POST /token — refresh user-токена

```
POST https://api.hh.ru/token          # альяс hh.ru/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&refresh_token={refresh_token}
```

- Успех: 200 `{access_token, refresh_token, expires_in, token_type}`. **refresh_token одноразовый** — в ответе приходит новая пара, обе надо сохранить атомарно (`data/hh_tokens.json`).
- `400 invalid_grant / token not expired` — access ещё жив, обновлять нельзя → продолжаем со старым.
- `400 invalid_grant / token has already been refreshed` — пара потеряна (сохранили не атомарно) → фатал, Telegram-алерт, нужна повторная авторизация.
- `400 invalid_grant / token was revoked|deactivated|bad token` — фатал → Telegram-алерт, повторная авторизация пользователя.

### Триггер refresh в пайплайне
Любой запрос с `403 {"type":"oauth","value":"token_expired"|"bad_authorization"}` → один refresh → один retry запроса. Второй подряд 403 → фатал + алерт.

## 3. Прочее
- `User-Agent` обязателен для всех запросов (иначе `400 bad_user_agent`).
- GET /vacancies (поиск) и GET /vacancies/{id} (enrich) работают и с app-токеном, но пайплайн использует один user-токен для всего.
- Setup (одноразово, вне петли): authorization_code flow на hh.ru → access+refresh, и `GET /resumes/mine` → выбрать `resume_id` → env `HH_RESUME_ID`.
