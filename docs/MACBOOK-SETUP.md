# MacBook Setup — live e2e на домашнем IP

Пайплайн работает на MacBook с residential IP — HH.ru пропускает
`POST /negotiations` (отклики) с пользовательских IP.

## 1. Клонировать репо

```bash
cd ~
git clone https://github.com/Asmadey/hh-ai-vacancies.git
cd hh-ai-vacancies
```

## 2. Создать env-файл

Создай `~/.hermes/.env` (или укажи путь через `HH_ENV_FILE`):

```bash
mkdir -p ~/.hermes
cat > ~/.hermes/.env << 'EOF'
HH_CLIENT_ID=JD9AIDP6NSM9M3HO56OR89M71FB3ELT9IMLHLSLI0A2QCGRBQAMKA703SC2K90C0
HH_CLIENT_SECRET=<вставь из dev.hh.ru>
HH_REDIRECT_URI=https://piramiza.com/rest/oauth2-credential/callback
HH_RESUME_ID=dde52705ff1076b2fe0039ed1f6255396b6135
TELEGRAM_BOT_TOKEN=<вставь токен бота>
TELEGRAM_CHAT_ID=128204572
OLLAMA_API_KEY=<вставь Ollama Cloud API key>
EOF
chmod 600 ~/.hermes/.env
```

## 3. OAuth авторизация (одноразово)

```bash
python3 scripts/hh_oauth_manager.py link
# → открой ссылку в браузере, авторизуйся на hh.ru
# → скопируй параметр code из редиректа
python3 scripts/hh_oauth_manager.py exchange <code>
# → токены сохранены в data/hh_tokens.json
```

Проверка:
```bash
python3 scripts/hh_oauth_manager.py check
# → должно быть ✅ API OK
```

## 4. Google Sheets credentials

```bash
mkdir -p ~/.config/gws
# скопируй credentials.json с VPS или создай новый OAuth-клиент
# → ~/.config/gws/credentials.json
```

## 5. Тесты

```bash
python3 -m pytest                          # 65 тестов, все должны пройти
```

## 6. DRY_RUN (отклики НЕ уходят)

```bash
DRY_RUN=1 python3 -m src.pipeline
python3 evals/check_metrics.py
# → goal_reached: true
```

## 7. Live на 2 отклика (после явного ОК)

```bash
DRY_RUN=0 APPLY_LIMIT=2 python3 -m src.pipeline
python3 evals/check_metrics.py
python3 -m evals.rate_cover_letters --sample 5
```

Проверить:
- `data/vacancies.json` — 2 записи со статусом «отправлено»
- Отклики на hh.ru (в разделе «Отклики»)
- Telegram отчёт
- Таб `HH_AI` в Google Sheets

## 8. Cron на MacBook

### Вариант A: Hermes Agent cron (если Hermes установлен на Mac)

```bash
# Token refresh — раз в сутки
cronjob create \
  --name "HH Token Refresh" \
  --schedule "0 8 * * *" \
  --script "python3 ~/hh-ai-vacancies/scripts/hh_token_refresh.sh" \
  --no-agent

# Pipeline — каждые 2 дня в 09:00 MSK
cronjob create \
  --name "HH.ru AI автоотклики" \
  --schedule "0 9 */2 * *" \
  --script "DRY_RUN=0 APPLY_LIMIT=0 python3 -m src.pipeline" \
  --workdir ~/hh-ai-vacancies \
  --no-agent
```

### Вариант B: системный crontab (macOS)

```bash
crontab -e
```

```cron
# HH token refresh — ежедневно 08:55 MSK (06:55 UTC летом)
55 6 * * * cd ~/hh-ai-vacancies && python3 scripts/hh_token_refresh.sh >> /tmp/hh_token_refresh.log 2>&1

# HH pipeline — каждые 2 дня 09:00 MSK (07:00 UTC летом)
0 7 */2 * * cd ~/hh-ai-vacancies && DRY_RUN=0 APPLY_LIMIT=0 python3 -m src.pipeline >> /tmp/hh_pipeline.log 2>&1
```

### Вариант C: launchd (macOS native)

Создай `~/Library/LaunchAgents/com.hh-ai-vacancies.pipeline.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hh-ai-vacancies.pipeline</string>
    <key>ProgramArguments</key>
    <array>
        <string>python3</string>
        <string>-m</string>
        <string>src.pipeline</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USERNAME/hh-ai-vacancies</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DRY_RUN</key>
        <string>0</string>
        <key>APPLY_LIMIT</key>
        <string>0</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Weekday</key>
        <integer>1</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/hh_pipeline.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/hh_pipeline.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.hh-ai-vacancies.pipeline.plist
```

## 9. Проверка cron

```bash
# Ручной запуск (имитация cron)
cd ~/hh-ai-vacancies
python3 scripts/hh_token_refresh.sh        # refresh токена
DRY_RUN=1 python3 -m src.pipeline          # контрольный прогон
python3 evals/check_metrics.py             # проверка метрик
```

## Troubleshooting

### 403 forbidden на /negotiations или /resumes/mine
- Проверь что ты на residential IP (не VPN, не прокси)
- Проверь что token начинается с `USER` (не `APPL`)
- Проверь `data/hh_tokens.json` — должен содержать `access_token` + `refresh_token`

### invalid_grant при refresh
- Refresh token истёк (одноразовый) —重新 авторизуйся: `link` → `exchange`

### HH_APP_TOKEN перетирается user-токеном
- Исправлено в commit 97defec — больше `_save_pair` не трогает `HH_APP_TOKEN`