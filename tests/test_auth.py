"""TC-02, TC-03: refresh-петля и алерты."""
import json

import pytest

from src import auth
from tests.conftest import TOKENS, make_resp


def oauth_403():
    return make_resp(403, {"errors": [{"type": "oauth", "value": "token_expired"}]})


def test_refresh_success_saves_new_pair(home, mock_http, tokens_file):
    mock_http.add("/token", make_resp(200, {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 100}))
    new = auth.refresh(dict(TOKENS), path=tokens_file)
    assert new["access_token"] == "AT2" and new["refresh_token"] == "RT2"
    saved = json.load(open(tokens_file))
    assert saved["access_token"] == "AT2" and saved["refresh_token"] == "RT2"


def test_refresh_not_expired_keeps_old(home, mock_http, tokens_file):
    mock_http.add("/token", make_resp(400, {"error": "invalid_grant", "error_description": "token not expired"}))
    new = auth.refresh(dict(TOKENS), path=tokens_file)
    assert new["access_token"] == "AT1"


def test_refresh_fatal_raises(home, mock_http, tokens_file):
    mock_http.add("/token", make_resp(400, {"error": "invalid_grant", "error_description": "token was revoked"}))
    with pytest.raises(auth.AuthError):
        auth.refresh(dict(TOKENS), path=tokens_file)


def test_api_request_403_triggers_refresh_and_retry(home, mock_http, tokens_file):
    """TC-02: 403 oauth → refresh → retry успешен."""
    mock_http.add("api.hh.ru/vacancies", oauth_403())
    mock_http.add("/token", make_resp(200, {"access_token": "AT2", "refresh_token": "RT2"}))
    mock_http.add("api.hh.ru/vacancies", make_resp(200, {"items": []}))
    resp, tokens = auth.api_request("GET", "https://api.hh.ru/vacancies?text=x", dict(TOKENS), tokens_path=tokens_file)
    assert resp.status == 200
    assert tokens["access_token"] == "AT2"
    retry_call = mock_http.calls_to("api.hh.ru/vacancies")[-1]
    assert retry_call["headers"]["Authorization"] == "Bearer AT2"


def test_refresh_failure_sends_alert(home, mock_http, tokens_file, tg_capture):
    """TC-03: refresh упал → Telegram-алерт + AuthError."""
    mock_http.add("api.hh.ru/vacancies", oauth_403())
    mock_http.add("/token", make_resp(400, {"error": "invalid_grant", "error_description": "token was revoked"}))
    with pytest.raises(auth.AuthError):
        auth.api_request("GET", "https://api.hh.ru/vacancies?text=x", dict(TOKENS), tokens_path=tokens_file)
    assert any("auth failure" in t for t in tg_capture)


def test_403_after_refresh_is_fatal(home, mock_http, tokens_file, tg_capture):
    mock_http.add("api.hh.ru/vacancies", oauth_403())
    mock_http.add("/token", make_resp(200, {"access_token": "AT2", "refresh_token": "RT2"}))
    mock_http.add("api.hh.ru/vacancies", oauth_403())
    with pytest.raises(auth.AuthError):
        auth.api_request("GET", "https://api.hh.ru/vacancies?text=x", dict(TOKENS), tokens_path=tokens_file)
    assert any("auth failure" in t for t in tg_capture)


def test_load_tokens_missing_file(home):
    with pytest.raises(auth.AuthError):
        auth.load_tokens()
