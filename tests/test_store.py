"""TC-04, TC-06, TC-07 + схема + миграция."""
import json
import os

from src import config, store


def test_new_record_valid(home):
    rec = store.new_record("123", "https://hh.ru/vacancy/123", "AI Lead")
    assert store.validate_record(rec) == []


def test_validate_missing_field(home):
    rec = store.new_record("123", "https://hh.ru/vacancy/123", "AI Lead")
    del rec["status"]
    assert any(p.startswith("missing:status") for p in store.validate_record(rec))


def test_validate_bad_status(home):
    rec = store.new_record("123", "https://hh.ru/vacancy/123", "AI Lead")
    rec["status"] = "в процессе"
    assert any(p.startswith("bad_status") for p in store.validate_record(rec))


def test_save_creates_backup(home):
    rec = store.new_record("1", "https://hh.ru/vacancy/1", "T")
    store.save({"1": rec})
    store.save({"1": rec, "2": store.new_record("2", "https://hh.ru/vacancy/2", "T2")})
    assert os.path.exists(config.vacancies_path() + ".bak")
    bak = json.load(open(config.vacancies_path() + ".bak"))
    assert len(bak) == 1  # бэкап = предыдущая версия


def test_merge_idempotent_no_duplicates(home):
    """TC-06: повторный merge тех же данных → 0 новых, 0 дублей."""
    recs = [store.new_record("1", "https://hh.ru/vacancy/1", "AI Lead"),
            store.new_record("2", "https://hh.ru/vacancy/2", "CPO")]
    vac = {}
    new1 = store.merge(vac, recs)
    new2 = store.merge(vac, [store.new_record("1", "https://hh.ru/vacancy/1", "AI Lead v2")])
    assert len(new1) == 2 and new2 == []
    assert len(vac) == 2 and store.duplicates(vac) == []


def test_merge_preserves_old_records(home):
    """TC-07: merge не трогает status/cover_letter/first_seen существующих."""
    old = store.new_record("1", "https://hh.ru/vacancy/1", "AI Lead")
    old["status"] = config.STATUS_SENT
    old["cover_letter"] = "письмо"
    first_seen = old["first_seen"]
    vac = {"1": old}
    store.merge(vac, [store.new_record("1", "https://hh.ru/vacancy/1", "AI Lead (updated)")])
    assert vac["1"]["status"] == config.STATUS_SENT
    assert vac["1"]["cover_letter"] == "письмо"
    assert vac["1"]["first_seen"] == first_seen
    assert vac["1"]["title"] == "AI Lead (updated)"  # метаданные обновились


def test_duplicates_detects_key_mismatch(home):
    rec = store.new_record("1", "https://hh.ru/vacancy/1", "T")
    assert store.duplicates({"2": rec}) == ["2"]


def test_migrate_seen(home, tmp_path):
    seen = {"https://hh.ru/vacancy/555?from=search": "2026-06-01T00:00:00+00:00",
            "https://example.com/not-a-vacancy": "2026-06-01T00:00:00+00:00"}
    seen_path = str(tmp_path / "seen.json")
    json.dump(seen, open(seen_path, "w"))
    vac, n = store.migrate_seen(seen_path=seen_path, store={})
    assert n == 1 and "555" in vac
    rec = vac["555"]
    assert rec["migrated"] is True
    assert rec["status"] == config.STATUS_NOT_SENT
    assert rec["first_seen"] == "2026-06-01T00:00:00+00:00"
    assert store.validate_record(rec) == []


def test_migrate_seen_skips_existing(home, tmp_path):
    seen_path = str(tmp_path / "seen.json")
    json.dump({"https://hh.ru/vacancy/1": "2026-06-01T00:00:00+00:00"}, open(seen_path, "w"))
    existing = {"1": store.new_record("1", "https://hh.ru/vacancy/1", "Real")}
    vac, n = store.migrate_seen(seen_path=seen_path, store=existing)
    assert n == 0 and vac["1"]["title"] == "Real"
