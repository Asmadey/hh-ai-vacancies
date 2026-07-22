HH.RU TOKEN AUTO-REFRESH — ПОЛНЫЙ КОМПЛЕКТ
================================================

1. hh_oauth_manager.py — OAuth2 token manager
2. hh_token_refresh.sh — cron wrapper

======================================================================
FILE 1: hh_oauth_manager.py
======================================================================

#!/usr/bin/env python3
"""
HH.ru OAuth2 token manager — автоматическое обновление токенов.

Режимы работы:

1. Авторизация (один раз):
   python3 hh_oauth_manager.py auth
   → Открывает браузер/выдаёт ссылку для авторизации на hh.ru
   → Ловит callback на локальном сервере (порт 9876)
   → Обменивает code на access_token + refresh_token
   → Сохраняет токены в ~/.hermes/.env

2. Обновление токена (автоматически, по cron):
   python3 hh_oauth_manager.py refresh
   → Использует refresh_token из .env
   → Получает новую пару access_token + refresh_token
   → Обновляет .env
   → Если refresh_token истёк, выводит ссылку для повторной авторизации

3. Проверка токена:
   python3 hh_oauth_manager.py check
   → Делает тестовый запрос к API
   → Показывает статус токена

4. Генерация только ссылки (без локального сервера):
   python3 hh_oauth_manager.py link
   → Выдаёт OAuth URL для ручного перехода
   → После редиректа вставь ?code=... в stdin

Использование в cron:
   Добавь в cron скрипт, который за 5 минут до запуска парсера
   вызывает `hh_oauth_manager.py refresh` для обновления токена.

Требования:
   - redirect_uri в настройках приложения на dev.hh.ru должен быть
     http://piramiza.com/rest/oauth2-credential/callback
   - Для локального callback скрипт временно стартует сервер на порту 9876
   - Если piramiza.com проксирует callback на этот порт — работает автоматически
   - Иначе: режим `link` + ручная вставка code

Файлы:
   ~/.hermes/.env — хранит HH_CLIENT_ID, HH_CLIENT_SECRET, HH_APP_TOKEN,
                     HH_OAUTH_ACCESS_TOKEN, HH_OAUTH_REFRESH_TOKEN
"""
import hashlib
import base64
import json
import os
import re
import secrets
import socket
import sys
import time
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

ENV_PATH = os.path.expanduser("~/.hermes/.env")
TOKEN_URL = "https://api.hh.ru/token"
AUTH_URL = "https://hh.ru/oauth/authorize"
API_VACANCIES_URL = "https://api.hh.ru/vacancies?text=test&per_page=1"
REDIRECT_URI = "https://piramiza.com/rest/oauth2-credential/callback"
LOCAL_CALLBACK_PORT = 9876
HH_USER_AGENT = "AI/PM Vacancy Bot / 1.0 (sagestaf@gmail.com)"


def load_env():
    env = {}
    if not os.path.exists(ENV_PATH):
        return env
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            env[key] = val
    return env


def save_env_key(key, value):
    """Update or add a key in .env file."""
    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "w") as f:
            f.write(f"{key}={value}\n")
        return
    
    with open(ENV_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}=") and not line.strip().startswith("#"):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        new_lines.append(f"{key}={value}\n")
    
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


# --------------------------------------------------------------------------- #
# Mode: link (generate auth URL only)
# --------------------------------------------------------------------------- #

