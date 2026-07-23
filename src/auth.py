"""User OAuth: access/refresh tokens, авто-refresh при 403 oauth, алерт при фатале.
Tokens: data/hh_tokens.json {access_token, refresh_token, obtained_at, expires_in}.

APPL fallback: on datacenter IPs the user token gets 403 "forbidden" on
read endpoints (GET /vacancies, GET /vacancies/{id}).  When that happens we
transparently fall back to the APPL (client_credentials) token for read
operations.  POST /negotiations still requires the user token and will only
work from a residential IP."""
import json
import os
import sys
import urllib.parse

from . import config, http_client, telegram
from .store import now_iso

TOKEN_URL = f"{config.HH_API}/token"

# --- APPL token fallback (client_credentials) ------------------------------- #
_APPL_TOKEN = None  # cached APPL token


def _get_appl_token():
    """Get APPL token via client_credentials grant. Cached per-process."""
    global _APPL_TOKEN
    if _APPL_TOKEN:
        return _APPL_TOKEN
    # Try ~/.hermes/cache/hh_token.json first (shared with other scripts)
    cache_path = os.path.expanduser("~/.hermes/cache/hh_token.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                _APPL_TOKEN = json.load(f).get("access_token", "")
                if _APPL_TOKEN:
                    return _APPL_TOKEN
        except Exception:
            pass
    # Fall back to HH_APP_TOKEN from env
    _APPL_TOKEN = os.environ.get("HH_APP_TOKEN", "")
    return _APPL_TOKEN


class AuthError(Exception):
    pass


def load_tokens(path=None):
    path = path or config.tokens_path()
    if not os.path.exists(path):
        raise AuthError(f"Token file not found: {path}. Пройди одноразовую OAuth-авторизацию (см. docs/api-contract.md §3).")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_tokens(tokens, path=None):
    """Atomic: refresh_token одноразовый, потеря пары = повторная авторизация."""
    path = path or config.tokens_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(tokens, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def refresh(tokens, path=None):
    """POST /token grant_type=refresh_token. Returns new tokens dict. Raises AuthError on fatal."""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens.get("refresh_token", ""),
    }).encode()
    try:
        resp = http_client.request("POST", TOKEN_URL, headers={
            "User-Agent": config.HH_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }, data=data)
    except http_client.NetworkError as e:
        raise AuthError(f"token endpoint unreachable: {e}")

    if resp.status == 200:
        body = resp.json()
        new_tokens = {
            "access_token": body["access_token"],
            "refresh_token": body.get("refresh_token", tokens.get("refresh_token", "")),
            "expires_in": body.get("expires_in", 0),
            "obtained_at": now_iso(),
        }
        save_tokens(new_tokens, path)
        return new_tokens

    body = resp.json()
    desc = body.get("error_description", "")
    if body.get("error") == "invalid_grant" and "not expired" in desc:
        # access ещё жив — работаем со старым
        return tokens
    raise AuthError(f"refresh failed HTTP {resp.status}: {body.get('error')}/{desc}")


def _is_auth_error(resp):
    if resp.status != 403:
        return False
    errors = resp.json().get("errors", [])
    return any(e.get("type") == "oauth" for e in errors)


def _is_forbidden(resp):
    """Generic 403 forbidden (not oauth error) — IP block or access denied."""
    if resp.status != 403:
        return False
    try:
        errors = resp.json().get("errors", [])
        return any(e.get("type") == "forbidden" for e in errors)
    except Exception:
        return False


def api_request(method, url, tokens, data=None, headers=None, tokens_path=None, _retried=False):
    """HH API call with Bearer + авто-refresh-once на 403 oauth.
    Returns (resp, tokens). Raises AuthError (после алерта) если refresh не спас.

    APPL fallback: on 403 "forbidden" (IP block) for GET requests, retries
    with the APPL (client_credentials) token.  POST /negotiations is never
    retried with APPL — it requires user auth."""
    h = {"User-Agent": config.HH_USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    h["Authorization"] = f"Bearer {tokens.get('access_token', '')}"
    resp = http_client.request(method, url, headers=h, data=data)

    # 403 oauth → refresh + retry
    if _is_auth_error(resp) and not _retried:
        try:
            tokens = refresh(tokens, tokens_path)
        except AuthError as e:
            telegram.send_alert(
                "🚨 <b>HH.ru auth failure</b>\n"
                f"Refresh token не сработал: {telegram.esc(str(e))}\n"
                "Нужна повторная OAuth-авторизация (docs/api-contract.md §3).")
            raise
        return api_request(method, url, tokens, data=data, headers=headers,
                           tokens_path=tokens_path, _retried=True)
    if _is_auth_error(resp) and _retried:
        telegram.send_alert("🚨 <b>HH.ru auth failure</b>\n403 oauth сразу после refresh — токен невалиден.")
        raise AuthError(f"403 oauth after refresh: {resp.text[:200]}")

    # 403 forbidden (not oauth) on GET → try APPL token fallback (IP block)
    if _is_forbidden(resp) and method == "GET" and not _retried:
        appl = _get_appl_token()
        if appl and appl != tokens.get("access_token", ""):
            h2 = dict(h)
            h2["Authorization"] = f"Bearer {appl}"
            resp2 = http_client.request(method, url, headers=h2, data=data)
            if resp2.status != 403:
                return resp2, tokens

    return resp, tokens
