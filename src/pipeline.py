"""Оркестратор: auth → fetch → merge/dedup → enrich → cover → apply → sheets → telegram.
Exit 0 = успех. Пишет data/last_run_report.json для evals/check_metrics.py."""
import json
import os
import sys
from datetime import datetime

from . import apply as apply_mod
from . import auth, config, cover, enrich, fetch, sheets_export, store, telegram


def write_report(metrics):
    path = config.run_report_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)


def run():
    dry = config.dry_run()
    print(f"[pipeline] start (DRY_RUN={dry})", file=sys.stderr)

    # 1. auth
    try:
        tokens = auth.load_tokens()
    except auth.AuthError as e:
        telegram.send_alert(f"🚨 <b>HH pipeline</b>: {telegram.esc(str(e))}")
        return 2

    # migrate legacy seen.json on first run
    vac = store.load()
    if not vac and os.path.exists(config.LEGACY_SEEN_PATH):
        vac, n = store.migrate_seen(store=vac)
        print(f"[pipeline] migrated {n} records from seen.json", file=sys.stderr)

    # 2. fetch
    try:
        fetched, found_total, tokens = fetch.fetch_all(tokens)
    except auth.AuthError:
        return 2
    except RuntimeError as e:
        telegram.send_alert(f"🚨 <b>HH pipeline</b>: fetch failed — {telegram.esc(str(e))}")
        return 3
    print(f"[pipeline] fetched {len(fetched)} relevant (found {found_total})", file=sys.stderr)

    # 3. merge + dedup
    new_ids = store.merge(vac, fetched)
    dups = store.duplicates(vac)
    print(f"[pipeline] new: {len(new_ids)}, dups: {len(dups)}", file=sys.stderr)

    # 4. enrich (только новые)
    try:
        enriched, tokens = enrich.enrich_new(vac, new_ids, tokens)
    except auth.AuthError:
        store.save(vac)
        return 2

    # 5. cover letters (только новые)
    covers = cover.generate_all(vac, new_ids)

    # 6. apply
    candidates = apply_mod.select_candidates(vac, new_ids)
    resume = config.resume_id()
    if not dry and not resume:
        telegram.send_alert("🚨 <b>HH pipeline</b>: HH_RESUME_ID не задан — отклики невозможны.")
        store.save(vac)
        return 2
    try:
        apply_metrics, tokens = apply_mod.apply_batch(vac, candidates, resume, tokens)
    except auth.AuthError:
        store.save(vac)
        return 2

    # persist source of truth ДО экспорта
    store.save(vac)

    # 7. sheets export (visualization only)
    try:
        sheets_rows = sheets_export.export(vac)
    except Exception as e:
        print(f"[pipeline] sheets export failed: {e}", file=sys.stderr)
        telegram.send_alert(f"⚠️ <b>HH pipeline</b>: Sheets export failed — {telegram.esc(str(e))}")
        sheets_rows = -1

    # 8. telegram report
    metrics = {
        "date": datetime.now().strftime("%d.%m.%Y"),
        "dry_run": dry,
        "found": len(fetched),
        "new": len(new_ids),
        "enriched": enriched,
        "covers": covers,
        "sent": apply_metrics["sent"],
        "tests": apply_metrics["tests"],
        "not_sent": apply_metrics["not_sent"],
        "sheets_rows": sheets_rows,
        "json_records": len(vac),
        "duplicates": len(dups),
        "candidates": len(candidates),
    }
    delivered = telegram.send_report(metrics)
    metrics["telegram_delivered"] = delivered
    write_report(metrics)
    print(f"[pipeline] done: {json.dumps(metrics, ensure_ascii=False)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(run())