def mode_link():
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    if not client_id:
        print("ERROR: HH_CLIENT_ID not found in .env")
        sys.exit(1)
    
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    
    # Save PKCE verifier for later use
    save_env_key("HH_OAUTH_CODE_VERIFIER", verifier)
    save_env_key("HH_OAUTH_STATE", state)
    
    params = {
        "response_type": "code",
        "client_id": client_id,
        "state": state,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    
    print("=" * 60)
    print("HH.ru OAuth2 Authorization")
    print("=" * 60)
    print()
    print("Перейди по ссылке для авторизации:")
    print()
    print(auth_url)
    print()
    print("После авторизации браузер редиректнет на:")
    print(f"  {REDIRECT_URI}?code=XXXXX&state={state}")
    print()
    print("Скопируй параметр ?code=... из URL и вставь его сюда:")
    print()
    
    # Read code from stdin
    code_input = input("authorization_code: ").strip()
    
    if not code_input:
        print("ERROR: No code provided")
        sys.exit(1)
    
    exchange_code(code_input, verifier)


# --------------------------------------------------------------------------- #
# Mode: auth (local server callback)
# --------------------------------------------------------------------------- #

class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""
    auth_code = None
    auth_state = None
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        if "code" in params:
            CallbackHandler.auth_code = params["code"][0]
            CallbackHandler.auth_state = params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>OK! Token received.</h1><p>Can close this tab.</p></body></html>")
        elif "error" in params:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            error = params.get("error", ["unknown"])[0]
            self.wfile.write(f"<html><body><h1>Error: {error}</h1></body></html>".encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Suppress logs


def mode_auth():
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    if not client_id:
        print("ERROR: HH_CLIENT_ID not found in .env")
        sys.exit(1)
    
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    
    save_env_key("HH_OAUTH_CODE_VERIFIER", verifier)
    save_env_key("HH_OAUTH_STATE", state)
    
    params = {
        "response_type": "code",
        "client_id": client_id,
        "state": state,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    
    print("=" * 60)
    print("HH.ru OAuth2 Authorization (local server mode)")
    print("=" * 60)
    print()
    print("1. Перейди по ссылке:")
    print()
    print(auth_url)
    print()
    print(f"2. Локальный сервер слушает на порту {LOCAL_CALLBACK_PORT}")
    print(f"   Callback URL: {REDIRECT_URI}")
    print(f"   Убедись что piramiza.com проксирует /rest/oauth2-credential/callback")
    print(f"   на порт {LOCAL_CALLBACK_PORT} этого сервера.")
    print()
    print("3. После авторизации на hh.ru токен будет получен автоматически.")
    print("   Если сервер не доступен — используй режим 'link' вместо 'auth'.")
    print()
    print("Waiting for callback... (Ctrl+C to abort)")
    
    # Start local server
    server = HTTPServer(("0.0.0.0", LOCAL_CALLBACK_PORT), CallbackHandler)
    server.timeout = 300  # 5 minutes
    
    try:
        server.handle_request()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    finally:
        server.server_close()
    
    if CallbackHandler.auth_code:
        print(f"\nGot authorization code: {CallbackHandler.auth_code[:10]}...")
        if CallbackHandler.auth_state and CallbackHandler.auth_state != state:
            print("WARNING: State mismatch! Possible CSRF attack.")
            sys.exit(1)
        exchange_code(CallbackHandler.auth_code, verifier)
    else:
        print("\nERROR: No code received. Timeout or error.")
        print("Use 'link' mode instead: python3 hh_oauth_manager.py link")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Exchange code for tokens
# --------------------------------------------------------------------------- #

def exchange_code(code, verifier):
    """Exchange authorization code for access_token + refresh_token."""
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    client_secret = env.get("HH_CLIENT_SECRET", "")
    
    if not client_id or not client_secret:
        print("ERROR: HH_CLIENT_ID or HH_CLIENT_SECRET not in .env")
        sys.exit(1)
    
    payload = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode()
    
    req = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", HH_USER_AGENT)
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        
        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 0)
        token_type = data.get("token_type", "")
        
        if not access_token:
            print(f"ERROR: No access_token in response: {data}")
            sys.exit(1)
        
        # Save to .env
        save_env_key("HH_OAUTH_ACCESS_TOKEN", access_token)
        save_env_key("HH_OAUTH_REFRESH_TOKEN", refresh_token)
        save_env_key("HH_APP_TOKEN", access_token)  # Also update HH_APP_TOKEN for scrapers
        
        # Calculate expiry
        expires_at = datetime.now(timezone.utc).timestamp() + expires_in
        save_env_key("HH_OAUTH_EXPIRES_AT", str(int(expires_at)))
        
        print()
        print("=" * 60)
        print("✅ Tokens saved to .env:")
        print(f"  HH_OAUTH_ACCESS_TOKEN = {access_token[:15]}...{access_token[-6:]}")
        print(f"  HH_OAUTH_REFRESH_TOKEN = {refresh_token[:15]}...{refresh_token[-6:]}")
        print(f"  HH_APP_TOKEN = {access_token[:15]}...{access_token[-6:]}")
        print(f"  Expires in: {expires_in} seconds ({expires_in // 86400} days)")
        print("=" * 60)
        print()
        print("Токен обновлён. Парсеры могут использовать HH_APP_TOKEN из .env.")
        
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        print(f"ERROR: HTTP {e.code}: {err}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Mode: refresh (auto-renew using refresh_token)
# --------------------------------------------------------------------------- #

def mode_refresh():
    """Refresh access_token using refresh_token."""
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    client_secret = env.get("HH_CLIENT_SECRET", "")
    refresh_token = env.get("HH_OAUTH_REFRESH_TOKEN", "")
    
    if not client_id or not client_secret:
        print("ERROR: HH_CLIENT_ID or HH_CLIENT_SECRET not in .env")
        sys.exit(1)
    
    if not refresh_token:
        print("ERROR: HH_OAUTH_REFRESH_TOKEN not in .env")
        print("Run 'auth' or 'link' mode first to get tokens.")
        sys.exit(1)
    
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }).encode()
    
    req = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", HH_USER_AGENT)
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        
        access_token = data.get("access_token", "")
        new_refresh_token = data.get("refresh_token", "")
        expires_in = data.get("expires_in", 0)
        
        if not access_token:
            print(f"ERROR: No access_token in response: {data}")
            sys.exit(1)
        
        # Save updated tokens
        save_env_key("HH_OAUTH_ACCESS_TOKEN", access_token)
        save_env_key("HH_OAUTH_REFRESH_TOKEN", new_refresh_token)
        save_env_key("HH_APP_TOKEN", access_token)
        
        expires_at = datetime.now(timezone.utc).timestamp() + expires_in
        save_env_key("HH_OAUTH_EXPIRES_AT", str(int(expires_at)))
        
        print(f"✅ Token refreshed: {access_token[:15]}...{access_token[-6:]}")
        print(f"   Expires in: {expires_in}s ({expires_in // 86400}d)")
        print(f"   New refresh_token: {new_refresh_token[:15]}...{new_refresh_token[-6:]}")
        
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        print(f"ERROR: HTTP {e.code}: {err}")
        if e.code == 400:
            print()
            print("Refresh token expired or invalid.")
            print("Run 'link' mode to re-authorize:")
            print(f"  python3 {sys.argv[0]} link")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Mode: check (verify token works)
# --------------------------------------------------------------------------- #

def mode_check():
    """Check if current token works."""
    env = load_env()
    token = env.get("HH_APP_TOKEN", "")
    
    if not token:
        print("ERROR: HH_APP_TOKEN not set in .env")
        sys.exit(1)
    
    print(f"Token: {token[:15]}...{token[-6:]}")
    
    # Check expiry
    expires_at = env.get("HH_OAUTH_EXPIRES_AT", "")
    if expires_at:
        now = datetime.now(timezone.utc).timestamp()
        remaining = int(expires_at) - now
        if remaining > 0:
            print(f"Expires in: {remaining}s ({remaining // 86400}d {remaining % 86400 // 3600}h)")
        else:
            print(f"EXPIRED {abs(remaining)}s ago — needs refresh")
    
    req = urllib.request.Request(API_VACANCIES_URL)
    req.add_header("User-Agent", HH_USER_AGENT)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("HH-User-Agent", HH_USER_AGENT)
    
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        found = data.get("found", 0)
        print(f"✅ API OK: found {found} vacancies for test query")
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:200]
        print(f"❌ API Error {e.code}: {err}")
        if "token_revoked" in err or "token-revoked" in err:
            print("Token revoked. Run 'refresh' or 'link' mode.")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

