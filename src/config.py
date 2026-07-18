"""Central config: env loading, paths, constants. Stdlib only."""
import os
import re

def load_env_file(path=None):
    """Load KEY=VALUE lines from ~/.hermes/.env into os.environ (no overwrite)."""
    path = path or os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val

load_env_file()

# --- Paths (overridable for tests via HH_PIPELINE_HOME) ---
BASE_DIR = os.environ.get("HH_PIPELINE_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def data_dir():
    return os.path.join(os.environ.get("HH_PIPELINE_HOME", BASE_DIR), "data")

def vacancies_path():
    return os.path.join(data_dir(), "vacancies.json")

def tokens_path():
    return os.path.join(data_dir(), "hh_tokens.json")

def run_report_path():
    return os.path.join(data_dir(), "last_run_report.json")

LEGACY_SEEN_PATH = os.path.expanduser("~/.hermes/hh_ai_seen.json")

# --- Runtime flags ---
def dry_run():
    return os.environ.get("DRY_RUN", "1") == "1"  # safe default: dry

def apply_limit():
    return int(os.environ.get("APPLY_LIMIT", "0"))  # 0 = no cap

APPLY_PAUSE_SEC = float(os.environ.get("APPLY_PAUSE_SEC", "5"))

# --- HH ---
HH_USER_AGENT = "Product AI Vacancy Bot / 1.0 (sagestaf@gmail.com)"
HH_API = "https://api.hh.ru"

def resume_id():
    return os.environ.get("HH_RESUME_ID", "")

# --- Google Sheets ---
SPREADSHEET_ID = "1R4uQG-yy2mZ4zuJVkQgrfxoVW6N60suUmnEVKBFolok"
SHEET_GID = 1464494667
SHEET_NAME = "HH_AI"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={SHEET_GID}"
GOOGLE_CREDS_PATH = os.path.expanduser("~/.config/gws/credentials.json")

# --- Telegram ---
def telegram_bot_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")

def telegram_chat_id():
    return os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Ollama (cover letters) ---
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "deepseek-v4-flash")

def ollama_api_key():
    return os.environ.get("OLLAMA_API_KEY", "")

COVER_LETTER_MAX_TOKENS = int(os.environ.get("COVER_LETTER_MAX_TOKENS", "900"))
COVER_LETTER_TEMP = float(os.environ.get("COVER_LETTER_TEMP", "0.4"))
COVER_LETTER_WORKERS = int(os.environ.get("COVER_LETTER_WORKERS", "10"))

# --- Search keywords & filters (ported from scripts/hh_ai_vacancies.py) ---
KEYWORDS = [
    "Product AI", "AI Lead", "AI Transformation Lead", "AI Product Manager",
    "Владелец AI продукта", "Руководитель по внедрению AI", "AI-First",
    "Специалист по внедрению ИИ", "директор по продукту", "Product Director",
    "Chief Product Officer", "CPO", "Head of Product",
]

JUNK_RE = re.compile(
    r"\b(data entry|virtual assistant|customer support|chat support|moderator|"
    r"content writer|translator|telemarketing|cold calling|sales representative|"
    r"social media manager|курьер|водитель|охранник|уборщица|кассир|продавец|"
    r"sales manager|smm|designer|developer|analyst|engineer|дизайнер|разработчик|"
    r"аналитик|инженер)\b", re.I)

RESUME_RE = re.compile(
    r"\b(резюме|resume|cv|curriculum vitae|ищу работу|open to work|available for hire|"
    r"looking for (?:a )?(?:job|position|role|opportunity))\b", re.I)

ARCHIVE_RE = re.compile(
    r"\b(в архиве|архивная|архив|удалена|закрыта|приостановлена|неактивна|не активна|"
    r"вакансия закрыта|вакансия не актуальна|вакансия в архиве|"
    r"archived?|in archive|expired|closed|no longer accepting|position closed|"
    r"vacancy closed|not currently hiring|paused|suspended|on hold)\b", re.I)

# --- Statuses (source of truth) ---
STATUS_SENT = "отправлено"
STATUS_NOT_SENT = "не отправлено"
STATUS_TEST = "тест"
VALID_STATUSES = {STATUS_SENT, STATUS_NOT_SENT, STATUS_TEST}
