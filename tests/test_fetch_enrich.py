"""Фильтры fetch + TC-08 enrichment."""
import pytest

from src import config, enrich, fetch
from tests.conftest import TOKENS, make_resp, search_item, vacancy_details


def _add_search_responses(mock_http, items_first, items_rest=None):
    mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": len(items_first), "items": items_first}))
    for _ in range(len(config.KEYWORDS) - 1):
        mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": 0, "items": items_rest or []}))


def test_fetch_filters_and_dedups(home, mock_http):
    items = [
        search_item("1", "AI Product Manager"),
        search_item("1", "AI Product Manager"),                      # дубль внутри прогона
        search_item("2", "Backend Developer"),                       # junk
        search_item("3", "AI Lead", requirement="вакансия в архиве"),  # archive
        search_item("4", "Секретарь офиса", requirement="работа с документами"),  # irrelevant
        search_item("5", "Head of Product AI"),
    ]
    _add_search_responses(mock_http, items)
    records, found, _ = fetch.fetch_all(dict(TOKENS))
    ids = sorted(r["vacancy_id"] for r in records)
    assert ids == ["1", "5"]


def test_fetch_all_keywords_fail_raises(home, mock_http):
    for _ in config.KEYWORDS:
        mock_http.add("api.hh.ru/vacancies?", make_resp(500, b"oops"))
    with pytest.raises(RuntimeError):
        fetch.fetch_all(dict(TOKENS))


def test_format_salary():
    assert fetch.format_salary(None) == "не указана"
    assert fetch.format_salary({"from": 100000, "currency": "RUR", "gross": False}) == "от 100,000 RUR net"
    assert fetch.format_salary({"to": 5000, "currency": "USD"}) == "до 5,000 USD"


def test_parse_level_and_match():
    assert fetch.parse_level("Head of AI") == "head"
    assert fetch.parse_level("AI Lead") == "lead"
    assert fetch.match_reason("AI Product Manager") == "AI + управленческая роль"


def test_enrich_fills_structured_fields(home, mock_http):
    """TC-08: company, role, description(text), work_format, employment, experience, key_skills."""
    from src import store
    rec = store.new_record("100", "https://hh.ru/vacancy/100", "AI Product Manager")
    mock_http.add("api.hh.ru/vacancies/100", make_resp(200, vacancy_details("100")))
    ok, _ = enrich.enrich_record(rec, dict(TOKENS))
    assert ok and rec["enriched"]
    assert rec["company"] == "Acme AI"
    assert "AI Product Manager" in rec["description"] and "<" not in rec["description"]
    assert rec["work_format"] == "Удалённо"
    assert rec["employment"] == "Полная занятость"
    assert rec["experience"] == "3–6 лет"
    assert rec["key_skills"] == ["LLM", "RAG"]
    assert "300,000" in rec["salary"]


def test_enrich_archived_marks_not_sent(home, mock_http):
    from src import store
    rec = store.new_record("101", "https://hh.ru/vacancy/101", "AI Lead")
    mock_http.add("api.hh.ru/vacancies/101", make_resp(200, vacancy_details("101", archived=True)))
    ok, _ = enrich.enrich_record(rec, dict(TOKENS))
    assert ok
    assert rec["status"] == config.STATUS_NOT_SENT and rec["status_reason"] == "archived"


def test_enrich_http_error_returns_false(home, mock_http):
    from src import store
    rec = store.new_record("102", "https://hh.ru/vacancy/102", "AI Lead")
    mock_http.add("api.hh.ru/vacancies/102", make_resp(404, {"errors": [{"type": "not_found"}]}))
    ok, _ = enrich.enrich_record(rec, dict(TOKENS))
    assert not ok and not rec["enriched"]