USAGE = """
HH.ru OAuth2 Token Manager

Usage:
  python3 hh_oauth_manager.py <mode>

Modes:
  auth     — Start local server + open browser (requires piramiza.com proxy)
  link     — Generate auth URL only, read code from stdin (manual)
  refresh  — Auto-refresh using refresh_token (for cron)
  check    — Test if current token works

Examples:
  python3 hh_oauth_manager.py link       # First time: get auth URL
  python3 hh_oauth_manager.py refresh     # Cron: auto-renew
  python3 hh_oauth_manager.py check      # Verify token
"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)
    
    mode = sys.argv[1].lower()
    
    if mode == "auth":
        mode_auth()
    elif mode == "link":
        mode_link()
    elif mode == "refresh":
        mode_refresh()
    elif mode == "check":
        mode_check()
    else:
        print(f"Unknown mode: {mode}")
        print(USAGE)
        sys.exit(1)

======================================================================
FILE 2: hh_token_refresh.sh
======================================================================

#!/bin/bash
# HH.ru token refresh wrapper — runs before scrapers to keep token alive.
# Called by cron 5 minutes before vacancy scrapers.
# If refresh fails (refresh_token expired), sends Telegram alert with auth link.
set -euo pipefail

export HOME=/home/hermes

PYTHON=/usr/bin/python3
SCRIPT=/home/hermes/.hermes/scripts/hh_oauth_manager.py
ENV_FILE=/home/hermes/.hermes/.env

# Load Telegram creds for alerts
TG_TOKEN=""
TG_CHAT=""
if [ -f "$ENV_FILE" ]; then
    TG_TOKEN=$(grep -E "^TELEGRAM_BOT_TOKEN=" "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"' | tr -d "'")
    TG_CHAT=$(grep -E "^TELEGRAM_CHAT_ID=" "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"' | tr -d "'")
fi

send_alert() {
    local msg="$1"
    if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
            -d chat_id="$TG_CHAT" \
            -d text="$msg" \
            -d parse_mode=HTML >/dev/null 2>&1 || true
    fi
    echo "$msg" >&2
}

# Check if we have a refresh_token
HAS_REFRESH=$(grep -c "^HH_OAUTH_REFRESH_TOKEN=" "$ENV_FILE" 2>/dev/null || echo "0")

if [ "$HAS_REFRESH" -eq 0 ]; then
    # No refresh token — try using current HH_APP_TOKEN as-is
    # (application tokens don't expire, they get revoked)
    echo "[HH Token] No OAuth refresh token. Using HH_APP_TOKEN as-is."
    exit 0
fi

# Try to refresh
OUTPUT=$($PYTHON "$SCRIPT" refresh 2>&1) || {
    # Refresh failed — send alert
    ALERT="⚠️ HH.ru OAuth token refresh failed.

$OUTPUT

Для обновления токена запусти:
  python3 ~/.hermes/scripts/hh_oauth_manager.py link

Или открой ссылку в браузере и передай code в скрипт."
    send_alert "$ALERT"
    exit 1
}

echo "[HH Token] $OUTPUT"