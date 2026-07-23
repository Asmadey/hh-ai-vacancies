#!/usr/bin/env python3
"""HH.ru OAuth2-менеджер: авторизация, обновление, проверка user-токенов.

Режимы (неинтерактивные, чтобы запускать из cron/Bash):

  link            — генерит PKCE, сохраняет verifier+state в env-файл,
                    печатает URL авторизации. Выйди по ссылке, авторизуйся на hh.ru,
                    из редиректа `...?code=...&state=...` скопируй параметр `code`.
  exchange <code> — меняет authorization_code на access+refresh, пишет пару
                    в env-файл (HH_OAUTH_*) И в data/hh_tokens.json (формат src/auth.py).
  refresh         — обновляет access_token через refresh_token (для cron),
                    пишет обе точки хранения. При invalid_grant — инструкция пере-авторизации.
  check           — тестовый запрос к /vacancies с текущим access_token.
  bridge          — только переложить HH_OAUTH_* из env-файла в data/hh_tokens.json.

Env-файл ищется так: $HH_ENV_FILE, затем ~/.hermes/.env (если есть), затем
<repo>/../env.env (файл-секретник на Mac). Формат — KEY=value.

HTTP гоняется через src/http_client.request (single seam) — это позволяет
тестировать offline, monkeypatch'ив один символ (TOK-06).
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: E402
from src import auth, config, http_client  # noqa: E402
from src.store import now_iso  # noqa: E402

AUTH_URL = "https://hh.ru/oauth/authorize"
TOKEN_URL = f"{config.HH_API}/token"
CHECK_URL = f"{config.HH_API}/vacancies?text=test&per_page=1"


def _env_path():
    """Где лежит env-файл с секретами."""
    if os.environ.get("HH_ENV_FILE"):
        return os.path.expanduser(os.environ["HH_ENV_FILE"])
    hermes = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(hermes):
        return hermes
    # Mac: DEMO/env.env — на уровень выше репо
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "env.env")


def load_env():
    env = {}
    path = _env_path()
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
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
    """Обновить/добавить KEY=value в env-файл (атомарно: tmp+rename)."""
    path = _env_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # совпадает либо `KEY=`, либо закомментированный плейсхолдер `# KEY=`
        if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.replace(tmp, path)


def _mask(token):
    if not token:
        return "[empty]"
    if len(token) <= 14:
        return f"{token[:4]}…{token[-2:]}"
    return f"{token[:8]}…{token[-4:]}"


def generate_pkce():
    """PKCE code_verifier + code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def write_tokens_to_store(access_token, refresh_token, expires_in):
    """Мост в data/hh_tokens.json (формат, что читает src/auth.py). Атомарно."""
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": int(expires_in or 0),
        "obtained_at": now_iso(),
    }
    auth.save_tokens(tokens)  # temp + os.replace; path = config.tokens_path()
    return tokens


def _save_pair(access_token, refresh_token, expires_in):
    """Пишет пару в env-файл (HH_OAUTH_*) и в data/hh_tokens.json."""
    save_env_key("HH_OAUTH_ACCESS_TOKEN", access_token)
    save_env_key("HH_OAUTH_REFRESH_TOKEN", refresh_token)
    # NOTE: do NOT overwrite HH_APP_TOKEN — that slot is for the APPL
    # (client_credentials) token used by legacy scrapers.  The user OAuth
    # pair lives in HH_OAUTH_ACCESS_TOKEN / HH_OAUTH_REFRESH_TOKEN and
    # data/hh_tokens.json.
    expires_at = int(datetime.now(timezone.utc).timestamp()) + int(expires_in or 0)
    save_env_key("HH_OAUTH_EXPIRES_AT", str(expires_at))
    write_tokens_to_store(access_token, refresh_token, expires_in)


