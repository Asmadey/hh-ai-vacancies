"""Step 6: POST /negotiations. Статусы: отправлено | не отправлено | тест.
Полный маппинг ошибок — docs/api-contract.md §1."""
import sys
import time
import urllib.parse

from . import auth, config, http_client, telegram
from .store import now_iso

NEGOTIATIONS_URL = f"{config.HH_API}/negotiations"
MAX_RETRIES_429 = 3


class BatchStop(Exception):
    """Останов батча: limit_exceeded / resume_not_found / API down."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _post_negotiation(rec, resume_id, tokens, tokens_path=None):
    data = urllib.parse.urlencode({
        "vacancy_id": rec["vacancy_id"],
        "resume_id": resume_id,
        "message": rec.get("cover_letter", ""),
    }).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return auth.api_request("POST", NEGOTIATIONS_URL, tokens, data=data,
                            headers=headers, tokens_path=tokens_path)


def _negotiation_error(resp):
    for e in resp.json().get("errors", []):
        if e.get("type") == "negotiations":
            return e.get("value", "")
        if e.get("type") == "captcha_required":
            return "captcha_required"
    return ""


def _set_status(rec, status, reason=""):
    rec["status"] = status
    rec["status_reason"] = reason
    rec["updated_at"] = now_iso()
    if status == config.STATUS_SENT and reason != "already_applied":
        rec["applied_at"] = now_iso()


def apply_one(rec, resume_id, tokens, tokens_path=None):
    """Returns tokens. Sets rec status. Raises BatchStop when batch must halt."""
    retries = 0
    while True:
        try:
            resp, tokens = _post_negotiation(rec, resume_id, tokens, tokens_path)
        except http_client.NetworkError:
            _set_status(rec, config.STATUS_NOT_SENT, "api_down")
            raise BatchStop("api_down")
        except auth.AuthError:
            _set_status(rec, config.STATUS_NOT_SENT, "auth_failed")
            raise

        if resp.status == 201:
            _set_status(rec, config.STATUS_SENT)
            return tokens

        if resp.status == 429:
            retries += 1
            if retries > MAX_RETRIES_429:
                _set_status(rec, config.STATUS_NOT_SENT, "rate_limited")
                return tokens
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 5 * (2 ** (retries - 1))
            time.sleep(delay)
            continue

        err = _negotiation_error(resp)
        if err == "test_required":
            _set_status(rec, config.STATUS_TEST, "test_required")
            return tokens
        if err == "already_applied":
            _set_status(rec, config.STATUS_SENT, "already_applied")
            return tokens
        if err == "limit_exceeded":
            _set_status(rec, config.STATUS_NOT_SENT, "limit_exceeded")
            raise BatchStop("limit_exceeded")
        if err == "resume_not_found":
            _set_status(rec, config.STATUS_NOT_SENT, "resume_not_found")
            telegram.send_alert("🚨 <b>HH.ru</b>: resume_not_found — проверь HH_RESUME_ID.")
            raise BatchStop("resume_not_found")
        if err in ("invalid_vacancy", "archived"):
            _set_status(rec, config.STATUS_NOT_SENT, "invalid_vacancy")
            return tokens
        if err == "captcha_required":
            _set_status(rec, config.STATUS_NOT_SENT, "captcha")
            telegram.send_alert("🚨 <b>HH.ru</b>: captcha_required на отклике — нужен ручной вход.")
            raise BatchStop("captcha")
        if resp.status >= 500:
            _set_status(rec, config.STATUS_NOT_SENT, "api_down")
            raise BatchStop("api_down")
        _set_status(rec, config.STATUS_NOT_SENT, err or f"http_{resp.status}")
        return tokens


def apply_batch(store_dict, candidate_ids, resume_id, tokens, tokens_path=None,
                dry_run=None, limit=None, pause=None):
    """Applies to candidates in order. Returns (metrics dict, tokens).
    DRY_RUN: никаких POST, статус 'не отправлено'/dry_run (не выдумываем результат)."""
    dry_run = config.dry_run() if dry_run is None else dry_run
    limit = config.apply_limit() if limit is None else limit
    pause = config.APPLY_PAUSE_SEC if pause is None else pause

    applied = 0
    m = {"sent": 0, "tests": 0, "not_sent": 0}
    for i, vid in enumerate(candidate_ids):
        rec = store_dict[vid]
        if dry_run:
            _set_status(rec, config.STATUS_NOT_SENT, "dry_run")
            m["not_sent"] += 1
            continue
        if limit and applied >= limit:
            _set_status(rec, config.STATUS_NOT_SENT, "apply_limit")
            m["not_sent"] += 1
            continue
        if i > 0 and pause:
            time.sleep(pause)
        try:
            tokens = apply_one(rec, resume_id, tokens, tokens_path)
        except BatchStop as e:
            print(f"[apply] batch stopped: {e.reason}", file=sys.stderr)
            m["not_sent"] += 1
            # остальные — «не отправлено», перенос на следующий прогон
            for rest in candidate_ids[i + 1:]:
                _set_status(store_dict[rest], config.STATUS_NOT_SENT, f"deferred_{e.reason}")
                m["not_sent"] += 1
            break
        applied += 1
        if rec["status"] == config.STATUS_SENT:
            m["sent"] += 1
        elif rec["status"] == config.STATUS_TEST:
            m["tests"] += 1
        else:
            m["not_sent"] += 1
    return m, tokens


def select_candidates(store_dict, new_ids):
    """Кому откликаемся: новые за прогон + недоотправленные с прошлых прогонов.
    migrated и уже отправленные/тестовые — никогда."""
    RETRYABLE = {"dry_run", "api_down", "rate_limited", "limit_exceeded", "apply_limit",
                 "auth_failed", "captcha"}
    ids = list(new_ids)
    for vid, rec in store_dict.items():
        if vid in ids or rec.get("migrated"):
            continue
        reason = rec.get("status_reason", "")
        if rec.get("status") == config.STATUS_NOT_SENT and (
                reason in RETRYABLE or reason.startswith("deferred_")):
            ids.append(vid)
    # только с cover letter
    return [vid for vid in ids if store_dict[vid].get("cover_letter")]
