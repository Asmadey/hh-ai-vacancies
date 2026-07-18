import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import http_client  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Изолированный data dir + чистое окружение."""
    monkeypatch.setenv("HH_PIPELINE_HOME", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setenv("HH_RESUME_ID", "resume-42")
    monkeypatch.setenv("APPLY_LIMIT", "0")
    return tmp_path


def make_resp(status, body=None, headers=None):
    raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else (body or b"")
    return http_client.HttpResponse(status, raw, headers or {})


class MockHttp:
    """FIFO очередь ответов, матчинг по подстроке URL. Записывает все вызовы."""

    def __init__(self):
        self.queue = []   # list of (substr, response_or_exception)
        self.calls = []   # list of dict(method, url, headers, data)

    def add(self, substr, response):
        self.queue.append((substr, response))

    def __call__(self, method, url, headers=None, data=None, timeout=25):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "data": data})
        for i, (substr, resp) in enumerate(self.queue):
            if substr in url:
                self.queue.pop(i)
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"Unexpected HTTP call: {method} {url}")

    def calls_to(self, substr):
        return [c for c in self.calls if substr in c["url"]]


@pytest.fixture
def mock_http(monkeypatch):
    mock = MockHttp()
    monkeypatch.setattr(http_client, "request", mock)
    return mock


@pytest.fixture
def no_sleep(monkeypatch):
    """Патчит time.sleep в apply, записывает задержки."""
    sleeps = []
    import src.apply as apply_mod
    monkeypatch.setattr(apply_mod.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


@pytest.fixture
def tg_capture(monkeypatch):
    """Перехват telegram._send."""
    sent = []
    from src import telegram
    monkeypatch.setattr(telegram, "_send", lambda text: (sent.append(text), True)[1])
    return sent


TOKENS = {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 1209600, "obtained_at": "2026-07-01T00:00:00+00:00"}


@pytest.fixture
def tokens_file(home):
    path = os.path.join(str(home), "data", "hh_tokens.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(TOKENS, fh)
    return path


def search_item(vid="100", name="AI Product Manager", **kw):
    return {
        "id": vid, "name": name,
        "alternate_url": f"https://hh.ru/vacancy/{vid}",
        "apply_alternate_url": f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}",
        "employer": {"name": kw.get("company", "Acme AI")},
        "area": {"name": kw.get("area", "Москва")},
        "salary": kw.get("salary"),
        "snippet": {"requirement": kw.get("requirement", "Опыт запуска AI продуктов")},
    }


def vacancy_details(vid="100", **kw):
    return {
        "id": vid, "name": kw.get("name", "AI Product Manager"),
        "alternate_url": f"https://hh.ru/vacancy/{vid}",
        "apply_alternate_url": f"https://hh.ru/applicant/vacancy_response?vacancyId={vid}",
        "employer": {"name": kw.get("company", "Acme AI")},
        "description": kw.get("description", "<p>Ищем <b>AI Product Manager</b> для запуска LLM-продуктов. Команда 10 человек.</p>"),
        "schedule": {"name": "Удаленная работа"},
        "work_format": kw.get("work_format", [{"name": "Удалённо"}]),
        "employment": {"name": "Полная занятость"},
        "experience": {"name": "3–6 лет"},
        "key_skills": [{"name": "LLM"}, {"name": "RAG"}],
        "salary": {"from": 300000, "to": 400000, "currency": "RUR", "gross": False},
        "archived": kw.get("archived", False),
    }
