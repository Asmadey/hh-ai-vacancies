#!/usr/bin/env python3
"""Одноразовая миграция ~/.hermes/hh_ai_seen.json → data/vacancies.json.
Запуск: python3 -m scripts.migrate_seen [path_to_seen.json]"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import config, store  # noqa: E402


def main():
    seen_path = sys.argv[1] if len(sys.argv) > 1 else config.LEGACY_SEEN_PATH
    vac = store.load()
    before = len(vac)
    vac, migrated = store.migrate_seen(seen_path=seen_path, store=vac)
    bad = [vid for vid, rec in vac.items() if store.validate_record(rec)]
    if bad:
        print(f"ERROR: {len(bad)} invalid records, abort (no write)", file=sys.stderr)
        return 1
    store.save(vac)
    print(f"Migrated {migrated} records ({before} -> {len(vac)}) into {config.vacancies_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
