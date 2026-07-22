"""TOK-06: offline-тесты HH.ru OAuth-менеджера (scripts/hh_oauth_manager.py).

Менеджер гоняет HTTP через src.http_client.request — поэтому всё мокается
monkeypatch'ем одного символа. Env-файл и data/ уводятся в tmp через HH_ENV_FILE
и HH_PIPELINE_HOME. Никакой сети.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))  # noqa: E402
import hh_oauth_manager as mgr  # noqa: E402
from src import http_client  # noqa: E402


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Временный env-файл + изолированный data dir."""
    p = tmp_path / "env.env"
    p.write_text(
        "HH_CLIENT_ID=CID\n"
        "HH_CLIENT_SECRET=CSEC\n"
        "HH_REDIRECT_URI=https://piramiza.com/cb\n"
        "HH_OAUTH_ACCESS_TOKEN=AT_OLD\n"
        "HH_OAUTH_REFRESH_TOKEN=RT_OLD\n"
        "HH_OAUTH_EXPIRES_AT=0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HH_ENV_FILE", str(p))
    monkeypatch.setenv("HH_PIPELINE_HOME", str(tmp_path / "data_root"))
    os.makedirs(tmp_path / "data_root" / "data", exist_ok=True)
    return p


def _resp(status, body):
    raw = json.dumps(body).encode()
    return http_client.HttpResponse(status, raw, {})


def _read_env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def _read_tokens():
    with open(mgr.config.tokens_path(), encoding="utf-8") as f:
        return json.load(f)


# --- PKCE --------------------------------------------------------------------

def test_pkce_shape():
    v, c = mgr.generate_pkce()
    assert len(v) >= 32
    # S256 challenge — base64url SHA256 верифа, без паддинга
    assert "=" not in c and "+" not in c and "/" not in c
    import hashlib, base64
    expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert c == expect


# --- refresh -----------------------------------------------------------------

def test_refresh_success_writes_pair(env_file, monkeypatch):
    calls = []
    def fake(method, url, headers=None, data=None, timeout=25):
        calls.append((method, url, data))
        return _resp(200, {"access_token": "AT_NEW", "refresh_token": "RT_NEW", "expires_in": 1209600})
    monkeypatch.setattr(http_client, "request", fake)

    mgr.mode_refresh()

    env = _read_env(env_file)
    assert env["HH_OAUTH_ACCESS_TOKEN"] == "AT_NEW"
    assert env["HH_OAUTH_REFRESH_TOKEN"] == "RT_NEW"
    assert int(env["HH_OAUTH_EXPIRES_AT"]) > 0
    # мост в data/hh_tokens.json (формат src/auth.py)
    toks = _read_tokens()
    assert toks["access_token"] == "AT_NEW"
    assert toks["refresh_token"] == "RT_NEW"
    assert toks["expires_in"] == 1209600
    assert "obtained_at" in toks
    # single seam: ровно один POST на /token
    assert len(calls) == 1 and calls[0][0] == "POST" and "/token" in calls[0][1]
    assert b"grant_type=refresh_token" in calls[0][2]


def test_refresh_invalid_grant_exits(env_file, monkeypatch, capsys):
    def fake(method, url, headers=None, data=None, timeout=25):
        return _resp(400, {"error": "invalid_grant", "error_description": "expired"})
    monkeypatch.setattr(http_client, "request", fake)

    with pytest.raises(SystemExit):
        mgr.mode_refresh()
    out = capsys.readouterr().out
    assert "invalid_grant" in out or "refresh failed" in out
    # старая пара не перезаписана при фатале
    assert _read_env(env_file)["HH_OAUTH_ACCESS_TOKEN"] == "AT_OLD"


def test_refresh_network_fatal_exits(env_file, monkeypatch):
    def fake(method, url, headers=None, data=None, timeout=25):
        raise http_client.NetworkError("dns down")
    monkeypatch.setattr(http_client, "request", fake)
    with pytest.raises(SystemExit):
        mgr.mode_refresh()