def _token_post(payload):
    """POST /token через single seam. Возвращает (body_dict, resp). Поднять при сетевом фатале."""
    data = urllib.parse.urlencode(payload).encode()
    try:
        resp = http_client.request("POST", TOKEN_URL, headers={
            "User-Agent": config.HH_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }, data=data)
    except http_client.NetworkError as e:
        print(f"ERROR: token endpoint unreachable: {e}")
        sys.exit(1)
    return resp.json(), resp


def mode_link():
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    redirect_uri = env.get("HH_REDIRECT_URI", "")
    if not client_id:
        print("ERROR: HH_CLIENT_ID не найден в env-файле")
        sys.exit(1)
    if not redirect_uri:
        print("ERROR: HH_REDIRECT_URI не найден в env-файле")
        sys.exit(1)

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    save_env_key("HH_OAUTH_CODE_VERIFIER", verifier)
    save_env_key("HH_OAUTH_STATE", state)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "state": state,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
}
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("=" * 64)
    print("HH.ru OAuth2 — авторизация (режим link)")
    print("=" * 64)
    print(f"env-файл:     {_env_path()}")
    print(f"redirect_uri: {redirect_uri}")
    print(f"state:        {state}")
    print()
    print("1) Перейди по ссылке и авторизуйся на hh.ru:")
    print()
    print(auth_url)
    print()
    print("2) После авторизации браузер редиректнет на:")
    print(f"   {redirect_uri}?code=XXXXX&state={state}")
    print()
    print("3) Скопируй параметр `code` из URL и передай его в exchange:")
    print(f"   python3 {sys.argv[0]} exchange <code>")


def exchange_code(code):
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    client_secret = env.get("HH_CLIENT_SECRET", "")
    redirect_uri = env.get("HH_REDIRECT_URI", "")
    verifier = env.get("HH_OAUTH_CODE_VERIFIER", "")
    if not (client_id and client_secret and redirect_uri and verifier):
        print("ERROR: не хватает HH_CLIENT_ID/SECRET/REDIRECT_URI/CODE_VERIFIER в env-файле")
        print("       Сначала запусти `link`.")
        sys.exit(1)

    body, resp = _token_post({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    })
    if resp.status != 200:
        print(f"ERROR: HTTP {resp.status}: {json.dumps(body)[:300]}")
        sys.exit(1)

    access_token = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")
    expires_in = body.get("expires_in", 0)
    if not access_token:
        print(f"ERROR: нет access_token в ответе: {json.dumps(body)[:300]}")
        sys.exit(1)

    _save_pair(access_token, refresh_token, expires_in)
    print("✅ Tokens сохранены:")
    print(f"   access_token:  {_mask(access_token)}")
    print(f"   refresh_token: {_mask(refresh_token)}")
    print(f"   expires_in:    {expires_in}s ({int(expires_in)//86400}д)")
    print(f"   env-файл:      {_env_path()}")
    print(f"   hh_tokens.json: {config.tokens_path()}")


