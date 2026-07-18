"""TC-10, TC-11, TC-12: отклики, статусы, backoff, паузы."""
import urllib.parse

import pytest

from src import apply as apply_mod
from src import config, http_client, store
from tests.conftest import TOKENS, make_resp


def _rec(vid="100", letter="Здравствуйте!\n\nПисьмо.\n\nБуду рад созвону."):
    r = store.new_record(vid, f"https://hh.ru/vacancy/{vid}", f"AI Lead {vid}")
    r["cover_letter"] = letter
    return r


def neg_403(value):
    return make_resp(403, {"errors": [{"type": "negotiations", "value": value}]})


def test_apply_success_message_is_cover_letter(home, mock_http, no_sleep):
    """TC-10: message == cover_letter записи; статус отправлено; applied_at выставлен."""
    rec = _rec()
    mock_http.add("/negotiations", make_resp(201, b"", {"Location": "/negotiations/xyz"}))
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_SENT and rec["applied_at"]
    sent = urllib.parse.parse_qs(mock_http.calls_to("/negotiations")[0]["data"].decode())
    assert sent["message"][0] == rec["cover_letter"]
    assert sent["vacancy_id"][0] == "100" and sent["resume_id"][0] == "resume-42"


def test_test_required_status(home, mock_http, no_sleep):
    """TC-12: test_required → «тест»."""
    rec = _rec()
    mock_http.add("/negotiations", neg_403("test_required"))
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_TEST


def test_limit_exceeded_stops_batch(home, mock_http, no_sleep):
    """TC-12: limit_exceeded → «не отправлено» + BatchStop."""
    rec = _rec()
    mock_http.add("/negotiations", neg_403("limit_exceeded"))
    with pytest.raises(apply_mod.BatchStop):
        apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_NOT_SENT
    assert rec["status_reason"] == "limit_exceeded"


def test_api_down_marks_not_sent(home, mock_http, no_sleep):
    """TC-12: network down → «не отправлено»/api_down."""
    rec = _rec()
    mock_http.add("/negotiations", http_client.NetworkError("conn refused"))
    with pytest.raises(apply_mod.BatchStop):
        apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_NOT_SENT and rec["status_reason"] == "api_down"


def test_already_applied_counts_as_sent(home, mock_http, no_sleep):
    rec = _rec()
    mock_http.add("/negotiations", neg_403("already_applied"))
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_SENT and rec["status_reason"] == "already_applied"


def test_429_backoff_respects_retry_after(home, mock_http, no_sleep):
    """TC-11: 429 → пауза ≥ Retry-After → retry → успех."""
    rec = _rec()
    mock_http.add("/negotiations", make_resp(429, b"", {"Retry-After": "7"}))
    mock_http.add("/negotiations", make_resp(201, b""))
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_SENT
    assert any(s >= 7 for s in no_sleep)


def test_429_exhausted_marks_rate_limited(home, mock_http, no_sleep):
    rec = _rec()
    for _ in range(4):
        mock_http.add("/negotiations", make_resp(429, b""))
    apply_mod.apply_one(rec, "resume-42", dict(TOKENS))
    assert rec["status"] == config.STATUS_NOT_SENT and rec["status_reason"] == "rate_limited"


def test_batch_pause_between_calls(home, mock_http, no_sleep):
    """TC-11: пауза ≥ APPLY_PAUSE_SEC между откликами."""
    vac = {"1": _rec("1"), "2": _rec("2")}
    mock_http.add("/negotiations", make_resp(201, b""))
    mock_http.add("/negotiations", make_resp(201, b""))
    m, _ = apply_mod.apply_batch(vac, ["1", "2"], "resume-42", dict(TOKENS), dry_run=False, pause=5)
    assert m["sent"] == 2
    assert any(s >= 5 for s in no_sleep)


def test_batch_stop_defers_remaining(home, mock_http, no_sleep):
    """После limit_exceeded остальные → не отправлено/deferred, 100% со статусом."""
    vac = {str(i): _rec(str(i)) for i in range(4)}
    mock_http.add("/negotiations", make_resp(201, b""))
    mock_http.add("/negotiations", neg_403("limit_exceeded"))
    m, _ = apply_mod.apply_batch(vac, ["0", "1", "2", "3"], "resume-42", dict(TOKENS), dry_run=False, pause=0)
    assert m["sent"] == 1 and m["not_sent"] == 3
    assert vac["2"]["status_reason"] == "deferred_limit_exceeded"
    assert all(v["status"] in config.VALID_STATUSES for v in vac.values())


def test_dry_run_makes_no_http_calls(home, mock_http, no_sleep):
    """TC-12/DRY_RUN: ни одного POST, статусы выставлены."""
    vac = {"1": _rec("1")}
    m, _ = apply_mod.apply_batch(vac, ["1"], "resume-42", dict(TOKENS), dry_run=True)
    assert mock_http.calls == []
    assert vac["1"]["status"] == config.STATUS_NOT_SENT and vac["1"]["status_reason"] == "dry_run"
    assert m["not_sent"] == 1


def test_apply_limit_caps_batch(home, mock_http, no_sleep):
    vac = {str(i): _rec(str(i)) for i in range(3)}
    mock_http.add("/negotiations", make_resp(201, b""))
    mock_http.add("/negotiations", make_resp(201, b""))
    m, _ = apply_mod.apply_batch(vac, ["0", "1", "2"], "resume-42", dict(TOKENS),
                                 dry_run=False, limit=2, pause=0)
    assert m["sent"] == 2
    assert vac["2"]["status_reason"] == "apply_limit"


def test_select_candidates(home):
    vac = {
        "1": _rec("1"),                                   # новый → да
        "2": _rec("2"), "3": _rec("3"), "4": _rec("4"), "5": _rec("5"),
    }
    vac["2"]["status"] = config.STATUS_SENT               # уже отправлен → нет
    vac["3"]["status_reason"] = "dry_run"                 # ретраябл → да
    vac["4"]["migrated"] = True                           # мигрирован → нет
    vac["5"]["cover_letter"] = ""                         # без письма → нет
    ids = apply_mod.select_candidates(vac, ["1"])
    assert sorted(ids) == ["1", "3"]