# --- exchange ----------------------------------------------------------------

def test_exchange_success(env_file, monkeypatch):
    # verifier нужен для exchange
    env_file.write_text(env_file.read_text() + "HH_OAUTH_CODE_VERIFIER=verifier123\n", encoding="utf-8")

    def fake(method, url, headers=None, data=None, timeout=25):
        assert b"grant_type=authorization_code" in data
        assert b"code=CODE123" in data
        assert b"code_verifier=verifier123" in data
        return _resp(200, {"access_token": "AT_X", "refresh_token": "RT_X", "expires_in": 100})
    monkeypatch.setattr(http_client, "request", fake)

    mgr.exchange_code("CODE123")

    assert _read_env(env_file)["HH_OAUTH_ACCESS_TOKEN"] == "AT_X"
    toks = _read_tokens()
    assert toks["access_token"] == "AT_X" and toks["expires_in"] == 100


def test_exchange_missing_verifier_exits(env_file, monkeypatch):
    with pytest.raises(SystemExit):
        mgr.exchange_code("CODE")
    out = ""
    # ничего не отправлено в сеть
    assert not os.path.exists(mgr.config.tokens_path())


def test_exchange_non200_exits(env_file, monkeypatch):
    env_file.write_text(env_file.read_text() + "HH_OAUTH_CODE_VERIFIER=v\n", encoding="utf-8")
    monkeypatch.setattr(http_client, "request", lambda *a, **k: _resp(400, {"error": "bad_verification_code"}))
    with pytest.raises(SystemExit):
        mgr.exchange_code("CODE")


# --- bridge ------------------------------------------------------------------

def test_bridge_writes_store(env_file, monkeypatch):
    env_file.write_text(
        env_file.read_text().split("HH_OAUTH_ACCESS_TOKEN=AT_OLD")[0]
        + "HH_OAUTH_ACCESS_TOKEN=AT_BR\nHH_OAUTH_REFRESH_TOKEN=RT_BR\nHH_OAUTH_EXPIRES_AT=9999999999\n",
        encoding="utf-8",
    )
    mgr.mode_bridge()
    toks = _read_tokens()
    assert toks["access_token"] == "AT_BR"
    assert toks["refresh_token"] == "RT_BR"


def test_bridge_empty_exits(env_file, monkeypatch):
    env_file.write_text("HH_CLIENT_ID=CID\nHH_CLIENT_SECRET=CSEC\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        mgr.mode_bridge()


# --- env round-trip ----------------------------------------------------------

def test_save_env_key_updates_and_appends(env_file):
    mgr.save_env_key("HH_OAUTH_ACCESS_TOKEN", "AT_FRESH")
    env = _read_env(env_file)
    assert env["HH_OAUTH_ACCESS_TOKEN"] == "AT_FRESH"
    # дополнение нового ключа
    mgr.save_env_key("HH_OAUTH_CODE_VERIFIER", "VVV")
    assert _read_env(env_file)["HH_OAUTH_CODE_VERIFIER"] == "VVV"


# --- mask --------------------------------------------------------------------

def test_mask_redacts():
    assert mgr._mask("") == "[empty]"
    assert mgr._mask("AT12345678901234567890") == "AT123456…7890"
    # префикс/суффикс показаны (отпечаток), середина редуцирована
    masked = mgr._mask("FULLTOKEN_VALUE_NEVER_SHOWN")
    assert masked.startswith("FULLTOKE") and masked.endswith("HOWN")
    assert "VALUE" not in masked and "NEVER" not in masked


# --- link --------------------------------------------------------------------

def test_link_prints_auth_url(env_file, monkeypatch, capsys):
    mgr.mode_link()
    out = capsys.readouterr().out
    assert "hh.ru/oauth/authorize" in out
    assert "response_type=code" in out
    assert "code_challenge_method=S256" in out
    # verifier+state сохранены в env
    env = _read_env(env_file)
    assert env["HH_OAUTH_CODE_VERIFIER"]
    assert env["HH_OAUTH_STATE"]