def mode_refresh():
    env = load_env()
    client_id = env.get("HH_CLIENT_ID", "")
    client_secret = env.get("HH_CLIENT_SECRET", "")
    refresh_token = env.get("HH_OAUTH_REFRESH_TOKEN", "")
    if not (client_id and client_secret):
        print("ERROR: HH_CLIENT_ID/HH_CLIENT_SECRET не найдены в env-файле")
        sys.exit(1)
    if not refresh_token:
        print("ERROR: HH_OAUTH_REFRESH_TOKEN отсутствует — запусти `link` + `exchange`.")
        sys.exit(1)

    body, resp = _token_post({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    if resp.status != 200:
        err = body.get("error", "")
        desc = body.get("error_description", "")
        print(f"ERROR: refresh failed HTTP {resp.status}: {err}/{desc}")
        if resp.status == 400 or err == "invalid_grant":
            print()
            print("Refresh_token истёк или невалиден. Пере-авторизуйся:")
            print(f"  python3 {sys.argv[0]} link")
            print(f"  python3 {sys.argv[0]} exchange <code>")
        sys.exit(1)

    access_token = body.get("access_token", "")
    new_refresh = body.get("refresh_token", "") or refresh_token
    expires_in = body.get("expires_in", 0)
    if not access_token:
        print(f"ERROR: нет access_token в ответе: {json.dumps(body)[:300]}")
        sys.exit(1)

    _save_pair(access_token, new_refresh, expires_in)
    print(f"✅ Token refreshed: {_mask(access_token)}  (expires in {expires_in}s)")
    print(f"   new refresh_token: {_mask(new_refresh)}")
    print(f"   hh_tokens.json: {config.tokens_path()}")


def mode_check():
    env = load_env()
    token = env.get("HH_OAUTH_ACCESS_TOKEN", "")
    if not token:
        print("ERROR: HH_OAUTH_ACCESS_TOKEN не задан в env-файле")
        sys.exit(1)
    print(f"access_token: {_mask(token)}")

    expires_at = env.get("HH_OAUTH_EXPIRES_AT", "")
    if expires_at:
        now = datetime.now(timezone.utc).timestamp()
        remaining = int(expires_at) - now
        if remaining > 0:
            print(f"expires in: {remaining}s ({remaining//86400}д {remaining%86400//3600}ч)")
        else:
            print(f"EXPIRED {abs(int(remaining))}s ago — нужен refresh")

    try:
        resp = http_client.request("GET", CHECK_URL, headers={
            "User-Agent": config.HH_USER_AGENT,
            "Authorization": f"Bearer {token}",
        })
    except http_client.NetworkError as e:
        print(f"ERROR: API unreachable: {e}")
        sys.exit(1)
    if resp.status != 200:
        print(f"❌ API Error {resp.status}: {resp.text[:200]}")
        sys.exit(1)
    found = resp.json().get("found", 0)
    print(f"✅ API OK: found {found} vacancies (test query)")


def mode_bridge():
    """Переложить HH_OAUTH_* из env-файла в data/hh_tokens.json."""
    env = load_env()
    access = env.get("HH_OAUTH_ACCESS_TOKEN", "")
    refresh = env.get("HH_OAUTH_REFRESH_TOKEN", "")
    expires_in = env.get("HH_OAUTH_EXPIRES_AT", "0")
    if not access:
        print("ERROR: HH_OAUTH_ACCESS_TOKEN пуст в env-файле — bridge не из чего")
        sys.exit(1)
    now = int(datetime.now(timezone.utc).timestamp())
    try:
        remaining = int(expires_in) - now
    except ValueError:
        remaining = 0
    tokens = write_tokens_to_store(access, refresh, max(remaining, 0))
    print(f"✅ Bridge: data/hh_tokens.json записан ({config.tokens_path()})")
    print(f"   access_token: {_mask(access)}  refresh_token: {_mask(refresh)}  expires_in: {tokens['expires_in']}s")


USAGE = """
HH.ru OAuth2 Token Manager

Usage:
  python3 hh_oauth_manager.py <mode> [args]

Modes:
  link              Сгенерить URL авторизации (PKCE), сохранить verifier+state
  exchange <code>   Поменять authorization_code на access+refresh
  refresh           Обновить access_token через refresh_token (cron)
  check             Проверить, что текущий access_token работает
  bridge            Переложить HH_OAUTH_* из env-файла в data/hh_tokens.json

Env-файл (KEY=value): $HH_ENV_FILE | ~/.hermes/.env | <repo>/../env.env
"""


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)
    mode = sys.argv[1].lower()
    if mode == "link":
        mode_link()
    elif mode == "exchange":
        if len(sys.argv) < 3:
            print("ERROR: нужен authorization_code: `exchange <code>`")
            sys.exit(1)
        exchange_code(sys.argv[2].strip())
    elif mode == "refresh":
        mode_refresh()
    elif mode == "check":
        mode_check()
    elif mode == "bridge":
        mode_bridge()
    else:
        print(f"Unknown mode: {mode}")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()