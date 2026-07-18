"""TC-01, TC-04, TC-06, TC-12, evals: e2e DRY_RUN на fixtures (без сети)."""
import json
import os

from src import config, pipeline, store
from evals import check_metrics
from tests.conftest import make_resp, search_item, vacancy_details


def _mock_full_run(mock_http, monkeypatch, items):
    monkeypatch.setattr(config, "LEGACY_SEEN_PATH", "/nonexistent/seen.json")
    mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": len(items), "items": items}))
    for _ in range(len(config.KEYWORDS) - 1):
        mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": 0, "items": []}))
    for it in items:
        mock_http.add(f"api.hh.ru/vacancies/{it['id']}", make_resp(200, vacancy_details(it["id"], name=it["name"])))


def test_e2e_dry_run_exit_0(home, mock_http, monkeypatch, tokens_file, capsys):
    """TC-01: полный прогон, exit 0. TC-04: JSON валиден. TC-12: 100% статусов."""
    items = [search_item("100", "AI Product Manager"), search_item("200", "Head of AI")]
    _mock_full_run(mock_http, monkeypatch, items)

    assert pipeline.run() == 0

    vac = store.load()
    assert len(vac) == 2
    for rec in vac.values():
        assert store.validate_record(rec) == []
        assert rec["status"] in config.VALID_STATUSES
        assert rec["cover_letter"]           # TC-09: 100% новых с письмом
        assert rec["enriched"]               # TC-08
    report = json.load(open(config.run_report_path()))
    assert report["new"] == 2 and report["covers"] == 2 and report["enriched"] == 2
    assert report["sheets_rows"] == 2 == report["json_records"]
    out = capsys.readouterr().out
    assert "DRY_RUN" in out  # отчёт напечатан


def test_e2e_second_run_idempotent(home, mock_http, monkeypatch, tokens_file):
    """TC-06: повторный прогон тех же данных → 0 новых, 0 дублей."""
    items = [search_item("100", "AI Product Manager")]
    _mock_full_run(mock_http, monkeypatch, items)
    assert pipeline.run() == 0

    # второй прогон: та же выдача; enrich не должен вызываться (новых нет)
    mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": 1, "items": items}))
    for _ in range(len(config.KEYWORDS) - 1):
        mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": 0, "items": []}))
    assert pipeline.run() == 0

    vac = store.load()
    assert len(vac) == 1
    report = json.load(open(config.run_report_path()))
    assert report["new"] == 0 and report["duplicates"] == 0


def test_check_metrics_goal_reached(home, mock_http, monkeypatch, tokens_file):
    """evals/check_metrics.py → goal_reached, exit 0 после DRY_RUN прогона."""
    items = [search_item("100", "AI Product Manager")]
    _mock_full_run(mock_http, monkeypatch, items)
    assert pipeline.run() == 0
    metrics, code = check_metrics.check()
    assert code == 0, metrics
    assert metrics["goal_reached"] and metrics["duplicates"] == 0
    assert metrics["enrichment_rate"] >= 0.95 and metrics["cover_rate"] == 1.0


def test_pipeline_no_tokens_exits_2(home, mock_http, monkeypatch, tg_capture):
    monkeypatch.setattr(config, "LEGACY_SEEN_PATH", "/nonexistent/seen.json")
    assert pipeline.run() == 2
    assert any("HH pipeline" in t for t in tg_capture)


def test_migration_runs_on_first_run(home, mock_http, monkeypatch, tokens_file, tmp_path):
    """seen.json подхватывается при первом прогоне."""
    seen_path = str(tmp_path / "legacy_seen.json")
    json.dump({"https://hh.ru/vacancy/999": "2026-06-01T00:00:00+00:00"}, open(seen_path, "w"))
    monkeypatch.setattr(config, "LEGACY_SEEN_PATH", seen_path)
    items = [search_item("100", "AI Product Manager")]
    mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": 1, "items": items}))
    for _ in range(len(config.KEYWORDS) - 1):
        mock_http.add("api.hh.ru/vacancies?", make_resp(200, {"found": 0, "items": []}))
    mock_http.add("api.hh.ru/vacancies/100", make_resp(200, vacancy_details("100")))
    assert pipeline.run() == 0
    vac = store.load()
    assert "999" in vac and vac["999"]["migrated"]
    assert "100" in vac and not vac["100"]["migrated"]
    # мигрированный не попадает в кандидаты на отклик
    from src.apply import select_candidates
    assert "999" not in select_candidates(vac, [])
