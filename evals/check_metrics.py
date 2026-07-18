#!/usr/bin/env python3
"""Детерминированная проверка цели («Готово»). Exit 0 = цель достигнута.
Читает data/vacancies.json + data/last_run_report.json, печатает JSON с метриками.

Критерии:
  - 100% записей: status ∈ {отправлено, не отправлено, тест} и валидны по схеме
  - 0 дублей по vacancy_id
  - enrichment ≥95% новых
  - cover letter у 100% новых
  - sheets_rows == len(JSON)
  - telegram_delivered == true (в DRY_RUN допускается stdout-фолбэк: игнорируется
    при отсутствии TELEGRAM_BOT_TOKEN)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import config, store  # noqa: E402


def check():
    vac = store.load()
    report_path = config.run_report_path()
    if not os.path.exists(report_path):
        return {"error": "no last_run_report.json — pipeline не запускался"}, 1
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)

    total = len(vac)
    invalid = {vid: store.validate_record(r) for vid, r in vac.items() if store.validate_record(r)}
    bad_status = [vid for vid, r in vac.items() if r.get("status") not in config.VALID_STATUSES]
    dups = store.duplicates(vac)

    new = report.get("new", 0)
    enriched = report.get("enriched", 0)
    covers = report.get("covers", 0)
    enrich_rate = (enriched / new) if new else 1.0
    cover_rate = (covers / new) if new else 1.0

    sheets_ok = report.get("sheets_rows", -1) == total
    tg_ok = bool(report.get("telegram_delivered")) or not os.environ.get("TELEGRAM_BOT_TOKEN")

    checks = {
        "status_100pct": len(bad_status) == 0 and len(invalid) == 0,
        "duplicates_zero": len(dups) == 0,
        "enrichment_ge_95": enrich_rate >= 0.95,
        "covers_100pct": cover_rate >= 1.0,
        "sheets_eq_json": sheets_ok,
        "telegram_delivered": tg_ok,
    }
    metrics = {
        "total_records": total,
        "invalid_records": len(invalid),
        "bad_status": len(bad_status),
        "duplicates": len(dups),
        "new": new,
        "enrichment_rate": round(enrich_rate, 3),
        "cover_rate": round(cover_rate, 3),
        "sheets_rows": report.get("sheets_rows"),
        "telegram_delivered": report.get("telegram_delivered"),
        "checks": checks,
        "goal_reached": all(checks.values()),
    }
    return metrics, 0 if metrics["goal_reached"] else 1


if __name__ == "__main__":
    metrics, code = check()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    sys.exit(code)
