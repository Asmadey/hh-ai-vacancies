#!/usr/bin/env bash
# hh_token_refresh.sh — cron-обёртка авто-refresh HH.ru user OAuth токена.
#
# Обновляет access_token через refresh_token (scripts/hh_oauth_manager.py refresh),
# пишет пару в env-файл и data/hh_tokens.json. При фатале (invalid_grant / сеть
# недоступна) шлёт Telegram-алерт через src/telegram.send_alert.
#
# Ставится отдельным Hermes cron-джобом — раз в сутки, до истечения access_token
# (HH access_token живёт ~14 дней, refresh раньше не истекает при регулярном обновлении).
#
# Окружение: env-файл ищётся как $HH_ENV_FILE | ~/.hermes/.env | <repo>/../env.env
# (см. hh_oauth_manager._env_path). TELEGRAM_BOT_TOKEN/CHAT_ID — из env-файла.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# refresh; capture exit code (не прерываемся set -e, чтобы отправить алерт)
python3 "$HERE/hh_oauth_manager.py" refresh
rc=$?

if [ "$rc" -ne 0 ]; then
  # Алерт в Telegram через модуль пайплайна (single seam, HTML, esc).
  HH_PIPELINE_HOME="${HH_PIPELINE_HOME:-$REPO}" \
  python3 - "$REPO" <<'PYALERT'
import os, sys
sys.path.insert(0, sys.argv[1])  # noqa: E402
from src import config, telegram  # noqa: E402
msg = "HH.ru token refresh failed — нужен link + exchange (см. logs cron-джоба)."
try:
    telegram.send_alert(msg)
except Exception as e:
    # Telegram опционален; всегда дублируем в stdout (Hermes deliver: origin).
    print(f"[token-refresh] ALERT (telegram failed: {e}): {msg}", file=sys.stderr)
    sys.exit(0)
PYALERT
  echo "[token-refresh] failed (rc=$rc), alert sent" >&2
  exit "$rc"
fi

echo "[token-refresh] ok"
exit 0