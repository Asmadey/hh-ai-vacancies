"""TC-05, TC-13, TC-14."""
import glob
import os

from src import config, sheets_export, store, telegram


def _vac(n=3):
    vac = {}
    for i in range(n):
        r = store.new_record(str(i), f"https://hh.ru/vacancy/{i}", f"AI Lead {i}")
        r["cover_letter"] = "письмо"
        r["status"] = config.STATUS_SENT
        vac[str(i)] = r
    return vac


def test_rows_match_json(home):
    """TC-13: header + все записи, колонка «статус» присутствует и заполнена."""
    vac = _vac(3)
    rows = sheets_export.build_rows(vac)
    assert len(rows) == 4
    assert rows[0] == sheets_export.COLUMNS and "статус" in rows[0]
    status_idx = rows[0].index("статус")
    title_idx = rows[0].index("title")
    titles_in_sheet = sorted(r[title_idx] for r in rows[1:])
    assert titles_in_sheet == sorted(v["title"] for v in vac.values())
    assert all(r[status_idx] == config.STATUS_SENT for r in rows[1:])


def test_export_dry_run_no_http(home, mock_http):
    n = sheets_export.export(_vac(5), dry_run=True)
    assert n == 5 and mock_http.calls == []


def test_no_module_reads_sheets(home):
    """TC-05: sheets.googleapis упоминается только в sheets_export.py — Sheets никто не читает."""
    src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    offenders = []
    for path in glob.glob(os.path.join(src_dir, "*.py")):
        if os.path.basename(path) == "sheets_export.py":
            continue
        if "sheets.googleapis" in open(path, encoding="utf-8").read():
            offenders.append(os.path.basename(path))
    assert offenders == []


def test_report_numbers_match_metrics(home):
    """TC-14: 5 чисел отчёта == агрегатам."""
    m = {"date": "18.07.2026", "found": 42, "new": 7, "covers": 7, "sent": 5,
         "tests": 2, "not_sent": 0, "dry_run": False}
    text = telegram.format_report(m)
    assert "<b>42</b>" in text and "<b>7</b>" in text and "<b>5</b>" in text and "<b>2</b>" in text
    assert "Cover letters: <b>7</b>" in text
    assert 'href="' + config.SHEET_URL in text


def test_send_report_http_200(home, monkeypatch, mock_http):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    from tests.conftest import make_resp
    mock_http.add("api.telegram.org", make_resp(200, {"ok": True}))
    ok = telegram.send_report({"date": "x", "found": 1, "new": 1, "covers": 1,
                               "sent": 0, "tests": 0, "not_sent": 1, "dry_run": True})
    assert ok is True


def test_send_without_token_returns_false(home):
    assert telegram._send("hi") is False
