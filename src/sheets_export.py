"""Step 7: полный JSON → Google Sheets HH_AI. Sheets — ТОЛЬКО визуализация.
Ни один модуль пайплайна не читает данные из Sheets (значения ячеек с данными).
Полная перезапись листа каждый прогон → лист всегда == vacancies.json."""
import json
import os
import urllib.parse

from . import config, http_client

COLUMNS = ["date", "title", "company", "salary", "location", "level", "url",
           "match", "cover-letter", "respond", "статус"]


def get_access_token():
    if not os.path.exists(config.GOOGLE_CREDS_PATH):
        return None
    with open(config.GOOGLE_CREDS_PATH) as fh:
        creds = json.load(fh)
    data = urllib.parse.urlencode({
        "client_id": creds["client_id"], "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    resp = http_client.request("POST", "https://oauth2.googleapis.com/token", data=data)
    if resp.status != 200:
        raise RuntimeError(f"google token refresh HTTP {resp.status}")
    return resp.json()["access_token"]


def record_to_row(rec):
    date = (rec.get("first_seen") or "")[:10]
    try:
        y, m, d = date.split("-")
        date = f"{d}.{m}.{y}"
    except ValueError:
        pass
    apply_url = rec.get("apply_url") or rec.get("url", "")
    return [
        date, rec.get("title", ""), rec.get("company", ""), rec.get("salary", ""),
        rec.get("location", ""), rec.get("level", ""), rec.get("url", ""),
        rec.get("match", ""), rec.get("cover_letter", ""),
        f'=HYPERLINK("{apply_url}";"🚀 Откликнуться")',
        rec.get("status", ""),
    ]


def build_rows(store_dict):
    """Header + все записи, сортировка: новые сверху (first_seen desc)."""
    recs = sorted(store_dict.values(), key=lambda r: r.get("first_seen", ""), reverse=True)
    return [COLUMNS] + [record_to_row(r) for r in recs]


def _sheets_url(path):
    return f"https://sheets.googleapis.com/v4/spreadsheets/{config.SPREADSHEET_ID}{path}"


def export(store_dict, dry_run=None):
    """Returns number of data rows written (excl. header)."""
    dry_run = config.dry_run() if dry_run is None else dry_run
    rows = build_rows(store_dict)
    if dry_run:
        return len(rows) - 1
    token = get_access_token()
    if not token:
        raise RuntimeError("no google credentials")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # 1. clear
    enc = urllib.parse.quote(f"{config.SHEET_NAME}!A:K", safe="")
    resp = http_client.request("POST", _sheets_url(f"/values/{enc}:clear"), headers=headers, data=b"{}")
    if resp.status != 200:
        raise RuntimeError(f"sheets clear HTTP {resp.status}: {resp.text[:200]}")
    # 2. write in batches of 200 rows (argv/payload limits)
    BATCH = 200
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        rng = f"{config.SHEET_NAME}!A{start + 1}"
        enc = urllib.parse.quote(rng, safe="")
        body = json.dumps({"range": rng, "majorDimension": "ROWS", "values": batch},
                          ensure_ascii=False).encode()
        resp = http_client.request(
            "PUT", _sheets_url(f"/values/{enc}?valueInputOption=USER_ENTERED"),
            headers=headers, data=body)
        if resp.status != 200:
            raise RuntimeError(f"sheets write HTTP {resp.status}: {resp.text[:200]}")
    return len(rows) - 1
