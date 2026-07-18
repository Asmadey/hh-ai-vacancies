"""User OAuth: access/refresh tokens, авто-refresh при 403 oauth, алерт при фатале.
Tokens: data/hh_tokens.json {access_token, refresh_token, obtained_at, expires_in}."""
import json
import os
import urllib.parse

from . import config, http_client, telegram
from .store import now_iso

TOKEN_URL = f"{config.HH_API}/token"


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


def api_request(method, url, tokens, data=None, headers=None, tokens_path=None, _retried=False):
    """HH API call with Bearer + авто-refresh-once на 403 oauth.
    Returns (resp, tokens). Raises AuthError (после алерта) если refresh не спас."""
    h = {"User-Agent": config.HH_USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    h["Authorization"] = f"Bearer {tokens.get('access_token', '')}"
    resp = http_client.request(method, url, headers=h, data=data)
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
    return resp, tokens
